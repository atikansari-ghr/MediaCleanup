#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MediaCleanup.py (Enhanced)
Production-grade Windows 11 Python 3.11 media cleanup/merge tool using MKVToolNix.

ENHANCEMENT: When two similar MKV files are found in movie directory with different audio tracks:
- Select the best x265/HEVC video track from either file
- Collect ALL Hindi, Telugu, and English audio tracks from BOTH files
- Select the best English subtitle
- Merge into a single optimized MKV file

Key guarantees:
- Never modifies source files in place.
- Uses a safe working mirror for required inputs.
- Uses mkvmerge -J JSON identification for track decisions.
- Writes output to temp file then atomically moves into destination.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as _dt
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =========================
# Configurable constants
# =========================

@dataclasses.dataclass(frozen=True)
class Config:
    # Tool paths — loaded from MediaCleanup.toml (same folder as this script).
    # No defaults here on purpose: load_config() is the single source of truth.
    MKVTOOLNIX_DIR: Path
    MKVMERGE_EXE: Path
    MKVPROPEDIT_EXE: Path
    MKVINFO_EXE: Path
    MKVEXTRACT_EXE: Path

    # Optional: FileBot (portable licensed) for pre-rename normalization.
    # If the path doesn't exist, FileBot steps are skipped gracefully.
    FILEBOT_EXE: Path

    # Roots — loaded from MediaCleanup.toml [paths]
    MOVIES_ROOT: Path
    TV_ROOT: Path
    WORK_ROOT: Path
    OUTPUT_ROOT: Path

    FILEBOT_DB: str = "TheMovieDB"

    # Cover art API keys — MediaCleanup.toml [coverart] section.
    # An empty string disables that source; local poster files always work.
    TMDB_API_KEY: str = ""
    FANARTTV_API_KEY: str = ""
    OMDB_API_KEY: str = ""

    # OpenSubtitles.com — MediaCleanup.toml [subtitles] section (--subtitles mode).
    # All three credentials are required for downloads; languages are ISO 639-1.
    OS_API_KEY: str = ""
    OS_USERNAME: str = ""
    OS_PASSWORD: str = ""
    SUB_LANGS: Tuple[str, ...] = ("en",)

    # Similarity grouping for Movies (per-folder)
    SIMILARITY_THRESHOLD_DEFAULT: float = 0.88

    # Language detection mapping (ISO + fuzzy tokens)
    # Keys are canonical language labels used by output bracket list.
    LANG_CANONICAL_ORDER: Tuple[str, ...] = ("Hin", "Eng", "Tel")
    # Full display names used in the output filename bracket list and track naming.
    # Use default_factory to avoid mutable-default dataclass errors (e.g., Python 3.13+).
    LANG_DISPLAY_MAP: Dict[str, str] = dataclasses.field(default_factory=lambda: {
        "Tel": "Telugu",
        "Hin": "Hindi",
        "Eng": "English",
    })

    # Canonical -> accepted ISO codes (lower)
    LANG_ISO_CODES: Dict[str, Tuple[str, ...]] = dataclasses.field(default_factory=lambda: {
        "Tel": ("tel", "te"),
        "Hin": ("hin", "hi"),
        "Eng": ("eng", "en"),
    })

    # Canonical -> fuzzy name tokens (lower; substring checks)
    LANG_NAME_TOKENS: Dict[str, Tuple[str, ...]] = dataclasses.field(default_factory=lambda: {
        "Tel": ("telugu", "tel", "తెలుగు", "తెలుగ", "telegu"),  # include common misspelling
        "Hin": ("hindi", "hin", "हिंदी", "हिन्दी"),
        "Eng": ("english", "eng"),
    })

    # Exclude audio if name indicates commentary/descriptive
    AUDIO_EXCLUDE_TOKENS: Tuple[str, ...] = ("commentary", "descriptive", "description", "director", "narration")

    # Video codec preference
    VIDEO_CODEC_PREF: Tuple[str, ...] = ("hevc", "h265", "x265", "avc", "h264", "x264")

    # Resolution targets — height-based (2160p, 1080p, 720p)
    RES_TARGETS: Tuple[int, ...] = (2160, 1080, 720)
    # Width counterparts paired 1-to-1 with RES_TARGETS (used as primary signal)
    RES_WIDTH_TARGETS: Tuple[int, ...] = (3840, 1920, 1280)

    # Audio codec preference (best first)
    AUDIO_CODEC_RANK: Tuple[str, ...] = (
        "a_truehd", "dts-hd", "dts_hd", "dts", "eac3", "ac3", "aac", "mp3", "vorbis", "opus"
    )

    # Subtitle codec preference (best first)
    SUB_CODEC_RANK: Tuple[str, ...] = (
        "s_text/utf8", "s_text/ass", "s_text/ssa", "s_text/webvtt", "s_hdmv/pgs", "s_vobsub"
    )

    # Working copy caching
    # By default: reuse working file if size+mtime match; if mismatch, recopy.
    # Optional: compute sha256 when size matches but mtime differs (enabled here for safety).
    HASH_ON_MTIME_MISMATCH: bool = True

    # Long path handling: use \\?\ prefix for Windows paths when needed
    ENABLE_WIN_LONG_PATH_PREFIX: bool = True


class ConfigError(Exception):
    """Raised when MediaCleanup.toml is missing or invalid."""


_SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = _SCRIPT_DIR / "MediaCleanup.toml"


def load_config(config_file: Path = CONFIG_FILE) -> Config:
    """
    Load tool/media paths from MediaCleanup.toml (same folder as the script).

    Required:
      [tools] mkvtoolnix_dir
      [paths] movies_root, tv_root, work_root, output_root
    Optional:
      [tools] mkvmerge/mkvpropedit/mkvinfo/mkvextract  (default: <mkvtoolnix_dir>\\<name>.exe)
      [filebot] exe, db                                 (FileBot skipped if exe missing)
    """
    if not config_file.exists():
        raise ConfigError(
            f"Config file not found: {config_file}\n"
            "Create it with [tools], [paths] (and optional [filebot]) sections. Example:\n"
            "  [tools]\n"
            "  mkvtoolnix_dir = 'D:\\Tools\\mkvtoolnix'\n"
            "  [paths]\n"
            "  movies_root = 'D:\\Media\\Movies'\n"
            "  tv_root     = 'D:\\Media\\TV'\n"
            "  work_root   = 'D:\\Media\\ToFix'\n"
            "  output_root = 'D:\\Media\\Fixed'"
        )
    try:
        with config_file.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {config_file}: {e}")

    tools = data.get("tools", {}) or {}
    filebot = data.get("filebot", {}) or {}
    paths = data.get("paths", {}) or {}
    coverart = data.get("coverart", {}) or {}
    subtitles = data.get("subtitles", {}) or {}

    sub_langs_raw = subtitles.get("languages") or ["en"]
    if not isinstance(sub_langs_raw, list):
        raise ConfigError(f"[subtitles] languages must be a list of ISO codes, got: {sub_langs_raw!r}")
    sub_langs = tuple(str(x).strip().lower() for x in sub_langs_raw if str(x).strip()) or ("en",)

    def required(section: Dict[str, Any], section_name: str, key: str) -> str:
        v = section.get(key)
        if not v:
            raise ConfigError(f"Missing required key '{key}' in [{section_name}] of {config_file}")
        return str(v)

    mkvtoolnix_dir = Path(required(tools, "tools", "mkvtoolnix_dir"))

    def tool_exe(key: str, default_name: str) -> Path:
        v = tools.get(key)
        return Path(str(v)) if v else mkvtoolnix_dir / default_name

    # FileBot is optional: point at a guaranteed-nonexistent path when not configured
    # so all FILEBOT_EXE.exists() checks skip FileBot gracefully.
    fb = filebot.get("exe")
    filebot_exe = Path(str(fb)) if fb else (_SCRIPT_DIR / "__filebot_not_configured__")

    return Config(
        MKVTOOLNIX_DIR=mkvtoolnix_dir,
        MKVMERGE_EXE=tool_exe("mkvmerge", "mkvmerge.exe"),
        MKVPROPEDIT_EXE=tool_exe("mkvpropedit", "mkvpropedit.exe"),
        MKVINFO_EXE=tool_exe("mkvinfo", "mkvinfo.exe"),
        MKVEXTRACT_EXE=tool_exe("mkvextract", "mkvextract.exe"),
        FILEBOT_EXE=filebot_exe,
        MOVIES_ROOT=Path(required(paths, "paths", "movies_root")),
        TV_ROOT=Path(required(paths, "paths", "tv_root")),
        WORK_ROOT=Path(required(paths, "paths", "work_root")),
        OUTPUT_ROOT=Path(required(paths, "paths", "output_root")),
        FILEBOT_DB=str(filebot.get("db", "TheMovieDB")),
        TMDB_API_KEY=str(coverart.get("tmdb_api_key", "") or ""),
        FANARTTV_API_KEY=str(coverart.get("fanarttv_api_key", "") or ""),
        OMDB_API_KEY=str(coverart.get("omdb_api_key", "") or ""),
        OS_API_KEY=str(subtitles.get("api_key", "") or ""),
        OS_USERNAME=str(subtitles.get("username", "") or ""),
        OS_PASSWORD=str(subtitles.get("password", "") or ""),
        SUB_LANGS=sub_langs,
    )


# Populated by main() via load_config(); module-level so all helpers can read it.
CFG: Config = None  # type: ignore[assignment]
# =========================
# FileBot formats
# =========================

# Final Movie naming
# Example output:
#   Movie Name (Year) - tt1234567 - HDRip.1080p.x265 - [Telugu + Hindi + English].mkv
MOVIE_FILEBOT_FORMAT = r"""{n} ({y}){ imdbid ? " - ${imdbid}" : (tmdbid ? " - tmdb${tmdbid}" : "") } - {
  def s = source ?: media?.Source ?: 'HDRip'
  s.replaceAll(/\s+/,'')
}.{vf}.{
  def c = vc?.toString()?.toLowerCase()
  if (c?.contains('hevc') || c?.contains('h.265') || c?.contains('x265')) 'x265'
  else if (c?.contains('avc') || c?.contains('h.264') || c?.contains('x264')) 'x264'
  else vc
} - [{
  audio.collect{ it.'Language/String' ?: it.Language ?: 'English' }
       .collect{ l ->
         l = l.toString().toLowerCase()
         if (l == 'und' || l == 'unknown')                        return 'English'
         if (l == 'en' || l == 'eng' || l.contains('english'))   return 'English'
         if (l == 'hi' || l == 'hin' || l.contains('hindi'))     return 'Hindi'
         if (l == 'te' || l == 'tel' || l.contains('telugu'))    return 'Telugu'
         if (l == 'ta' || l == 'tam' || l.contains('tamil'))     return 'Tamil'
         if (l == 'ml' || l == 'mal' || l.contains('malayalam')) return 'Malayalam'
         if (l == 'kn' || l == 'kan' || l.contains('kannada'))   return 'Kannada'
         return l.replaceAll(/\s*\(.+\)$/, '').capitalize()
       }
       .unique()
       .join(' + ')
}]"""

# Final TV episode naming
# Example output:
#   Show Name (Year) - S01E03 - Episode Title - 1080p.x265 - [Telugu + Hindi + English].mkv
TV_FILEBOT_FORMAT = r"""{n} ({y}) - S{s.pad(2)}E{e.pad(2)} - {t} - {vf}.{
  def c = vc?.toString()?.toLowerCase()
  if (c?.contains('hevc') || c?.contains('h.265') || c?.contains('x265')) 'x265'
  else if (c?.contains('avc') || c?.contains('h.264') || c?.contains('x264')) 'x264'
  else vc
} - [{
  audio
    .collect { it.'Language/String' ?: it.Language ?: 'und' }
    .collect { l ->
      def x = l.toString().trim().toLowerCase()
      if (x == 'ta' || x == 'tam' || x.contains('tamil'))       return 'Tamil'
      if (x == 'ml' || x == 'mal' || x.contains('malayalam'))   return 'Malayalam'
      if (x == 'kn' || x == 'kan' || x.contains('kannada'))     return 'Kannada'
      if (x == 'te' || x == 'tel' || x.contains('telugu'))      return 'Telugu'
      if (x == 'hi' || x == 'hin' || x.contains('hindi'))       return 'Hindi'
      if (x == 'en' || x == 'eng' || x.contains('english'))     return 'English'
      return l.toString().replaceAll(/\s*\(.+\)$/, '')
    }
    .unique()
    .join(' + ')
}]"""


# =========================
# Logging & results
# =========================

@dataclasses.dataclass
class Result:
    kind: str  # "movie_cleanup", "movie_merge", "tv_cleanup"
    source_items: List[Path]
    output_path: Optional[Path]
    ok: bool
    reason: str = ""
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


_LOG_LOCK = threading.Lock()


def setup_logging(verbose: bool, log_file: Optional[Path]) -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)


# =========================
# Windows path safety
# =========================

def win_long_path(p: Path) -> str:
    s = str(p)
    if os.name != "nt" or not CFG.ENABLE_WIN_LONG_PATH_PREFIX:
        return s
    # If already has prefix
    if s.startswith("\\\\?\\"):
        return s
    # For UNC paths
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s.lstrip("\\")
    # For drive paths
    if re.match(r"^[A-Za-z]:\\", s):
        return "\\\\?\\" + s
    return s


def sanitize_filename(name: str) -> str:
    # Replace invalid Windows characters and normalize whitespace.
    name = re.sub(r'[<>:"/\\|?*]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Remove trailing dots/spaces (Windows restriction)
    name = name.rstrip(" .")
    return name


# =========================
# Subprocess wrapper
# =========================

@dataclasses.dataclass
class CmdResult:
    ok: bool
    rc: int
    out: str
    err: str
    cmd: List[str]


def run_cmd(cmd: List[str], timeout_sec: int = 600) -> CmdResult:
    logging.debug("CMD: %s", " ".join(cmd))
    try:
        # Force UTF-8 decoding to avoid Windows cp1252 UnicodeDecodeError on tool output.
        # mkvmerge JSON is UTF-8; other tools are safe with replacement for unexpected bytes.
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return CmdResult(ok=(p.returncode == 0), rc=p.returncode, out=p.stdout or "", err=p.stderr or "", cmd=cmd)
    except subprocess.TimeoutExpired as e:
        return CmdResult(ok=False, rc=124, out=(e.stdout or ""), err=f"TimeoutExpired: {e}", cmd=cmd)
    except Exception as e:
        return CmdResult(ok=False, rc=1, out="", err=f"Exception: {e}", cmd=cmd)


def validate_tools(need_propedit: bool = False) -> None:
    required = [CFG.MKVMERGE_EXE]
    if need_propedit:
        required.append(CFG.MKVPROPEDIT_EXE)
    missing = [exe for exe in required if not exe.exists()]
    if missing:
        raise FileNotFoundError(f"Missing MKVToolNix binary(ies): {', '.join(str(p) for p in missing)}")
    logging.info("MKVToolNix mkvmerge: %s", CFG.MKVMERGE_EXE)
    if need_propedit:
        logging.info("MKVToolNix mkvpropedit: %s", CFG.MKVPROPEDIT_EXE)
    if CFG.FILEBOT_EXE.exists():
        logging.info("FileBot: %s (db=%s)", CFG.FILEBOT_EXE, CFG.FILEBOT_DB)
    else:
        logging.info("FileBot: not found (optional) at %s", CFG.FILEBOT_EXE)



# =========================
# FileBot integration (optional)
# =========================

_FILEBOT_TITLE_RX = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)(?:\s*-\s*(?P<imdb>tt\d+)\b)?", re.IGNORECASE)

def parse_title_year_imdb_from_filename(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse 'Name (Year) - tt1234567' from a filename (best-effort)."""
    m = _FILEBOT_TITLE_RX.search(path.stem)
    if not m:
        return None, None, None
    title = m.group("title").strip()
    year = m.group("year").strip()
    imdb = (m.group("imdb").strip() if m.group("imdb") else None)
    return title, year, imdb

def run_filebot_rename_mkvs(mkvs: List[Path], dry_run: bool) -> List[Path]:
    """
    Run FileBot to normalize movie filename(s) to: {n} ({y})
    Returns updated paths in the same order (matched by file size; hash only if needed).
    """
    if dry_run or not mkvs:
        return mkvs
    if not CFG.FILEBOT_EXE.exists():
        return mkvs

    # FileBot works best when invoked with explicit file list.
    parent_dirs = {p.parent for p in mkvs}
    if len(parent_dirs) != 1:
        # Process one folder at a time; but our movie-group working copies are normally co-located
        logging.debug("FileBot rename skipped (multiple parent dirs): %s", parent_dirs)
        return mkvs
    out_dir = next(iter(parent_dirs))

    before = [(p, p.stat().st_size) for p in mkvs]

    # Plain str() paths: the FileBot launcher cannot locate its bundled JRE when
    # invoked via a \\?\-prefixed path ("bundled JRE missing or corrupted" error).
    cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename",
        *[str(p) for p in mkvs],
        "--db", CFG.FILEBOT_DB,
        "--format", "{n} ({y}) - {imdbid}",
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]
    r = run_cmd(cmd, timeout_sec=900)
    if not r.ok:
        logging.warning("FileBot rename failed (continuing without FileBot). rc=%s stderr=%s", r.rc, r.err.strip())
        return mkvs

    # Map renamed files back to originals by size (unique in nearly all cases for variant files).
    candidates = list(out_dir.glob("*.mkv"))
    by_size: Dict[int, List[Path]] = {}
    for c in candidates:
        try:
            by_size.setdefault(c.stat().st_size, []).append(c)
        except Exception:
            continue

    resolved: List[Path] = []
    for old_path, old_size in before:
        options = by_size.get(old_size, [])
        if len(options) == 1:
            resolved.append(options[0])
            continue
        if not options:
            # If FileBot didn't touch it (or it moved unexpectedly), fall back
            resolved.append(old_path)
            continue
        # Ambiguous: hash-match (rare)
        try:
            old_hash = sha256_file(old_path)
            match = None
            for opt in options:
                if sha256_file(opt) == old_hash:
                    match = opt
                    break
            resolved.append(match or old_path)
        except Exception:
            resolved.append(old_path)

    return resolved

# Cache to ensure we run FileBot only once per episode output path during a single run
_FILEBOT_TV_RENAMED_CACHE: set[str] = set()

# Global disable switch if FileBot is not runnable (e.g., bundled JRE missing)
_FILEBOT_DISABLED: bool = False


def run_filebot_rename_tv_mkv(mkv: Path, dry_run: bool) -> Path:
    """
    Post-step FileBot rename for a SINGLE TV episode MKV (best-effort).

    Goal: normalize ONLY the *base* TV episode name via FileBot:
        Show (Year) - SxxEyy - Episode Title

    The script will then append the technical suffix derived from MKVToolNix:
        - Res.Codec - [Audio Languages]

    Hardening:
      - runs at most once per episode path (in-process cache)
      - safe fallback if FileBot is missing or fails (returns original path)
      - if FileBot reports missing/corrupt bundled JRE, disable further FileBot attempts for this run
    """
    if dry_run or not mkv or not mkv.exists():
        return mkv

    if not CFG.FILEBOT_EXE.exists():
        return mkv

    global _FILEBOT_DISABLED
    if _FILEBOT_DISABLED:
        return mkv

    # Ensure we only try once per path per run
    try:
        key = str(mkv.resolve()).lower()
    except Exception:
        key = str(mkv).lower()
    if key in _FILEBOT_TV_RENAMED_CACHE:
        return mkv
    _FILEBOT_TV_RENAMED_CACHE.add(key)

    TV_BASE_FORMAT = TV_FILEBOT_FORMAT

    out_dir = mkv.parent
    try:
        before_size = mkv.stat().st_size
    except Exception:
        before_size = None

    # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths.
    cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename", str(mkv),
        "--db", "TheTVDB",
        "--format", TV_BASE_FORMAT,
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        logging.warning("FileBot TV rename failed to execute: %s", e)
        return mkv

    if proc.returncode != 0:
        out_txt = (proc.stdout or "").strip()
        err_txt = (proc.stderr or "").strip()
        logging.warning("FileBot TV rename failed (rc=%s). STDOUT=%s STDERR=%s",
                        proc.returncode, out_txt, err_txt)

        # Disable further attempts if FileBot itself cannot run due to bundled JRE missing
        if "bundled java runtime environment" in out_txt.lower() and ("missing" in out_txt.lower() or "corrupted" in out_txt.lower()):
            _FILEBOT_DISABLED = True
        return mkv

    # FileBot moved/renamed the file. Find the resulting MKV (best-effort).
    try:
        candidates = sorted(out_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if before_size is not None:
            candidates = [p for p in candidates if p.exists() and p.stat().st_size == before_size]
        if candidates:
            new_path = candidates[0]
            try:
                _FILEBOT_TV_RENAMED_CACHE.add(str(new_path.resolve()).lower())
            except Exception:
                _FILEBOT_TV_RENAMED_CACHE.add(str(new_path).lower())
            return new_path
    except Exception:
        pass

    return mkv



def run_filebot_rename_final_mkv(
    mkv: Path,
    *,
    db: str,
    filebot_format: str,
    dry_run: bool,
    query: Optional[str] = None,
) -> Path:
    """
    Run FileBot rename for a SINGLE MKV, writing result into the same directory.
    Best-effort: returns original path on failure.

    query: clean movie/show title passed as --query to FileBot so it doesn't try to
           parse the (potentially noisy release) filename for the DB lookup.
    """
    if dry_run or not mkv or not mkv.exists():
        return mkv
    if not CFG.FILEBOT_EXE.exists():
        return mkv

    global _FILEBOT_DISABLED
    if _FILEBOT_DISABLED:
        return mkv

    out_dir = mkv.parent

    try:
        before_size = mkv.stat().st_size
    except Exception:
        before_size = None

    # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths.
    cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename", str(mkv),
        "--db", db,
        "--format", filebot_format,
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]
    if query:
        # Override FileBot's filename-based search with a clean title so release
        # noise in the original filename doesn't corrupt the DB lookup result.
        cmd += ["--q", query]
        logging.debug("FileBot query override: %s", query)

    r = run_cmd(cmd, timeout_sec=1200)
    out_txt = (r.out or "").strip()
    err_txt = (r.err or "").strip()

    if not r.ok:
        logging.warning("FileBot rename failed (db=%s, rc=%s).", db, r.rc)
        if out_txt:
            logging.warning("FileBot STDOUT: %s", out_txt)
        if err_txt:
            logging.warning("FileBot STDERR: %s", err_txt)

        # Disable further attempts if FileBot itself cannot run due to bundled JRE missing
        if "bundled java runtime environment" in out_txt.lower() and ("missing" in out_txt.lower() or "corrupted" in out_txt.lower()):
            _FILEBOT_DISABLED = True
        return mkv

    # Log what FileBot actually did so the user can see it
    if out_txt:
        logging.info("FileBot (db=%s): %s", db, out_txt)

    # Find resulting MKV (best-effort: same size, most recent)
    try:
        candidates = sorted(out_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if before_size is not None:
            candidates = [p for p in candidates if p.exists() and p.stat().st_size == before_size]
        if candidates:
            return candidates[0]
    except Exception:
        pass

    return mkv

def mkvmerge_identify_json(mkv_path: Path) -> Dict[str, Any]:
    cmd = [win_long_path(CFG.MKVMERGE_EXE), "-J", win_long_path(mkv_path)]
    r = run_cmd(cmd, timeout_sec=300)
    if not r.ok:
        raise RuntimeError(f"mkvmerge -J failed rc={r.rc}: {r.err.strip()}")
    try:
        return json.loads(r.out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse mkvmerge JSON for {mkv_path}: {e}")


# =========================
# Working copy system
# =========================

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ensure_working_copy(src: Path, work_dst: Path, dry_run: bool) -> Path:
    """
    Copies src into work_dst if needed. Reuses existing if unchanged (size+mtime),
    optionally hash-verified on mtime mismatch.
    """
    work_dst.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logging.info("[DRY] Would ensure working copy: %s -> %s", src, work_dst)
        return work_dst

    if work_dst.exists():
        s_stat = src.stat()
        w_stat = work_dst.stat()
        if s_stat.st_size == w_stat.st_size and int(s_stat.st_mtime) == int(w_stat.st_mtime):
            logging.debug("Working copy reused (size+mtime match): %s", work_dst)
            return work_dst

        if s_stat.st_size == w_stat.st_size and CFG.HASH_ON_MTIME_MISMATCH:
            try:
                s_hash = sha256_file(src)
                w_hash = sha256_file(work_dst)
                if s_hash == w_hash:
                    # Align timestamps to avoid repeated hashing
                    os.utime(work_dst, (s_stat.st_atime, s_stat.st_mtime))
                    logging.debug("Working copy reused (hash match): %s", work_dst)
                    return work_dst
            except Exception as e:
                logging.warning("Hash verify failed; recopying. (%s)", e)

        logging.info("Working copy differs; recopying: %s", work_dst)

    tmp = work_dst.with_suffix(work_dst.suffix + ".copytmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass

    shutil.copy2(win_long_path(src), win_long_path(tmp))
    os.replace(win_long_path(tmp), win_long_path(work_dst))
    return work_dst


# =========================
# Scanning & grouping
# =========================

def scan_mkvs(root: Path) -> List[Path]:
    if not root.exists():
        logging.warning("Root not found (skipping): %s", root)
        return []
    out: List[Path] = []
    for p in root.rglob("*.mkv"):
        if p.is_file():
            out.append(p)
    return out


_MOVIE_NOISE_TOKENS = re.compile(
    r"(?i)\b(2160p|1440p|1080p|720p|480p|x265|x264|hevc|h265|h264|avc|hdr10\+?|dv|dolby\.?vision|remux|bluray|brrip|webrip|web[- ]dl|hdr|aac|ac3|eac3|dts|truehd|atmos)\b"
)

_YEAR_RE = re.compile(r"\((19\d{2}|20\d{2})\)|\b(19\d{2}|20\d{2})\b")
_SEASON_EP_RE = re.compile(r"(?i)\bS(\d{1,2})E(\d{1,2})\b")


def normalize_for_similarity(name: str) -> str:
    """
    Normalize movie filenames for similarity grouping.

    Goals:
    - Group multi-audio variants together (e.g., [Telugu] vs [Hindi + Malayalam + Kannada]).
    - Ignore bracketed language/metadata, IMDb ids, and common release tokens.
    """
    base = Path(name).stem
    base = base.replace(".", " ").replace("_", " ")

    # Drop bracket groups: [ ... ] (languages, tags, groups)
    base = re.sub(r"\[[^\]]*\]", " ", base)

    # Drop IMDb ids like tt1234567
    base = re.sub(r"(?i)\btt\d{6,9}\b", " ", base)

    # Remove common noise tokens & year tokens
    base = _MOVIE_NOISE_TOKENS.sub(" ", base)
    base = _YEAR_RE.sub(" ", base)

    # Remove language words (helps grouping when brackets weren't present)
    base = re.sub(r"(?i)\b(telugu|telegu|tamil|hindi|english|malayalam|kannada|multi)\b", " ", base)

    base = re.sub(r"\s+", " ", base).strip().lower()
    return base



def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def group_movies_in_folder(folder_mkvs: List[Path], threshold: float) -> List[List[Path]]:
    """
    SIMILARITY_RULE (implemented):
    - Only group within the same directory.
    - Normalize filenames by removing year + common quality/codec tokens.
    - Use SequenceMatcher ratio; group if >= threshold.
    - Log grouping with normalized names and ratio.
    """
    if not folder_mkvs:
        return []

    items = sorted(folder_mkvs, key=lambda p: p.name.lower())
    norms = {p: normalize_for_similarity(p.name) for p in items}

    groups: List[List[Path]] = []
    used: set[Path] = set()

    for p in items:
        if p in used:
            continue
        group = [p]
        used.add(p)
        for q in items:
            if q in used:
                continue
            s = similarity(norms[p], norms[q])
            if s >= threshold and norms[p] and norms[q]:
                logging.info("Movie grouping: '%s' ~ '%s' | norm='%s' vs '%s' | ratio=%.3f",
                             p.name, q.name, norms[p], norms[q], s)
                group.append(q)
                used.add(q)
        groups.append(group)

    return groups


# =========================
# Track extraction & scoring
# =========================

@dataclasses.dataclass
class Track:
    file: Path
    id: int
    type: str  # "video"|"audio"|"subtitles"
    codec_id: str
    codec: str
    language: str
    name: str
    default: bool
    forced: bool
    width: Optional[int] = None
    height: Optional[int] = None
    channels: Optional[int] = None
    bitrate: Optional[int] = None  # may be missing
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)


def _get_prop(props: Dict[str, Any], key: str, default=None):
    return props.get(key, default)


def extract_tracks(mkv_path: Path, meta: Dict[str, Any]) -> List[Track]:
    tracks: List[Track] = []
    for t in meta.get("tracks", []):
        props = t.get("properties", {}) or {}

        # mkvmerge JSON fields vary by version. Prefer explicit pixel_width/height,
        # but fall back to parsing pixel_dimensions like "1280x720" when needed.
        w = _get_prop(props, "pixel_width", None)
        h = _get_prop(props, "pixel_height", None)
        if (not w or not h):
            dim = _get_prop(props, "pixel_dimensions", None) or _get_prop(props, "display_dimensions", None)
            if isinstance(dim, str) and "x" in dim:
                try:
                    a, b = dim.lower().split("x", 1)
                    w = int(a.strip())
                    h = int(re.sub(r"[^0-9]", "", b))
                except Exception:
                    pass

        tr = Track(
            file=mkv_path,
            id=int(t.get("id")),
            type=str(t.get("type", "")),
            codec_id=str(t.get("codec_id", "")),
            codec=str(t.get("codec", "")),
            language=str(_get_prop(props, "language", "und") or "und").lower(),
            name=str(_get_prop(props, "track_name", "") or ""),
            default=bool(_get_prop(props, "default_track", False)),
            forced=bool(_get_prop(props, "forced_track", False)),
            width=w,
            height=h,
            channels=_get_prop(props, "audio_channels", None),
            bitrate=_get_prop(props, "bit_rate", None),
            extra={"properties": props},
        )
        tracks.append(tr)
    return tracks


def detect_language_canonical(track: Track) -> Optional[str]:
    """
    Returns canonical language label: 'Tel'|'Hin'|'Eng' or None.
    Uses ISO + fuzzy token checks in track name.
    """
    lang = (track.language or "und").lower()
    name = (track.name or "").lower()

    # ISO first
    for canon, codes in CFG.LANG_ISO_CODES.items():
        if lang in codes:
            return canon

    # Some files use und but have track_name
    for canon, toks in CFG.LANG_NAME_TOKENS.items():
        for tok in toks:
            if tok and tok in name:
                return canon

    return None


def is_excluded_audio(track: Track) -> bool:
    n = (track.name or "").lower()
    for tok in CFG.AUDIO_EXCLUDE_TOKENS:
        if tok in n:
            return True
    return False


def apply_track_lang_overrides(
    tracks: List[Track],
    audio_overrides: Dict[int, str],
    sub_overrides: Dict[int, str],
) -> None:
    """
    Patch Track objects in-place so downstream detection uses the forced language.
    Also sets track.language to the ISO code so mkvmerge --language picks it up.
    """
    _display = {"Hin": "Hindi", "Eng": "English", "Tel": "Telugu"}
    for t in tracks:
        overrides = audio_overrides if t.type == "audio" else (sub_overrides if t.type == "subtitles" else {})
        if t.id in overrides:
            canon = overrides[t.id]
            iso = _CANON_TO_ISO.get(canon, canon.lower())
            logging.info("Force-lang override: track %d (%s) %r -> %s (%s)", t.id, t.type, t.language, canon, iso)
            t.language = iso
            if not t.name or t.name.strip().lower() in ("", "und", "2 channels", "stereo", "5.1"):
                t.name = _display.get(canon, canon)


def fix_track_langs_inplace(
    mkv_path: Path,
    tracks: List[Track],
    audio_overrides: Dict[int, str],
    sub_overrides: Dict[int, str],
) -> None:
    """
    Use mkvpropedit to write forced language tags directly into a file
    (used in the skip-remux path where we don't remux but still need correct tags).
    """
    if not CFG.MKVPROPEDIT_EXE.exists():
        logging.warning("mkvpropedit not found — cannot fix language tags in-place.")
        return
    _display = {"Hin": "Hindi", "Eng": "English", "Tel": "Telugu"}
    cmd = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
    audio_idx = 0
    sub_idx = 0
    any_change = False
    for t in sorted(tracks, key=lambda x: x.id):
        if t.type == "audio":
            audio_idx += 1
            if t.id in audio_overrides:
                canon = audio_overrides[t.id]
                iso = _CANON_TO_ISO.get(canon, canon.lower())
                name = _display.get(canon, canon)
                cmd += ["--edit", f"track:a{audio_idx}", "--set", f"language={iso}", "--set", f"name={name}"]
                any_change = True
        elif t.type == "subtitles":
            sub_idx += 1
            if t.id in sub_overrides:
                canon = sub_overrides[t.id]
                iso = _CANON_TO_ISO.get(canon, canon.lower())
                name = _display.get(canon, canon)
                cmd += ["--edit", f"track:s{sub_idx}", "--set", f"language={iso}", "--set", f"name={name}"]
                any_change = True
    if any_change:
        r = run_cmd(cmd, timeout_sec=120)
        if r.ok:
            logging.info("fix_track_langs_inplace OK: %s", mkv_path.name)
        else:
            logging.warning("fix_track_langs_inplace failed (non-fatal): %s", r.err)


def is_sdh_subtitle(track: Track) -> bool:
    """Return True if the subtitle track is SDH / hearing-impaired."""
    n = (track.name or "").lower()
    if any(tok in n for tok in ("sdh", "hearing impaired", "hearing-impaired", "hi subtitles", "for the deaf")):
        return True
    props = track.extra.get("properties", {}) or {}
    return bool(props.get("hearing_impaired_flag", False))


def codec_family_video(track: Track) -> str:
    # mkvmerge JSON may provide codec hints in either codec_id or codec.
    # Some versions may return null -> "None" after str(). Include filename fallback.
    cid = (track.codec_id or "")
    cc  = (track.codec or "")
    c = f"{cid} {cc}".lower()

    # Normalize common patterns
    if any(x in c for x in ("hevc", "hvc1", "hev1", "h.265", "h265", "x265")):
        return "hevc"
    if any(x in c for x in ("avc", "h.264", "h264", "x264")):
        return "avc"

    # Fallback: infer from filename when metadata is missing
    fn = (track.file.name or "").lower()
    if any(x in fn for x in ("hevc", "h265", "h.265", "x265")):
        return "hevc"
    if any(x in fn for x in ("avc", "h264", "h.264", "x264")):
        return "avc"

    # Last resort
    c2 = (cid or cc or "").lower()
    return c2 or "unknown"


def codec_tag_video(track: Track) -> str:
    fam = codec_family_video(track)
    if fam == "hevc":
        return "x265"
    if fam == "avc":
        return "x264"
    if "vp9" in fam:
        return "vp9"
    if "av1" in fam:
        return "av1"
    return sanitize_filename(fam)[:12] or "video"


def normalize_audio_codec_rank(codec_id: str) -> str:
    c = (codec_id or "").lower()
    # Common MKV codec_id examples:
    # A_AAC, A_AC3, A_EAC3, A_DTS, A_TRUEHD, A_OPUS, A_VORBIS
    if "truehd" in c:
        return "a_truehd"
    if "dts-hd" in c or "dtshd" in c:
        return "dts-hd"
    if "dts" in c:
        return "dts"
    if "eac3" in c:
        return "eac3"
    if "ac3" in c:
        return "ac3"
    if "aac" in c:
        return "aac"
    if "mp3" in c:
        return "mp3"
    if "opus" in c:
        return "opus"
    if "vorbis" in c:
        return "vorbis"
    return c or "other"


def normalize_sub_codec(codec_id: str) -> str:
    return (codec_id or "").lower()


def resolution_value(track: Track) -> Optional[int]:
    # Prefer height if present
    if track.height:
        try:
            return int(track.height)
        except Exception:
            return None
    return None


def nearest_target_rank(h: int) -> Tuple[int, int]:
    """
    Returns (target_index, delta) where target_index is lower is better:
      0 -> nearest 2160
      1 -> nearest 1080
      2 -> nearest 720
    delta is abs difference.
    """
    best_idx, best_delta = 0, 10**9
    for i, t in enumerate(CFG.RES_TARGETS):
        d = abs(h - t)
        if d < best_delta:
            best_delta = d
            best_idx = i
    return (best_idx, best_delta)


def score_video(track: Track, file_size: int) -> Tuple:
    fam = codec_family_video(track)
    # codec preference
    codec_rank = 9
    if fam == "hevc":
        codec_rank = 0
    elif fam == "avc":
        codec_rank = 1
    else:
        codec_rank = 5

    w = track.width or 0
    h = resolution_value(track) or 0
    if w:
        target_idx, delta = _nearest_by_dim(w, CFG.RES_WIDTH_TARGETS)
    elif h:
        target_idx, delta = _nearest_by_dim(h, CFG.RES_TARGETS)
    else:
        target_idx, delta = 9, 10**9
    pixels = (track.width or 0) * (track.height or 0)

    # bitrate may be None; file size acts as final tie breaker
    br = track.bitrate or 0

    # Lower tuple is better for ranks; for pixels/br/size use negative for higher-is-better.
    return (codec_rank, target_idx, delta, -pixels, -br, -file_size, track.id)


def score_audio(track: Track) -> Tuple:
    # Higher channels preferred
    ch = int(track.channels or 0)
    c_rank_key = normalize_audio_codec_rank(track.codec_id)
    try:
        c_rank = CFG.AUDIO_CODEC_RANK.index(c_rank_key)
    except ValueError:
        c_rank = len(CFG.AUDIO_CODEC_RANK) + 5

    br = int(track.bitrate or 0)
    # Prefer default track as small tie-break
    default_rank = 0 if track.default else 1

    # Lower is better; use negative for higher-is-better values
    return (-ch, c_rank, -br, default_rank, track.id)


def score_sub(track: Track, include_forced: bool) -> Tuple:
    cid = normalize_sub_codec(track.codec_id)
    try:
        c_rank = CFG.SUB_CODEC_RANK.index(cid)
    except ValueError:
        c_rank = len(CFG.SUB_CODEC_RANK) + 5

    # Prefer non-forced by default; if include_forced is enabled, we allow forced but do not
    # automatically prefer it unless no non-forced exists.
    forced_rank = 1 if track.forced else 0
    default_rank = 0 if track.default else 1
    return (c_rank, forced_rank, default_rank, track.id)


# =========================
# Filename inference helpers
# =========================

def infer_movie_name_year_from_path(p: Path) -> Tuple[str, Optional[str]]:
    """
    Best-effort inference of Movie Title + Year from a filename.

    Goals:
    - Extract a 4-digit year (prefer (YYYY), else standalone token).
    - Remove typical release/quality clutter from the *title* (languages, codecs, sizes, bracketed groups).
    - Keep the human movie title clean, even when the source name is extremely noisy.

    Note: Source tags like WEB-DL/HDRip/BluRay are NOT kept in the title; they are inferred separately.
    """
    stem = p.stem

    # Normalize separators early
    s = stem.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()

    # Remove bracketed groups that commonly contain junk: [ ... ]
    # (Languages, groups, tags, etc.)
    s = re.sub(r"\[[^\]]*\]", " ", s)

    # Remove non-year parentheses groups that often contain audio/bitrate/size info.
    # Keep (YYYY) if present.
    s = re.sub(r"\((?!19\d{2}\)|20\d{2}\))[^\)]*\)", " ", s)

    # Extract year. Scene convention is 'Title.Year.Quality.Source.Lang.Tags' —
    # when there is title text BEFORE the year, everything AFTER it is release
    # junk (e.g. 'The.Film.2026.1080p.WEB-DL.Hindi.ESubs'), so truncate.
    year = None
    m = re.search(r"\((19\d{2}|20\d{2})\)", s)
    if m:
        year = m.group(1)
        before = s[:m.start()].strip()
        s = before if before else s.replace(m.group(0), " ")
    else:
        m2 = re.search(r"\b(19\d{2}|20\d{2})\b", s)
        if m2:
            year = m2.group(1)
            before = s[:m2.start()].strip()
            s = before if before else re.sub(r"\b" + re.escape(year) + r"\b", " ", s)

    # Remove common "release junk" tokens from title
    # (we intentionally do NOT remove plain words that could be part of title)
    junk = re.compile(
        r"(?i)\b("
        r"2160p|1440p|1080p|720p|480p|"
        r"x265|x264|h265|h264|hevc|avc|"
        r"hdr10\+?|hdr|dv|dolby\s*vision|"
        r"webrip|web[- ]?dl|bluray|b[dr]rip|remux|"
        r"hdtv|cam|ts|tc|dvdrip|"
        r"esubs?|msubs?|subbed|multi|dubbed|dual\s*audio|uncut|org|hq|"
        r"ddp?\+?\s*\d\.\d|dd\s*\d\.\d|"
        r"eac3|ac3|aac|dts(?:-hd)?|truehd|atmos|"
        r"(?:8|10)\s*-?\s*bit|"
        r"\d+\s*kbps|\d+\s*mbps|"
        r"\d+(?:\.\d+)?\s*(?:gb|mb)"
        r")\b"
    )
    s = junk.sub(" ", s)

    # Release-group debris left behind after codec removal (e.g. 'HEVC-GRP' -> '-GRP')
    s = re.sub(r"(?:^|\s)-[A-Za-z0-9]+\b", " ", s)

    # Collapse repeated hyphens / separators
    s = re.sub(r"[\-–—]{2,}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # Final sanitize
    title = sanitize_filename(s)
    if not title:
        # Fallback to folder name if filename was too noisy
        title = sanitize_filename(p.parent.name) or sanitize_filename(stem)

    return title, year


def extract_imdb_id_from_path(p: Path) -> Optional[str]:
    """Extract IMDb id (tt1234567) from filename, if present."""
    m = re.search(r"(?i)\btt\d{6,9}\b", p.stem)
    return m.group(0) if m else None


def extract_imdb_id_from_movie_path(p: Path) -> Optional[str]:
    """
    Extract IMDb id for a movie file.
    Checks the filename first, then walks up parent folder names —
    movie folders are often named 'Movie Title (Year) - tt1234567'.
    """
    imdb = extract_imdb_id_from_path(p)
    if imdb:
        return imdb
    for parent in p.parents:
        if len(parent.parts) <= 1:
            break
        m = re.search(r"(?i)\btt\d{6,9}\b", parent.name)
        if m:
            return m.group(0)
    return None


def extract_imdb_from_mkv_tags(mkv_path: Path) -> Optional[str]:
    """
    Read the IMDB tag already embedded in the MKV file's Matroska tags.
    Used as a fallback when the filename/folder doesn't carry an IMDB ID —
    FileBot writes the IMDB ID into the tags even when the filename format
    doesn't include it.

    Runs mkvextract to dump the tags XML, then parses for <Name>IMDB</Name>.
    Returns the first tt-prefixed ID found, or None.
    """
    if not CFG.MKVEXTRACT_EXE.exists():
        return None
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(prefix="mkvtags_read_", suffix=".xml")
    tmp_path = Path(tmp)
    try:
        os.close(fd)
        mkvextract_exe = CFG.MKVEXTRACT_EXE
        r = run_cmd([str(mkvextract_exe), str(mkv_path), "tags", str(tmp_path)], timeout_sec=60)
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            return None
        xml_text = tmp_path.read_text(encoding="utf-8", errors="replace")
        # Find <Name>IMDB</Name> ... <String>ttNNN</String>
        m = re.search(r"<Name>IMDB</Name>\s*<String>(tt\d{6,9})</String>", xml_text, re.IGNORECASE)
        return m.group(1) if m else None
    except Exception:
        return None
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def extract_imdb_id_from_tv_path(p: Path) -> Optional[str]:
    """
    Extract IMDb id for a TV file.
    Checks the filename first, then walks up parent folder names —
    TV show folders commonly carry the IMDb id (e.g. 'Show Name (2008) - tt1234567').
    """
    imdb = extract_imdb_id_from_path(p)
    if imdb:
        return imdb
    for parent in p.parents:
        if len(parent.parts) <= 1:
            break
        m = re.search(r"(?i)\btt\d{6,9}\b", parent.name)
        if m:
            return m.group(0)
    return None


def _nearest_by_dim(value: int, targets: Tuple[int, ...]) -> Tuple[int, int]:
    """Return (index, delta) of the closest target to value, picking by smallest delta."""
    best_idx, best_delta = 0, 10**9
    for i, t in enumerate(targets):
        d = abs(value - t)
        if d < best_delta:
            best_delta = d
            best_idx = i
    return (best_idx, best_delta)


def infer_resolution_tag_from_video(track: Track, fallback_filename: Optional[str] = None, **_ignored) -> str:
    """
    Infer resolution tag like '1080p'.

    Priority:
    1) Width (primary) — matched against RES_WIDTH_TARGETS (3840/1920/1280).
    2) Height (fallback) — matched against RES_TARGETS (2160/1080/720).
    3) Filename pattern — looks for '1080p', '2160p', etc.
    4) 'UnknownRes' if nothing matches.
    """
    # 1) Width — most reliable for anamorphic / non-standard encodes
    w = track.width
    if w:
        try:
            idx, _d = _nearest_by_dim(int(w), CFG.RES_WIDTH_TARGETS)
            return f"{CFG.RES_TARGETS[idx]}p"
        except Exception:
            pass

    # 2) Height fallback
    h = resolution_value(track)
    if h:
        try:
            idx, _d = _nearest_by_dim(int(h), CFG.RES_TARGETS)
            return f"{CFG.RES_TARGETS[idx]}p"
        except Exception:
            return f"{int(h)}p"

    # 3) Filename fallback
    if fallback_filename:
        m = re.search(r"(?i)\b(2160|1440|1080|720|480)p\b", fallback_filename)
        if m:
            return f"{m.group(1)}p"

    return "UnknownRes"


_SOURCE_TAGS = [
    ("WEB-DL", re.compile(r"(?i)\bweb[ ._-]?dl\b")),
    ("WEBRip", re.compile(r"(?i)\bweb[ ._-]?rip\b")),
    ("BluRay", re.compile(r"(?i)\bblu[ ._-]?ray\b|\bbd\b")),
    ("BRRip", re.compile(r"(?i)\bbrrip\b|\bb[dr]rip\b")),
    ("HDRip", re.compile(r"(?i)\bhdrip\b")),
    ("HDTV", re.compile(r"(?i)\bhdtv\b")),
    ("DVDRip", re.compile(r"(?i)\bdvdrip\b")),
    ("REMUX", re.compile(r"(?i)\bremux\b")),
]

def infer_source_tag_from_filename(filename: str) -> Optional[str]:
    """
    Infer a source tag (e.g., WEB-DL, WEBRip, BluRay, HDRip) from the filename stem.
    Returns None if not detected.
    """
    s = filename.replace(".", " ").replace("_", " ")
    for tag, rx in _SOURCE_TAGS:
        if rx.search(s):
            return tag
    return None


def infer_codec_tag_from_filename(filename: str) -> Optional[str]:
    s = filename.lower()
    if re.search(r"\b(x265|h265|hevc)\b", s):
        return "x265"
    if re.search(r"\b(x264|h264|avc)\b", s):
        return "x264"
    if re.search(r"\b(av1)\b", s):
        return "av1"
    if re.search(r"\b(vp9)\b", s):
        return "vp9"
    return None

_CANON_TO_ISO: Dict[str, str] = {"Hin": "hin", "Eng": "eng", "Tel": "tel"}


def parse_force_lang_overrides(pairs: Optional[List[List[str]]]) -> Dict[int, str]:
    """
    Parse repeated --force-audio-lang / --force-sub-lang TRACK_ID LANG pairs
    into {track_id: canonical} dict.  LANG accepts same values as --audio-langs.
    """
    if not pairs:
        return {}
    result: Dict[int, str] = {}
    for tid_str, lang_str in pairs:
        try:
            tid = int(tid_str)
        except ValueError:
            raise ValueError(f"Track ID must be an integer, got: {tid_str!r}")
        resolved = parse_audio_lang_filter([lang_str])
        if not resolved:
            raise ValueError(f"Could not resolve language: {lang_str!r}")
        result[tid] = resolved[0]
    return result


def parse_audio_lang_filter(raw: List[str]) -> Optional[List[str]]:
    """
    Parse user-supplied language names/codes into canonical keys.
    Accepts full names (Telugu, Hindi, English) or ISO codes (tel, hin, eng).
    Returns ordered list of canonical keys, or None if input is empty/None.
    Raises ValueError for unrecognised tokens.
    """
    if not raw:
        return None

    # Build a lookup: lower token -> canonical key
    lookup: Dict[str, str] = {}
    for canon, codes in CFG.LANG_ISO_CODES.items():
        for c in codes:
            lookup[c.lower()] = canon
    for canon, tokens in CFG.LANG_NAME_TOKENS.items():
        for tok in tokens:
            if tok:
                lookup[tok.lower()] = canon
    # Also accept canonical keys themselves (Tel, Hin, Eng)
    for canon in CFG.LANG_CANONICAL_ORDER:
        lookup[canon.lower()] = canon

    resolved: List[str] = []
    for token in raw:
        key = token.strip().lower()
        canon = lookup.get(key)
        if canon is None:
            valid = sorted({k for k in lookup.values()})
            raise ValueError(
                f"Unrecognised language '{token}'. "
                f"Accepted values: {', '.join(v for v in [*CFG.LANG_DISPLAY_MAP.values(), *[c.lower() for c in CFG.LANG_CANONICAL_ORDER], 'tel','hin','eng'])}"
            )
        if canon not in resolved:
            resolved.append(canon)

    # Return in canonical order
    return [c for c in CFG.LANG_CANONICAL_ORDER if c in resolved]


def build_audio_bracket(selected_langs: List[str]) -> str:
    """
    Build bracket string using FULL language names in fixed order.
    Example: [Telugu + Hindi + English]
    """
    if not selected_langs:
        return "NoAudioMatch"
    ordered = [x for x in CFG.LANG_CANONICAL_ORDER if x in selected_langs]
    ordered_display = [CFG.LANG_DISPLAY_MAP.get(x, x) for x in ordered]
    return " + ".join(ordered_display)


# =========================
# mkvmerge command builder
# =========================

def mkvmerge_build_and_run(
    output_tmp: Path,
    parts: List[Tuple[Path, Dict[str, Any]]],
    dry_run: bool,
    segment_title: Optional[str] = None,
    timeout_sec: int = 3600,
) -> CmdResult:
    """
    parts: list of (input_file, options_dict) where options_dict contains:
      - video_tracks: List[int] | None
      - audio_tracks: List[int] | None
      - sub_tracks: List[int] | None
      - track_names: Dict[int,str] track_id->name
      - languages: Dict[int,str] track_id->iso (optional)
      - no_attachments: bool
      - no_chapters: bool
    Each part's options apply to that file and are placed immediately before it.
    """
    cmd: List[str] = [win_long_path(CFG.MKVMERGE_EXE), "-o", win_long_path(output_tmp)]

    # Global safety: no chapters / tags unless desired
    cmd += ["--no-chapters", "--no-global-tags"]

    if segment_title:
        cmd += ["--title", segment_title]

    for in_file, opt in parts:
        # Attachments can carry fonts; default keep them unless explicitly disabled.
        if opt.get("no_attachments", False):
            cmd += ["--no-attachments"]

        v = opt.get("video_tracks", None)
        a = opt.get("audio_tracks", None)
        s = opt.get("sub_tracks", None)

        if v is None:
            cmd += ["--no-video"]
        else:
            cmd += ["--video-tracks", ",".join(str(x) for x in v)]

        if a is None:
            cmd += ["--no-audio"]
        else:
            cmd += ["--audio-tracks", ",".join(str(x) for x in a)]

        if s is None:
            cmd += ["--no-subtitles"]
        else:
            cmd += ["--subtitle-tracks", ",".join(str(x) for x in s)]

        # track names
        tnames: Dict[int, str] = opt.get("track_names", {}) or {}
        for tid, tname in tnames.items():
            cmd += ["--track-name", f"{tid}:{tname}"]

        # languages (optional)
        tlang: Dict[int, str] = opt.get("languages", {}) or {}
        for tid, iso in tlang.items():
            cmd += ["--language", f"{tid}:{iso}"]

        cmd += [win_long_path(in_file)]

    if dry_run:
        logging.info("[DRY] mkvmerge command: %s", " ".join(cmd))
        return CmdResult(ok=True, rc=0, out="", err="", cmd=cmd)

    return run_cmd(cmd, timeout_sec=timeout_sec)


def file_has_all_target_langs(
    src: Path,
    audios_found: Dict[str, Any],
    audio_lang_filter: Optional[List[str]],
) -> bool:
    """
    Return True if a SINGLE source file already contains every target audio language
    so that remuxing is unnecessary.

    target_langs = audio_lang_filter if specified, else all three canonical languages
    that are present in the file (we only require the ones the user asked for, not all
    three unconditionally — if user asked for Telugu+Hindi only, English being absent is fine).

    Additionally the file must be a single-file group (caller is responsible for checking
    len(group) == 1 for movies).
    """
    target = set(audio_lang_filter) if audio_lang_filter else set(CFG.LANG_CANONICAL_ORDER)
    found  = set(audios_found.keys())
    return target.issubset(found)


def cleanup_working_copies(work_files: List[Path], dry_run: bool) -> None:
    """
    Delete working copy files from WORK_ROOT and prune any empty parent
    directories up to (but not including) WORK_ROOT itself.
    Only called on successful processing.
    """
    for wf in work_files:
        if not wf.exists():
            continue
        # Safety: only delete files that live under WORK_ROOT
        try:
            wf.relative_to(CFG.WORK_ROOT)
        except ValueError:
            logging.warning("Working copy outside WORK_ROOT, skipping delete: %s", wf)
            continue
        if dry_run:
            logging.info("[DRY] Would delete working copy: %s", wf)
            continue
        try:
            wf.unlink()
            logging.debug("Deleted working copy: %s", wf)
        except Exception as e:
            logging.warning("Could not delete working copy %s: %s", wf, e)

    if dry_run:
        return

    # Prune empty parent directories up to (not including) WORK_ROOT
    dirs_to_check: set[Path] = set()
    for wf in work_files:
        try:
            wf.relative_to(CFG.WORK_ROOT)
        except ValueError:
            continue
        dirs_to_check.add(wf.parent)

    for d in sorted(dirs_to_check, key=lambda p: len(p.parts), reverse=True):
        while d != CFG.WORK_ROOT and d.is_dir():
            try:
                d.rmdir()  # only succeeds if empty
                logging.debug("Removed empty work dir: %s", d)
            except OSError:
                break  # not empty or permission issue — stop climbing
            d = d.parent


def atomic_move(src_tmp: Path, dst_final: Path, overwrite: bool) -> None:
    dst_final.parent.mkdir(parents=True, exist_ok=True)
    if dst_final.exists():
        if not overwrite:
            raise FileExistsError(f"Output exists and overwrite disabled: {dst_final}")
        # Try remove first to reduce cross-volume rename issues
        dst_final.unlink()
    os.replace(win_long_path(src_tmp), win_long_path(dst_final))


# =========================
# Tag cleaning (--cleantags mode)
# =========================

def _build_tags_xml(imdb_id: Optional[str] = None) -> str:
    """
    Build a Matroska tags XML string.
    If imdb_id is provided, includes an IMDB tag at movie level (TargetTypeValue 50).
    Otherwise returns an empty tags document (clears all existing tags).
    """
    if imdb_id:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n'
            "<Tags>\n"
            "  <Tag>\n"
            "    <Targets>\n"
            "      <TargetTypeValue>50</TargetTypeValue>\n"
            "    </Targets>\n"
            "    <Simple>\n"
            "      <Name>IMDB</Name>\n"
            f"      <String>{imdb_id}</String>\n"
            "    </Simple>\n"
            "  </Tag>\n"
            "</Tags>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n'
        "<Tags>\n"
        "</Tags>\n"
    )


def _write_tags_xml(imdb_id: Optional[str] = None, xml_text: Optional[str] = None) -> Path:
    """Write a Matroska tags XML to a temp file and return its path.
    xml_text overrides the default minimal (IMDB-only) document."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".xml", prefix="mkvtags_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml_text if xml_text is not None else _build_tags_xml(imdb_id))
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return Path(tmp)


def _xml_esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _simple_tag(name: str, value: Any, indent: str = "    ", nested: str = "") -> str:
    """One Matroska <Simple> element, or empty string when value is empty."""
    if value is None or str(value).strip() == "":
        return ""
    return (f"{indent}<Simple>\n"
            f"{indent}  <Name>{_xml_esc(name)}</Name>\n"
            f"{indent}  <String>{_xml_esc(str(value).strip())}</String>\n"
            f"{nested}"
            f"{indent}</Simple>\n")


def _actor_tags(cast: List[Tuple[str, str]], indent: str = "    ") -> str:
    """ACTOR Simple tags with nested CHARACTER sub-tags."""
    out = []
    for actor, character in cast:
        if not actor:
            continue
        nested = ""
        if character:
            nested = (f"{indent}  <Simple>\n"
                      f"{indent}    <Name>CHARACTER</Name>\n"
                      f"{indent}    <String>{_xml_esc(character)}</String>\n"
                      f"{indent}  </Simple>\n")
        out.append(_simple_tag("ACTOR", actor, indent=indent, nested=nested))
    return "".join(out)


def _open_tag(ttv: int) -> str:
    return ("  <Tag>\n"
            "    <Targets>\n"
            f"      <TargetTypeValue>{ttv}</TargetTypeValue>\n"
            "    </Targets>\n")


def _build_rich_tags_xml(meta: Dict[str, Any], is_tv: bool, imdb_id: Optional[str]) -> str:
    """
    Build a full Matroska tags document from fetched metadata.

    Movies : TargetTypeValue 50 (TITLE, DATE_RELEASED, GENRE, DIRECTOR, WRITTEN_BY,
             DESCRIPTION, SYNOPSIS, LAW_RATING, RATING, IMDB, TMDB, ACTOR+CHARACTER)
             + TargetTypeValue 70 collection tag when the movie belongs to one.
    TV     : TargetTypeValue 70 show (TITLE, GENRE, NETWORK, LAW_RATING, ACTORs, ids)
             + 60 season (TITLE, PART_NUMBER)
             + 50 episode (TITLE, PART_NUMBER, DATE_RELEASED, DIRECTOR, DESCRIPTION,
               SYNOPSIS, RATING).
    """
    parts: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n<Tags>\n']

    if not is_tv:
        parts.append(_open_tag(50))
        parts.append(_simple_tag("TITLE", meta.get("title")))
        parts.append(_simple_tag("DATE_RELEASED", meta.get("date") or meta.get("year")))
        parts.append(_simple_tag("GENRE", ", ".join(meta.get("genres") or [])))
        for d in meta.get("directors") or []:
            parts.append(_simple_tag("DIRECTOR", d))
        for w in meta.get("writers") or []:
            parts.append(_simple_tag("WRITTEN_BY", w))
        parts.append(_actor_tags(meta.get("cast") or []))
        parts.append(_simple_tag("DESCRIPTION", meta.get("description")))
        parts.append(_simple_tag("SYNOPSIS", meta.get("synopsis")))
        parts.append(_simple_tag("LAW_RATING", meta.get("law_rating")))
        parts.append(_simple_tag("RATING", meta.get("rating")))
        parts.append(_simple_tag("IMDB", imdb_id))
        parts.append(_simple_tag("TMDB", meta.get("tmdb_id")))
        parts.append("  </Tag>\n")
        if meta.get("collection"):
            parts.append(_open_tag(70))
            parts.append(_simple_tag("TITLE", meta.get("collection")))
            parts.append("  </Tag>\n")
    else:
        # Show level
        parts.append(_open_tag(70))
        parts.append(_simple_tag("TITLE", meta.get("show")))
        parts.append(_simple_tag("DATE_RELEASED", meta.get("show_year")))
        parts.append(_simple_tag("GENRE", ", ".join(meta.get("genres") or [])))
        parts.append(_simple_tag("NETWORK", meta.get("network")))
        parts.append(_simple_tag("LAW_RATING", meta.get("law_rating")))
        parts.append(_actor_tags(meta.get("cast") or []))
        parts.append(_simple_tag("IMDB", imdb_id))
        parts.append(_simple_tag("TMDB", meta.get("tmdb_id")))
        parts.append("  </Tag>\n")
        # Season level
        if meta.get("season") is not None:
            parts.append(_open_tag(60))
            parts.append(_simple_tag("TITLE", meta.get("season_name")))
            parts.append(_simple_tag("PART_NUMBER", meta.get("season")))
            parts.append("  </Tag>\n")
        # Episode level
        if meta.get("episode") is not None:
            parts.append(_open_tag(50))
            parts.append(_simple_tag("TITLE", meta.get("ep_title")))
            parts.append(_simple_tag("PART_NUMBER", meta.get("episode")))
            parts.append(_simple_tag("DATE_RELEASED", meta.get("airdate")))
            for d in meta.get("directors") or []:
                parts.append(_simple_tag("DIRECTOR", d))
            parts.append(_simple_tag("DESCRIPTION", meta.get("description")))
            parts.append(_simple_tag("SYNOPSIS", meta.get("synopsis")))
            parts.append(_simple_tag("RATING", meta.get("rating")))
            parts.append("  </Tag>\n")

    parts.append("</Tags>\n")
    return "".join(parts)


def clean_mkv_tags(mkv_path: Path, dry_run: bool, is_tv: bool = False) -> Result:
    """
    Clean promotional/watermark tags from an MKV in-place using mkvpropedit.

    Changes made:
      Segment info  : title → movie 'Title (Year)'  or  TV 'Show (Year) - S01E01 - Episode Title'
      Global tags   : all cleared; IMDB tag written back if ID found in filename/folder
      Attachments   : all deleted (watermark images, fonts from release releases)
      Video track   : name → same as segment title
      Audio tracks  : name → '<N> channels'  (e.g. '6 channels')
      Subtitle tracks: name → '' (cleared)

    is_tv=True  uses TV naming conventions (infer_tv_components).
    is_tv=False uses movie naming conventions (default).
    """
    kind = "tag_clean"
    try:
        # --- Identify tracks and attachments ---
        meta = mkvmerge_identify_json(mkv_path)
        tracks = extract_tracks(mkv_path, meta)
        attachments: List[Dict[str, Any]] = meta.get("attachments", []) or []

        # --- Build segment title and extract IMDb ID ---
        if is_tv:
            show_name, season_str, ep_str, ep_title = infer_tv_components(mkv_path)
            # infer_tv_components may leave trailing " - -" artifacts when noise tokens
            # (codec/resolution) were removed from the episode title before space normalization.
            if ep_title:
                ep_title = re.sub(r"[\s.\-–—]+$", "", ep_title).strip() or None
            parts_title: List[str] = [show_name]
            if season_str and ep_str:
                parts_title.append(f"{season_str}{ep_str}")
            if ep_title:
                parts_title.append(ep_title)
            segment_title = " - ".join(parts_title)
            imdb_id = extract_imdb_id_from_tv_path(mkv_path)
            if not imdb_id:
                imdb_id = extract_imdb_from_mkv_tags(mkv_path)
                if imdb_id:
                    logging.debug("IMDB tag read from existing MKV tags (TV): %s -> %s", mkv_path.name, imdb_id)
        else:
            title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv_path)
            if not imdb_id:
                # Walk filename + parent folder names — folder may carry the IMDB ID even
                # when the filename alone does not (e.g. 'Movie (2026) - tt1234567\file.mkv')
                imdb_id = extract_imdb_id_from_movie_path(mkv_path)
            if not imdb_id:
                # Last resort: read the IMDB tag already embedded in the file's Matroska tags.
                # FileBot writes it there even when the filename format doesn't include it.
                imdb_id = extract_imdb_from_mkv_tags(mkv_path)
                if imdb_id:
                    logging.debug("IMDB tag read from existing MKV tags: %s -> %s", mkv_path.name, imdb_id)
            segment_title = f"{title} ({year})" if year else (title or mkv_path.stem)

        # --- Fetch rich metadata (TMDB primary, OMDb supplement) ---
        # Enabled whenever API keys are configured; --no-fetch-tags disables it.
        # Failures fall back to the basic (IMDB-only) tags — never fatal, and
        # dry runs stay offline.
        rich_xml_text: Optional[str] = None
        if not dry_run and _FETCH_TAGS_ENABLED and CFG.TMDB_API_KEY:
            try:
                if is_tv:
                    s_num = int(season_str[1:]) if season_str else None
                    e_num = int(ep_str[1:]) if ep_str else None
                    rich = _get_meta_fetcher().episode_metadata(show_name, imdb_id, s_num, e_num)
                else:
                    rich = _get_meta_fetcher().movie_metadata(title, year, imdb_id)
                if rich:
                    rich_xml_text = _build_rich_tags_xml(rich, is_tv=is_tv, imdb_id=imdb_id)
                    logging.info("Tags enriched: %s | genre=%s | director=%s | actors=%d",
                                 mkv_path.name,
                                 ", ".join((rich.get("genres") or [])[:3]) or "-",
                                 ", ".join(rich.get("directors") or []) or "-",
                                 len(rich.get("cast") or []))
                else:
                    logging.debug("No rich metadata found for: %s", mkv_path.name)
            except Exception as e:
                logging.warning("Metadata fetch failed (non-fatal, basic tags used): %s | %s",
                                mkv_path.name, e)

        if imdb_id:
            logging.info("Cleaning tags [%s]: %s -> title='%s'  imdb=%s",
                         "tv" if is_tv else "movie", mkv_path.name, segment_title, imdb_id)
        else:
            logging.info("Cleaning tags [%s]: %s -> title='%s'  (no IMDb ID found)",
                         "tv" if is_tv else "movie", mkv_path.name, segment_title)

        # --- Build mkvpropedit command ---
        # Use plain str() for paths — mkvpropedit doesn't accept the \\?\ prefix.
        cmd: List[str] = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]

        # 1. Replace ALL global tags with a clean XML.
        #    Clears release tags (AUTHOR, SUMMARY, WEBSITE, Copyright, Comment, etc.)
        #    and writes back the IMDb tag if the ID was found in the filename.
        tags_xml: Optional[Path] = None
        if not dry_run:
            tags_xml = _write_tags_xml(imdb_id, xml_text=rich_xml_text)
            cmd += ["--tags", f"all:{tags_xml}"]
        else:
            placeholder = f"tags_imdb={imdb_id}" if imdb_id else "tags_empty"
            cmd += ["--tags", f"all:<{placeholder}.xml>"]

        # 2. Set segment title only. Description/Copyright/Comment are tags,
        #    not segment-info properties — they are already wiped by step 1.
        #    Only 'title' and 'date' are valid --edit info properties.
        cmd += [
            "--edit", "info",
            "--set", f"title={segment_title}",
        ]

        # 3. Delete all attachments (watermark PNGs, custom fonts, etc.).
        #    Selector is plain numeric ID from mkvmerge -J (0-based per mkvpropedit docs).
        #    Embedded cover art (cover.jpg etc., per Matroska convention) is legitimate
        #    metadata written by the --coverart mode — never delete it.
        for att in attachments:
            att_id = att.get("id")
            att_name = str(att.get("file_name", "")).lower()
            if att_name in _COVER_ATTACHMENT_NAMES:
                continue
            if att_id is not None:
                cmd += ["--delete-attachment", str(att_id)]

        # 4. Set per-track names.
        video_idx = audio_idx = sub_idx = 0
        for t in tracks:
            if t.type == "video":
                video_idx += 1
                cmd += ["--edit", f"track:v{video_idx}",
                        "--set", f"name={segment_title}"]

            elif t.type == "audio":
                audio_idx += 1
                ch = int(t.channels or 0)
                ch_label = f"{ch} channels" if ch else "audio"
                cmd += ["--edit", f"track:a{audio_idx}",
                        "--set", f"name={ch_label}"]

            elif t.type == "subtitles":
                sub_idx += 1
                cmd += ["--edit", f"track:s{sub_idx}",
                        "--set", "name="]

        if dry_run:
            logging.info("[DRY] mkvpropedit command: %s", " ".join(cmd))
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="dry-run")

        try:
            r = run_cmd(cmd, timeout_sec=300)
        finally:
            # Always clean up the temp XML regardless of outcome
            if tags_xml and tags_xml.exists():
                try:
                    tags_xml.unlink()
                except Exception:
                    pass

        if not r.ok:
            # mkvpropedit writes errors to stdout, not stderr.
            detail = (r.out or r.err or "").strip()
            # rc=1 means warnings only — operation still applied; treat as non-fatal.
            if r.rc > 1:
                return Result(kind=kind, source_items=[mkv_path], output_path=None,
                              ok=False, reason=f"mkvpropedit rc={r.rc}: {detail}")
            logging.warning("mkvpropedit warning (rc=1, continuing): %s", detail)

        logging.info("Tags cleaned OK: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path, ok=True)

    except Exception as e:
        logging.exception("Tag clean failed: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason=str(e))


def _insert_imdb_into_filename(p: Path, imdb_id: str) -> Path:
    """
    Rename a file in-place to add the IMDB ID after 'Title (Year)' in the filename.

    Input:  The Sequel (2022) - BRRip.1080p.x265 - [Hindi + English].mkv
    Output: The Sequel (2022) - tt1234567 - BRRip.1080p.x265 - [Hindi + English].mkv

    If the IMDB ID is already present, the file is left untouched.
    Returns the new Path (or the original if nothing changed / rename failed).
    """
    stem = p.stem
    # Already has it — nothing to do
    if re.search(r"\btt\d{6,9}\b", stem, re.IGNORECASE):
        return p

    # Insert after 'Title (Year)' — find the first ' - ' separator
    m = re.match(r"^(.+?\(\d{4}\))(.*)", stem)
    if not m:
        # No year found — append before the first ' - '
        idx = stem.find(" - ")
        if idx == -1:
            new_stem = f"{stem} - {imdb_id}"
        else:
            new_stem = f"{stem[:idx]} - {imdb_id}{stem[idx:]}"
    else:
        title_year = m.group(1)        # "The Sequel (2022)"
        rest       = m.group(2)        # " - BRRip.1080p.x265 - [Hindi + English]"
        # Drop an existing leading ' - ' from rest so we can re-join cleanly
        rest_clean = re.sub(r"^\s*-\s*", "", rest)
        new_stem   = f"{title_year} - {imdb_id} - {rest_clean}" if rest_clean else f"{title_year} - {imdb_id}"

    new_stem = re.sub(r"\s+-\s+-\s+", " - ", new_stem)   # collapse double separators
    new_name = sanitize_filename(new_stem) + p.suffix
    new_path = p.parent / new_name
    if new_path == p:
        return p
    try:
        p.rename(new_path)
        logging.info("Inserted IMDB into filename: %s -> %s", p.name, new_path.name)
        return new_path
    except Exception as exc:
        logging.warning("Failed to rename for IMDB insert (%s): %s", p.name, exc)
        return p


def _cleantags_one(
    mkv_path: Path,
    is_tv: bool,
    dry_run: bool,
    skip_filebot: bool = False,
) -> Result:
    """
    Full cleantags sequence for a single file:
      1. clean_mkv_tags        — strip release tags, write clean segment title + IMDB tag
      2. FileBot rename        — identify via DB using clean title as --query, rename in-place
         Fallback (no FileBot) — insert IMDB ID directly into the filename via Python rename
      3. clean_mkv_tags        — update segment title to match the final filename
    """
    kind = "tag_clean"

    # Step 1: clean tags — also resolves the clean title / IMDB we'll need below
    ct = clean_mkv_tags(mkv_path, dry_run=dry_run, is_tv=is_tv)
    if not ct.ok:
        return ct

    current = mkv_path  # will be updated if the file gets renamed

    if not skip_filebot and not dry_run:
        # Extract clean title and IMDB so we can use them whether FileBot runs or not
        if is_tv:
            show_name, _s, _e, _t = infer_tv_components(mkv_path)
            query    = show_name
            db       = "TheTVDB"
            fmt      = TV_FILEBOT_FORMAT
            imdb_id  = extract_imdb_id_from_tv_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
        else:
            title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv_path)
            if not imdb_id:
                imdb_id = extract_imdb_id_from_movie_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
            query = f"{title} ({year})" if year else (title or mkv_path.stem)
            db    = CFG.FILEBOT_DB
            fmt   = MOVIE_FILEBOT_FORMAT

        filebot_ok = False
        if CFG.FILEBOT_EXE.exists() and not _FILEBOT_DISABLED:
            logging.info("cleantags FileBot rename: %s  (query=%s)", mkv_path.name, query)
            fb = run_filebot_rename_final_mkv(mkv_path, db=db, filebot_format=fmt,
                                              dry_run=False, query=query)
            if fb and fb.exists() and fb != mkv_path:
                logging.info("cleantags FileBot renamed -> %s", fb.name)
                current    = fb
                filebot_ok = True

        if not filebot_ok and not is_tv and imdb_id:
            # FileBot unavailable or failed — insert the IMDB ID into the filename directly
            logging.info("FileBot unavailable; inserting IMDB ID into filename: %s", mkv_path.name)
            current = _insert_imdb_into_filename(current, imdb_id)

        # Step 3: re-run cleantags so segment title matches the final filename
        if current.exists():
            ct2 = clean_mkv_tags(current, dry_run=False, is_tv=is_tv)
            if not ct2.ok:
                logging.warning("cleantags (post-rename) failed (non-fatal): %s", ct2.reason)

    return Result(kind=kind, source_items=[mkv_path], output_path=current, ok=True)


def run_cleantags_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
    skip_filebot: bool = False,
) -> List[Result]:
    """Scan Movies/TV roots, clean tags, and rename via FileBot on every MKV found."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root     = tv_root     or CFG.TV_ROOT
    targets: List[Path] = []
    if do_movies:
        found = scan_mkvs(movies_root)
        logging.info("cleantags - Movies: %d MKV(s) found in %s.", len(found), movies_root)
        targets.extend(found)
    if do_tv:
        found = scan_mkvs(tv_root)
        logging.info("cleantags - TV: %d MKV(s) found in %s.", len(found), tv_root)
        targets.extend(found)

    # Build (path, is_tv) pairs
    tagged_targets: List[Tuple[Path, bool]] = []
    for p in targets:
        try:
            p.relative_to(tv_root or CFG.TV_ROOT)
            is_tv = True
        except ValueError:
            is_tv = False
        tagged_targets.append((p, is_tv))

    results: List[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_cleantags_one, p, is_tv, dry_run, skip_filebot): p
            for p, is_tv in tagged_targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("cleantags worker crashed: %s", p)
                results.append(Result(kind="tag_clean", source_items=[p],
                                      output_path=None, ok=False,
                                      reason=f"Worker exception: {e}"))
    return results


# =========================
# Cover art (--coverart mode)
# =========================

# Matroska cover-art attachment names (spec convention; "cover.jpg" is the front cover).
# Used both to detect existing covers and to protect them from cleantags deletion.
_COVER_ATTACHMENT_NAMES = (
    "cover.jpg", "cover.png", "cover.webp",
    "cover_land.jpg", "cover_land.png",
    "small_cover.jpg", "small_cover.png",
)

# Local poster files checked next to the MKV (first match wins).
_LOCAL_POSTER_NAMES = ("poster", "cover", "folder")
_LOCAL_POSTER_EXTS = (".jpg", ".jpeg", ".png")

# ISO 639-1 codes used by TMDB / fanart.tv image language fields.
_CANON_TO_ISO1: Dict[str, str] = {"Hin": "hi", "Tel": "te", "Eng": "en"}

# TMDB pre-sized poster (780x1170 for 2:3 posters) — no local image resize needed.
_TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w780"

_HTTP_USER_AGENT = "MediaCleanup/1.0"


def mkv_cover_attachment_ids(meta: Dict[str, Any]) -> List[int]:
    """Return attachment IDs whose file_name marks them as embedded cover art."""
    ids: List[int] = []
    for att in meta.get("attachments", []) or []:
        name = str(att.get("file_name", "")).lower()
        if name in _COVER_ATTACHMENT_NAMES:
            aid = att.get("id")
            if aid is not None:
                ids.append(int(aid))
    return ids


def find_local_poster(mkv_path: Path, is_tv: bool) -> Optional[Path]:
    """
    Look for a manual poster file next to the MKV: poster/cover/folder + .jpg/.jpeg/.png.
    Movies: same folder only (a poster in a shared folder applies to every MKV in it).
    TV: episode's folder, then one level up (Season xx -> show folder).
    """
    dirs = [mkv_path.parent]
    if is_tv and mkv_path.parent.parent != mkv_path.parent:
        dirs.append(mkv_path.parent.parent)
    for d in dirs:
        for base in _LOCAL_POSTER_NAMES:
            for ext in _LOCAL_POSTER_EXTS:
                p = d / f"{base}{ext}"
                if p.is_file():
                    return p
    return None


def _http_get_json(url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logging.debug("HTTP GET failed: %s | %s", url, e)
        return None


def _http_get_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return data if data else None
    except Exception as e:
        logging.debug("HTTP download failed: %s | %s", url, e)
        return None


def poster_lang_preference(audio_canon_langs: List[str]) -> List[str]:
    """
    Poster language priority: English always first, then the file's own audio
    languages (Hindi/Telugu as detected), then textless posters ('null' at TMDB).
    """
    pref = ["en"]
    for canon in audio_canon_langs:
        iso1 = _CANON_TO_ISO1.get(canon)
        if iso1 and iso1 not in pref:
            pref.append(iso1)
    pref.append("null")
    return pref


def _maybe_downscale_poster(data: bytes, max_width: int = 1000) -> bytes:
    """
    Downscale oversized posters (e.g. full-res local files) to ~1000px wide JPEG.
    Pillow is an OPTIONAL dependency: if it isn't installed, the image is embedded
    as-is. TMDB w780 images never need this.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return data
    try:
        import io
        img = Image.open(io.BytesIO(data))
        if img.width <= max_width:
            return data
        new_h = max(1, int(img.height * max_width / img.width))
        img = img.convert("RGB").resize((max_width, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        out = buf.getvalue()
        logging.debug("Poster downscaled: %d KB -> %d KB", len(data) // 1024, len(out) // 1024)
        return out
    except Exception as e:
        logging.debug("Poster downscale skipped: %s", e)
        return data


class CoverArtFetcher:
    """
    Fetches poster images via the source chain: TMDB -> fanart.tv -> OMDb.
    (Local poster files are handled by the caller before this runs.)

    Thread-safe; results are cached per movie/show for the run, so every episode
    of a series reuses one downloaded show poster (and repeated failures are not
    retried). Sources with an empty API key are skipped.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # cache: key -> (image_bytes | None, source_label)
        self._cache: Dict[str, Tuple[Optional[bytes], str]] = {}

    # ---------- TMDB ----------

    def _tmdb_find_by_imdb(self, imdb_id: str) -> Tuple[Optional[int], Optional[int]]:
        """Resolve an IMDB id to TMDB ids. Returns (movie_id, tv_id)."""
        url = (f"https://api.themoviedb.org/3/find/{urllib.parse.quote(imdb_id)}"
               f"?api_key={CFG.TMDB_API_KEY}&external_source=imdb_id")
        data = _http_get_json(url)
        if not data:
            return None, None
        movies = data.get("movie_results") or []
        shows = data.get("tv_results") or []
        return (movies[0].get("id") if movies else None,
                shows[0].get("id") if shows else None)

    def _tmdb_search(self, title: str, year: Optional[str], is_tv: bool) -> Optional[int]:
        kind = "tv" if is_tv else "movie"
        url = (f"https://api.themoviedb.org/3/search/{kind}"
               f"?api_key={CFG.TMDB_API_KEY}&query={urllib.parse.quote(title)}")
        if year and not is_tv:
            url += f"&year={year}"
        data = _http_get_json(url)
        results = (data or {}).get("results") or []
        return results[0].get("id") if results else None

    def _tmdb_pick_poster_url(self, tmdb_id: int, is_tv: bool, lang_pref: List[str]) -> Optional[str]:
        """Pick the best poster by language preference, then TMDB vote score."""
        kind = "tv" if is_tv else "movie"
        url = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/images?api_key={CFG.TMDB_API_KEY}"
        data = _http_get_json(url)
        posters = (data or {}).get("posters") or []
        if not posters:
            return None

        def rank(p: Dict[str, Any]) -> Tuple[int, float]:
            lang = p.get("iso_639_1") or "null"
            try:
                li = lang_pref.index(lang)
            except ValueError:
                li = len(lang_pref) + 1  # language not in preference list: last resort
            return (li, -float(p.get("vote_average") or 0.0))

        best = min(posters, key=rank)
        fp = best.get("file_path")
        if fp:
            logging.debug("TMDB poster picked: lang=%s votes=%s %s",
                          best.get("iso_639_1"), best.get("vote_average"), fp)
            return f"{_TMDB_IMG_BASE}{fp}"
        return None

    def _tmdb_tv_tvdb_id(self, tmdb_tv_id: int) -> Optional[int]:
        """fanart.tv keys TV shows by TheTVDB id; TMDB can translate."""
        url = f"https://api.themoviedb.org/3/tv/{tmdb_tv_id}/external_ids?api_key={CFG.TMDB_API_KEY}"
        data = _http_get_json(url)
        return (data or {}).get("tvdb_id") or None

    # ---------- fanart.tv ----------

    @staticmethod
    def _fanart_rank(items: List[Dict[str, Any]], lang_pref: List[str]) -> Optional[str]:
        if not items:
            return None

        def rank(p: Dict[str, Any]) -> Tuple[int, int]:
            lang = (p.get("lang") or "00").lower()
            if lang == "00":  # fanart.tv's code for textless
                lang = "null"
            try:
                li = lang_pref.index(lang)
            except ValueError:
                li = len(lang_pref) + 1
            try:
                likes = int(p.get("likes") or 0)
            except (TypeError, ValueError):
                likes = 0
            return (li, -likes)

        return min(items, key=rank).get("url")

    def _fanarttv_movie_poster_url(self, movie_id: str, lang_pref: List[str]) -> Optional[str]:
        """movie_id: IMDB id (ttNNN) or TMDB id — fanart.tv accepts both."""
        url = (f"https://webservice.fanart.tv/v3/movies/{urllib.parse.quote(movie_id)}"
               f"?api_key={CFG.FANARTTV_API_KEY}")
        data = _http_get_json(url)
        return self._fanart_rank((data or {}).get("movieposter") or [], lang_pref)

    def _fanarttv_show_poster_url(self, tvdb_id: int, lang_pref: List[str]) -> Optional[str]:
        url = f"https://webservice.fanart.tv/v3/tv/{tvdb_id}?api_key={CFG.FANARTTV_API_KEY}"
        data = _http_get_json(url)
        return self._fanart_rank((data or {}).get("tvposter") or [], lang_pref)

    # ---------- OMDb ----------

    def _omdb_poster_url(self, imdb_id: str) -> Optional[str]:
        url = f"https://www.omdbapi.com/?i={urllib.parse.quote(imdb_id)}&apikey={CFG.OMDB_API_KEY}"
        data = _http_get_json(url)
        poster = (data or {}).get("Poster")
        return poster if poster and poster != "N/A" else None

    # ---------- public API ----------

    def fetch_movie_poster(
        self, title: Optional[str], year: Optional[str], imdb_id: Optional[str],
        lang_pref: List[str],
    ) -> Tuple[Optional[bytes], str]:
        cache_key = f"movie:{(imdb_id or f'{title}|{year}' or '').lower()}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        img: Optional[bytes] = None
        source = "none"
        tmdb_id: Optional[int] = None

        if CFG.TMDB_API_KEY:
            if imdb_id:
                tmdb_id, _tv = self._tmdb_find_by_imdb(imdb_id)
            if tmdb_id is None and title:
                tmdb_id = self._tmdb_search(title, year, is_tv=False)
            if tmdb_id is not None:
                purl = self._tmdb_pick_poster_url(tmdb_id, is_tv=False, lang_pref=lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "TMDB"

        if img is None and CFG.FANARTTV_API_KEY and (imdb_id or tmdb_id is not None):
            purl = self._fanarttv_movie_poster_url(imdb_id or str(tmdb_id), lang_pref)
            if purl:
                img = _http_get_bytes(purl)
                source = "fanart.tv"

        if img is None and CFG.OMDB_API_KEY and imdb_id:
            purl = self._omdb_poster_url(imdb_id)
            if purl:
                img = _http_get_bytes(purl)
                source = "OMDb"

        result = (img, source if img is not None else "none")
        with self._lock:
            self._cache[cache_key] = result
        return result

    def fetch_show_poster(
        self, show_name: str, imdb_id: Optional[str], lang_pref: List[str],
    ) -> Tuple[Optional[bytes], str]:
        """One show poster per series per run (cached), embedded into every episode."""
        cache_key = f"tv:{(imdb_id or show_name or '').lower()}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        img: Optional[bytes] = None
        source = "none"
        tmdb_tv_id: Optional[int] = None

        # Strip a trailing (Year) for the title search; TMDB matches better without it.
        search_name = re.sub(r"\s*\(\d{4}\)\s*$", "", show_name or "").strip()

        if CFG.TMDB_API_KEY:
            if imdb_id:
                _mv, tmdb_tv_id = self._tmdb_find_by_imdb(imdb_id)
            if tmdb_tv_id is None and search_name:
                tmdb_tv_id = self._tmdb_search(search_name, None, is_tv=True)
            if tmdb_tv_id is not None:
                purl = self._tmdb_pick_poster_url(tmdb_tv_id, is_tv=True, lang_pref=lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "TMDB"

        if img is None and CFG.FANARTTV_API_KEY and CFG.TMDB_API_KEY and tmdb_tv_id is not None:
            tvdb_id = self._tmdb_tv_tvdb_id(tmdb_tv_id)
            if tvdb_id:
                purl = self._fanarttv_show_poster_url(tvdb_id, lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "fanart.tv"

        if img is None and CFG.OMDB_API_KEY and imdb_id:
            purl = self._omdb_poster_url(imdb_id)
            if purl:
                img = _http_get_bytes(purl)
                source = "OMDb"

        result = (img, source if img is not None else "none")
        with self._lock:
            self._cache[cache_key] = result
        return result


# =========================
# Metadata fetching (rich MKV tags) & API key validation
# =========================

# Rich tag fetching is on by default when API keys are configured;
# --no-fetch-tags sets this to False in main().
_FETCH_TAGS_ENABLED: bool = True


def _http_get_json_status(url: str, timeout: int = 30) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """Like _http_get_json but also returns the HTTP status (for key validation)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        logging.debug("HTTP GET failed: %s | %s", url, e)
        return None, None


def validate_api_keys() -> Dict[str, str]:
    """
    Check each configured [coverart] API key with one cheap call.
    Returns {source: 'ok' | 'invalid' | 'network error' | 'not configured'}.
    Uses tt0111161 (a well-known title) as an always-existing probe title.
    """
    status: Dict[str, str] = {}

    if not CFG.TMDB_API_KEY:
        status["TMDB"] = "not configured"
    else:
        code, _ = _http_get_json_status(
            f"https://api.themoviedb.org/3/configuration?api_key={CFG.TMDB_API_KEY}")
        status["TMDB"] = "ok" if code == 200 else ("invalid" if code == 401 else "network error")

    if not CFG.FANARTTV_API_KEY:
        status["fanart.tv"] = "not configured"
    else:
        code, _ = _http_get_json_status(
            f"https://webservice.fanart.tv/v3/movies/tt0111161?api_key={CFG.FANARTTV_API_KEY}")
        status["fanart.tv"] = "ok" if code == 200 else ("invalid" if code == 401 else "network error")

    if not CFG.OMDB_API_KEY:
        status["OMDb"] = "not configured"
    else:
        code, data = _http_get_json_status(
            f"https://www.omdbapi.com/?i=tt0111161&apikey={CFG.OMDB_API_KEY}")
        if code == 200 and data and data.get("Response") == "True":
            status["OMDb"] = "ok"
        elif code == 401 or (data and "invalid api key" in str(data.get("Error", "")).lower()):
            status["OMDb"] = "invalid"
        else:
            status["OMDb"] = "network error"

    if not (CFG.OS_API_KEY and CFG.OS_USERNAME and CFG.OS_PASSWORD):
        status["OpenSubs"] = "not configured"
    else:
        try:
            payload = json.dumps({"username": CFG.OS_USERNAME, "password": CFG.OS_PASSWORD}).encode("utf-8")
            req = urllib.request.Request(
                f"{_OS_API_BASE}/login", data=payload, method="POST",
                headers={"Api-Key": CFG.OS_API_KEY, "User-Agent": _OS_USER_AGENT,
                         "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            status["OpenSubs"] = "ok" if data.get("token") else "invalid"
        except urllib.error.HTTPError as e:
            status["OpenSubs"] = "invalid" if e.code in (401, 403) else "network error"
        except Exception:
            status["OpenSubs"] = "network error"

    return status


def disable_invalid_api_keys() -> None:
    """
    Validate configured keys once at run start; blank out definitively-invalid
    ones (HTTP 401) in CFG so every worker doesn't fail per-file. Network errors
    are transient — sources are left enabled.
    """
    global CFG
    status = validate_api_keys()
    replace: Dict[str, str] = {}
    key_field = {"TMDB": "TMDB_API_KEY", "fanart.tv": "FANARTTV_API_KEY",
                 "OMDb": "OMDB_API_KEY", "OpenSubs": "OS_API_KEY"}
    for source, st in status.items():
        if st == "invalid":
            logging.warning("API key/credentials for %s are INVALID — source disabled for this run. "
                            "Fix them in %s (verify with --validate-keys).",
                            source, CONFIG_FILE.name)
            field = key_field.get(source)
            if field:
                replace[field] = ""
        elif st == "network error":
            logging.warning("API key check for %s hit a network error — leaving the source enabled.", source)
    if replace:
        CFG = dataclasses.replace(CFG, **replace)


class MetadataFetcher:
    """
    Fetches movie/TV metadata for rich MKV tagging (cleantags enrichment).

    TMDB is the primary source (details + credits + certifications in one call);
    OMDb supplements the US certification (LAW_RATING) and IMDB rating (RATING)
    when TMDB lacks them. Thread-safe; every lookup is cached for the run, so a
    full season costs one show call + one season call regardless of episode count.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {}

    def _cached(self, key: str, fetch) -> Any:
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        val = fetch()
        with self._lock:
            self._cache[key] = val
        return val

    # ---------- shared TMDB lookups ----------

    def _tmdb_ids_for_imdb(self, imdb_id: str) -> Tuple[Optional[int], Optional[int]]:
        url = (f"https://api.themoviedb.org/3/find/{urllib.parse.quote(imdb_id)}"
               f"?api_key={CFG.TMDB_API_KEY}&external_source=imdb_id")
        data = _http_get_json(url)
        if not data:
            return None, None
        movies = data.get("movie_results") or []
        shows = data.get("tv_results") or []
        return (movies[0].get("id") if movies else None,
                shows[0].get("id") if shows else None)

    def _tmdb_search_id(self, title: str, year: Optional[str], is_tv: bool) -> Optional[int]:
        kind = "tv" if is_tv else "movie"
        url = (f"https://api.themoviedb.org/3/search/{kind}"
               f"?api_key={CFG.TMDB_API_KEY}&query={urllib.parse.quote(title)}")
        if year and not is_tv:
            url += f"&year={year}"
        data = _http_get_json(url)
        results = (data or {}).get("results") or []
        return results[0].get("id") if results else None

    @staticmethod
    def _top_cast(credits: Dict[str, Any], limit: int = 10) -> List[Tuple[str, str]]:
        cast = (credits or {}).get("cast") or []
        return [(str(c.get("name") or ""), str(c.get("character") or "")) for c in cast[:limit]]

    # ---------- movies ----------

    def movie_metadata(self, title: Optional[str], year: Optional[str],
                       imdb_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not CFG.TMDB_API_KEY:
            return None
        cache_key = f"movie:{(imdb_id or f'{title}|{year}' or '').lower()}"

        def fetch() -> Optional[Dict[str, Any]]:
            tmdb_id: Optional[int] = None
            if imdb_id:
                tmdb_id, _tv = self._tmdb_ids_for_imdb(imdb_id)
            if tmdb_id is None and title:
                tmdb_id = self._tmdb_search_id(title, year, is_tv=False)
            if tmdb_id is None:
                return None

            data = _http_get_json(
                f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                f"?api_key={CFG.TMDB_API_KEY}&append_to_response=credits,release_dates")
            if not data:
                return None

            crew = (data.get("credits") or {}).get("crew") or []
            directors = [c.get("name") for c in crew if c.get("job") == "Director" and c.get("name")]
            writers: List[str] = []
            for c in crew:
                if c.get("department") == "Writing" and c.get("name") and c["name"] not in writers:
                    writers.append(c["name"])
            overview = str(data.get("overview") or "").strip()
            tagline = str(data.get("tagline") or "").strip()

            # US certification from TMDB release_dates
            law_rating: Optional[str] = None
            for entry in (data.get("release_dates") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "US":
                    for rel in entry.get("release_dates") or []:
                        cert = str(rel.get("certification") or "").strip()
                        if cert:
                            law_rating = cert
                            break
                    break

            rating: Optional[str] = None
            if CFG.OMDB_API_KEY and imdb_id:
                od = _http_get_json(
                    f"https://www.omdbapi.com/?i={urllib.parse.quote(imdb_id)}&apikey={CFG.OMDB_API_KEY}")
                if od and od.get("Response") == "True":
                    if not law_rating and od.get("Rated") not in (None, "", "N/A"):
                        law_rating = str(od["Rated"])
                    if od.get("imdbRating") not in (None, "", "N/A"):
                        rating = str(od["imdbRating"])
            if rating is None and data.get("vote_average"):
                rating = f"{float(data['vote_average']):.1f}"

            return {
                "title": data.get("title") or title,
                "year": (data.get("release_date") or "")[:4] or year,
                "date": data.get("release_date") or None,
                "genres": [g.get("name") for g in data.get("genres") or [] if g.get("name")],
                "directors": directors[:5],
                "writers": writers[:5],
                "cast": self._top_cast(data.get("credits") or {}),
                "description": tagline or (overview[:250] + "…" if len(overview) > 250 else overview) or None,
                "synopsis": overview or None,
                "law_rating": law_rating,
                "rating": rating,
                "collection": ((data.get("belongs_to_collection") or {}).get("name") or None),
                "tmdb_id": tmdb_id,
            }

        return self._cached(cache_key, fetch)

    # ---------- TV ----------

    def _show_metadata(self, show_name: str, imdb_id: Optional[str]) -> Optional[Dict[str, Any]]:
        cache_key = f"show:{(imdb_id or show_name or '').lower()}"

        def fetch() -> Optional[Dict[str, Any]]:
            search_name = re.sub(r"\s*\(\d{4}\)\s*$", "", show_name or "").strip()
            tv_id: Optional[int] = None
            if imdb_id:
                _mv, tv_id = self._tmdb_ids_for_imdb(imdb_id)
            if tv_id is None and search_name:
                tv_id = self._tmdb_search_id(search_name, None, is_tv=True)
            if tv_id is None:
                return None

            data = _http_get_json(
                f"https://api.themoviedb.org/3/tv/{tv_id}"
                f"?api_key={CFG.TMDB_API_KEY}&append_to_response=credits,content_ratings")
            if not data:
                return None

            law_rating: Optional[str] = None
            for entry in (data.get("content_ratings") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "US" and str(entry.get("rating") or "").strip():
                    law_rating = str(entry["rating"]).strip()
                    break

            networks = data.get("networks") or []
            return {
                "tv_id": tv_id,
                "show": data.get("name") or show_name,
                "show_year": (data.get("first_air_date") or "")[:4] or None,
                "genres": [g.get("name") for g in data.get("genres") or [] if g.get("name")],
                "network": networks[0].get("name") if networks else None,
                "cast": self._top_cast(data.get("credits") or {}),
                "law_rating": law_rating,
                "tmdb_id": tv_id,
            }

        return self._cached(cache_key, fetch)

    def _season_json(self, tv_id: int, season: int) -> Optional[Dict[str, Any]]:
        cache_key = f"season:{tv_id}:{season}"

        def fetch() -> Optional[Dict[str, Any]]:
            return _http_get_json(
                f"https://api.themoviedb.org/3/tv/{tv_id}/season/{season}?api_key={CFG.TMDB_API_KEY}")

        return self._cached(cache_key, fetch)

    def episode_metadata(self, show_name: str, imdb_id: Optional[str],
                         season: Optional[int], episode: Optional[int]) -> Optional[Dict[str, Any]]:
        if not CFG.TMDB_API_KEY:
            return None
        show = self._show_metadata(show_name, imdb_id)
        if not show:
            return None

        meta: Dict[str, Any] = dict(show)
        meta.update({"season": season, "episode": episode,
                     "season_name": None, "ep_title": None, "airdate": None,
                     "directors": [], "description": None, "synopsis": None, "rating": None})

        if season is None:
            return meta

        sdata = self._season_json(show["tv_id"], season)
        if not sdata:
            return meta
        meta["season_name"] = sdata.get("name") or f"Season {season}"

        if episode is None:
            return meta
        ep = next((e for e in sdata.get("episodes") or []
                   if e.get("episode_number") == episode), None)
        if not ep:
            return meta

        overview = str(ep.get("overview") or "").strip()
        meta["ep_title"] = ep.get("name") or None
        meta["airdate"] = ep.get("air_date") or None
        meta["directors"] = [c.get("name") for c in ep.get("crew") or []
                             if c.get("job") == "Director" and c.get("name")][:5]
        meta["description"] = (overview[:250] + "…" if len(overview) > 250 else overview) or None
        meta["synopsis"] = overview or None
        if ep.get("vote_average"):
            meta["rating"] = f"{float(ep['vote_average']):.1f}"
        return meta


_META_FETCHER: Optional[MetadataFetcher] = None
_META_FETCHER_LOCK = threading.Lock()


def _get_meta_fetcher() -> MetadataFetcher:
    global _META_FETCHER
    with _META_FETCHER_LOCK:
        if _META_FETCHER is None:
            _META_FETCHER = MetadataFetcher()
        return _META_FETCHER


def embed_cover_into_mkv(
    mkv_path: Path,
    image_bytes: bytes,
    delete_attachment_ids: List[int],
    dry_run: bool,
) -> bool:
    """
    Embed image as the Matroska front cover via mkvpropedit.
    delete_attachment_ids: existing cover attachment IDs to replace (overwrite mode).
    """
    is_png = image_bytes[:4] == b"\x89PNG"
    att_name = "cover.png" if is_png else "cover.jpg"
    mime = "image/png" if is_png else "image/jpeg"

    if dry_run:
        logging.info("[DRY] Would embed %s (%d KB) into: %s", att_name, len(image_bytes) // 1024, mkv_path.name)
        return True

    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="mkvcover_", suffix=".png" if is_png else ".jpg")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)

        cmd: List[str] = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
        for aid in delete_attachment_ids:
            cmd += ["--delete-attachment", str(aid)]
        cmd += [
            "--attachment-name", att_name,
            "--attachment-mime-type", mime,
            "--attachment-description", "Cover art",
            "--add-attachment", str(tmp_path),
        ]
        r = run_cmd(cmd, timeout_sec=300)
        if not r.ok and r.rc > 1:  # rc=1 is warnings-only, operation still applied
            logging.warning("Cover embed failed rc=%s: %s", r.rc, (r.out or r.err).strip())
            return False
        return True
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _save_review_copy(review_dir: Path, mkv_path: Path, image_bytes: bytes) -> Optional[str]:
    """
    Save an audit copy of the embedded poster into the review folder, named after
    the MKV so a wrong poster is immediately obvious in Explorer / the HTML report.
    Returns the saved filename (relative to review_dir), or None on failure.
    """
    ext = ".png" if image_bytes[:4] == b"\x89PNG" else ".jpg"
    base = sanitize_filename(mkv_path.stem) or "cover"
    name = f"{base}{ext}"
    target = review_dir / name
    if target.exists():
        # Same stem from another folder (rare): disambiguate with a short path hash.
        suffix = hashlib.sha1(str(mkv_path).encode("utf-8", "replace")).hexdigest()[:6]
        name = f"{base}_{suffix}{ext}"
        target = review_dir / name
    try:
        target.write_bytes(image_bytes)
        return name
    except Exception as e:
        logging.warning("Could not save review copy for %s: %s", mkv_path.name, e)
        return None


def process_coverart_one(
    mkv_path: Path,
    is_tv: bool,
    fetcher: CoverArtFetcher,
    dry_run: bool,
    overwrite_cover: bool,
    review_dir: Optional[Path] = None,
) -> Result:
    """
    Full cover-art sequence for one MKV:
      1. Skip if a cover attachment already exists (unless overwrite).
      2. Detect audio languages -> poster language preference (English first).
      3. Source chain: local poster file -> TMDB -> fanart.tv -> OMDb.
      4. Embed as cover.jpg/cover.png via mkvpropedit (in-place, no remux).
      5. Save an audit copy of the poster into review_dir for verification.
    """
    kind = "coverart"
    try:
        meta = mkvmerge_identify_json(mkv_path)
        existing = mkv_cover_attachment_ids(meta)
        if existing and not overwrite_cover:
            logging.debug("Cover already present, skipping: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="already_has_cover")

        tracks = extract_tracks(mkv_path, meta)
        detected = {detect_language_canonical(t) for t in tracks if t.type == "audio"}
        audio_langs = [c for c in CFG.LANG_CANONICAL_ORDER if c in detected]
        lang_pref = poster_lang_preference(audio_langs)

        img: Optional[bytes] = None
        source = "none"

        # Tier 1: local poster file (manual override always wins)
        local = find_local_poster(mkv_path, is_tv=is_tv)
        if local:
            try:
                img = local.read_bytes()
                source = f"local:{local.name}"
            except Exception as e:
                logging.warning("Could not read local poster %s: %s", local, e)

        # Tier 2-4: online sources. Dry-run stays offline by design.
        if img is None:
            if is_tv:
                show_name, _s, _e, _t = infer_tv_components(mkv_path)
                imdb_id = extract_imdb_id_from_tv_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
                if dry_run:
                    logging.info("[DRY] Would fetch show poster: show=%r imdb=%s langs=%s | %s",
                                 show_name, imdb_id, lang_pref, mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="dry-run")
                img, source = fetcher.fetch_show_poster(show_name, imdb_id, lang_pref)
            else:
                title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
                if not title:
                    title, year = infer_movie_name_year_from_path(mkv_path)
                if not imdb_id:
                    imdb_id = extract_imdb_id_from_movie_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
                if dry_run:
                    logging.info("[DRY] Would fetch movie poster: title=%r year=%s imdb=%s langs=%s | %s",
                                 title, year, imdb_id, lang_pref, mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="dry-run")
                img, source = fetcher.fetch_movie_poster(title, year, imdb_id, lang_pref)

        if img is None:
            logging.warning("No cover art found for: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=None,
                          ok=False, reason="no_poster_found")

        img = _maybe_downscale_poster(img)

        if embed_cover_into_mkv(mkv_path, img, existing if overwrite_cover else [], dry_run):
            logging.info("%sCover embedded (%s, %d KB): %s",
                         "[DRY] " if dry_run else "", source, len(img) // 1024, mkv_path.name)
            review_name: Optional[str] = None
            if review_dir is not None and not dry_run:
                review_name = _save_review_copy(review_dir, mkv_path, img)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, details={"source": source, "langs": audio_langs,
                                            "review_image": review_name})
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason="mkvpropedit_embed_failed")

    except Exception as e:
        logging.exception("Cover art failed: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason=str(e))


def _write_coverart_report(review_dir: Path, results: List[Result]) -> Optional[Path]:
    """
    Write a self-contained HTML gallery (coverart_report.html) into the review folder:
    failures listed first, then a thumbnail grid of every embedded poster with the
    MKV name and source underneath, then the list of files skipped (already covered).
    """
    import html as _html

    embedded = [r for r in results if r.ok and r.details.get("review_image")]
    embedded_no_img = [r for r in results if r.ok and r.reason not in ("already_has_cover", "dry-run")
                       and not r.details.get("review_image")]
    skipped = [r for r in results if r.ok and r.reason == "already_has_cover"]
    failed = [r for r in results if not r.ok]

    def _name(r: Result) -> str:
        return r.source_items[0].name if r.source_items else "?"

    rows: List[str] = []
    rows.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    rows.append("<title>MediaCleanup cover art report</title><style>")
    rows.append(
        "body{font-family:Segoe UI,Arial,sans-serif;margin:20px;background:#1b1b1f;color:#ddd}"
        "h1,h2{color:#fff} a{color:#7ab7ff}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}"
        "figure{margin:0;background:#26262c;border-radius:8px;padding:10px}"
        "figure img{width:100%;height:300px;object-fit:contain;background:#000;border-radius:4px}"
        "figcaption{font-size:12px;margin-top:8px;word-break:break-word}"
        ".src{color:#8fc98f} .fail{color:#ff8484} details{margin:10px 0}"
        "li{font-size:13px;margin:2px 0}"
    )
    rows.append("</style></head><body>")
    rows.append("<h1>Cover art report</h1>")
    rows.append(f"<p>Run: {_html.escape(_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} &nbsp;|&nbsp; "
                f"embedded: <b>{len(embedded) + len(embedded_no_img)}</b> &nbsp;|&nbsp; "
                f"already had cover: <b>{len(skipped)}</b> &nbsp;|&nbsp; "
                f"failed: <b class='fail'>{len(failed)}</b></p>")

    if failed:
        rows.append("<h2 class='fail'>Failures — needs attention</h2><ul>")
        for r in failed:
            rows.append(f"<li class='fail'>{_html.escape(_name(r))} — {_html.escape(r.reason)}</li>")
        rows.append("</ul>")
        rows.append("<p>Fix: drop a <code>poster.jpg</code> into the movie's folder and re-run "
                    "<code>--coverart</code> for it.</p>")

    if embedded:
        rows.append("<h2>Embedded posters — verify visually</h2>")
        rows.append("<p>Wrong poster? Drop the correct <code>poster.jpg</code> into that movie's folder and "
                    "re-run with <code>--coverart-overwrite</code> (scoped via <code>--input</code>).</p>")
        rows.append("<div class='grid'>")
        for r in sorted(embedded, key=_name):
            img = _html.escape(str(r.details["review_image"]))
            src = _html.escape(str(r.details.get("source", "?")))
            langs = ", ".join(r.details.get("langs") or []) or "-"
            rows.append(
                f"<figure><img src='{img}' loading='lazy'>"
                f"<figcaption>{_html.escape(_name(r))}<br>"
                f"<span class='src'>source: {src} | audio: {_html.escape(langs)}</span>"
                f"</figcaption></figure>"
            )
        rows.append("</div>")

    if skipped:
        rows.append(f"<details><summary>Skipped — already had a cover ({len(skipped)})</summary><ul>")
        for r in sorted(skipped, key=_name):
            rows.append(f"<li>{_html.escape(_name(r))}</li>")
        rows.append("</ul></details>")

    rows.append("</body></html>")

    report = review_dir / "coverart_report.html"
    try:
        report.write_text("\n".join(rows), encoding="utf-8")
        return report
    except Exception as e:
        logging.warning("Could not write cover art report: %s", e)
        return None


def run_coverart_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
    overwrite_cover: bool = False,
) -> List[Result]:
    """Scan Movies/TV roots and embed cover art into every MKV missing one."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root = tv_root or CFG.TV_ROOT

    if not (CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY):
        logging.warning("coverart: no API keys in [coverart] section of %s — "
                        "only local poster files (poster.jpg/cover.jpg/folder.jpg) will be used.",
                        CONFIG_FILE.name)

    movie_set: set[Path] = set(scan_mkvs(movies_root)) if do_movies else set()
    tv_set: set[Path] = set(scan_mkvs(tv_root)) if do_tv else set()
    if do_movies:
        logging.info("coverart - Movies: %d MKV(s) found in %s.", len(movie_set), movies_root)
    if do_tv:
        logging.info("coverart - TV: %d MKV(s) found in %s.", len(tv_set), tv_root)

    # Dedupe (both pipelines may scan the same --input root). For files seen by
    # both, classify by SxxEyy episode pattern in the filename.
    tagged_targets: List[Tuple[Path, bool]] = []
    for p in sorted(movie_set | tv_set):
        if p in movie_set and p in tv_set:
            is_tv = bool(_SEASON_EP_RE.search(p.stem))
        else:
            is_tv = p in tv_set
        tagged_targets.append((p, is_tv))

    # Audit trail: every embedded poster is copied here, plus an HTML gallery
    # report, so wrong matches can be spotted at a glance. Dry runs are offline
    # (no images to show), so no review folder is created.
    review_dir: Optional[Path] = None
    if not dry_run and tagged_targets:
        review_dir = _SCRIPT_DIR / "logs" / "coverart_review" / _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            review_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.warning("Could not create review folder %s: %s", review_dir, e)
            review_dir = None

    fetcher = CoverArtFetcher()
    results: List[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(process_coverart_one, p, is_tv, fetcher, dry_run, overwrite_cover, review_dir): p
            for p, is_tv in tagged_targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("coverart worker crashed: %s", p)
                results.append(Result(kind="coverart", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))

    if review_dir is not None:
        report = _write_coverart_report(review_dir, results)
        if report:
            logging.info("Cover art review: %s", review_dir)
            logging.info("Open in a browser to verify posters: %s", report)

    return results


# =========================
# Rename mode (--rename / --rename-undo)
# =========================

RENAME_HISTORY_CSV = _SCRIPT_DIR / "logs" / "rename_history.csv"

# Library-organizing formats for --rename-into (folder structure prepended).
MOVIE_FILEBOT_FORMAT_DIR = "{n} ({y})/" + MOVIE_FILEBOT_FORMAT
TV_FILEBOT_FORMAT_DIR = "{n} ({y})/Season {s.pad(2)}/" + TV_FILEBOT_FORMAT


def _append_rename_history(batch_id: str, pairs: List[Tuple[Path, Path]]) -> None:
    """Append old->new mappings to logs/rename_history.csv (creates it if missing)."""
    if not pairs:
        return
    import csv
    RENAME_HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not RENAME_HISTORY_CSV.exists()
    try:
        with RENAME_HISTORY_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["batch", "old", "new"])
            for old, new in pairs:
                w.writerow([batch_id, str(old), str(new)])
        logging.info("Rename history: %d entries appended to %s (batch %s)",
                     len(pairs), RENAME_HISTORY_CSV, batch_id)
    except Exception as e:
        logging.warning("Could not write rename history (non-fatal): %s", e)


def run_rename_undo() -> int:
    """
    Revert the most recent --rename batch recorded in logs/rename_history.csv.
    Files that moved or changed since are skipped with a warning. The undone
    batch is removed from the history so a further undo targets the batch before.
    """
    import csv
    if not RENAME_HISTORY_CSV.exists():
        logging.error("No rename history found at %s — nothing to undo.", RENAME_HISTORY_CSV)
        return 1

    with RENAME_HISTORY_CSV.open("r", newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r]
    if len(rows) <= 1:
        logging.error("Rename history is empty — nothing to undo.")
        return 1

    header, entries = rows[0], rows[1:]
    last_batch = entries[-1][0]
    batch_rows = [r for r in entries if r[0] == last_batch]
    keep_rows = [r for r in entries if r[0] != last_batch]

    logging.info("Undoing rename batch %s (%d file(s))...", last_batch, len(batch_rows))
    reverted = skipped = 0
    for _b, old_s, new_s in reversed(batch_rows):
        old, new = Path(old_s), Path(new_s)
        if not new.exists():
            logging.warning("Skip undo (renamed file no longer exists): %s", new)
            skipped += 1
            continue
        if old.exists():
            logging.warning("Skip undo (original path is occupied): %s", old)
            skipped += 1
            continue
        try:
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(win_long_path(new), win_long_path(old))
            logging.info("Reverted: %s -> %s", new.name, old)
            reverted += 1
            # Prune empty folders --rename-into may have created
            d = new.parent
            while d != d.parent:
                try:
                    d.rmdir()
                except OSError:
                    break
                d = d.parent
        except Exception as e:
            logging.warning("Undo failed for %s: %s", new, e)
            skipped += 1

    try:
        with RENAME_HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(keep_rows)
    except Exception as e:
        logging.warning("Could not rewrite rename history (non-fatal): %s", e)

    logging.info("Undo complete: reverted=%d skipped=%d", reverted, skipped)
    return 0 if skipped == 0 else 1


def process_rename_one(
    mkv: Path,
    is_tv: bool,
    target_root: Optional[Path],
    dry_run: bool,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
) -> Result:
    """
    Rename a single MKV via FileBot into the canonical naming format.

    target_root=None  -> rename in place (same folder).
    target_root=Path  -> organize into the library structure under that root
                         (Movies: 'Title (Year)/...'; TV: 'Show (Year)/Season XX/...').

    When --force-audio-lang/--force-sub-lang are given, language tags are fixed
    via mkvpropedit BEFORE FileBot runs so the [language] bracket comes out right.
    Dry runs use FileBot's native test action, which prints the actual proposed name.
    """
    kind = "rename"
    try:
        if not CFG.FILEBOT_EXE.exists():
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot not found at {CFG.FILEBOT_EXE}")
        if _FILEBOT_DISABLED:
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="FileBot disabled for this run (bundled JRE problem)")

        # Fix mislabeled language tags first so FileBot reads correct languages.
        if force_audio_langs or force_sub_langs:
            if dry_run:
                logging.info("[DRY] Would fix language tags before rename: %s", mkv.name)
            else:
                meta = mkvmerge_identify_json(mkv)
                tracks = extract_tracks(mkv, meta)
                fix_track_langs_inplace(mkv, tracks, force_audio_langs or {}, force_sub_langs or {})

        # Clean query so release noise in the filename doesn't corrupt the DB lookup.
        if is_tv:
            show_name, _s, _e, _t = infer_tv_components(mkv)
            query = re.sub(r"\s*\(\d{4}\)\s*$", "", show_name or "").strip() or None
            db = "TheTVDB"
            fmt = TV_FILEBOT_FORMAT_DIR if target_root else TV_FILEBOT_FORMAT
        else:
            title, year, _imdb = parse_title_year_imdb_from_filename(mkv)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv)
            query = f"{title} ({year})" if title and year else (title or None)
            db = CFG.FILEBOT_DB
            fmt = MOVIE_FILEBOT_FORMAT_DIR if target_root else MOVIE_FILEBOT_FORMAT

        out_dir = target_root if target_root else mkv.parent
        action = "test" if dry_run else "move"

        try:
            before_size = mkv.stat().st_size
        except Exception:
            before_size = None

        # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths
        # ("bundled JRE missing or corrupted" error).
        cmd = [
            str(CFG.FILEBOT_EXE),
            "-rename", str(mkv),
            "--db", db,
            "--format", fmt,
            "--output", str(out_dir),
            "--action", action,
            "--conflict", "skip",
            "-non-strict",
        ]
        if query:
            cmd += ["--q", query]

        r = run_cmd(cmd, timeout_sec=600)
        out_txt = (r.out or "").strip()

        if dry_run:
            # FileBot prints '[TEST] from [old] to [new]' — surface it verbatim.
            # NOTE: --action test exits with rc=1 even on success (no files were
            # actually renamed), so success is judged from the output, not rc.
            for line in out_txt.splitlines():
                if "[TEST]" in line or "Skipped" in line or "Failed" in line:
                    logging.info("[DRY] %s", line.strip())
            if "[TEST]" in out_txt or "skipped" in out_txt.lower():
                return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True, reason="dry-run")
            tail = out_txt.splitlines()[-1].strip() if out_txt else f"rc={r.rc}"
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot found no match: {tail}")

        if "skipped" in out_txt.lower() and mkv.exists():
            logging.info("Rename skipped (already named / destination exists): %s", mkv.name)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          reason="already_named")

        if not r.ok and mkv.exists():
            tail = out_txt.splitlines()[-1].strip() if out_txt else f"rc={r.rc}"
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot no match: {tail}")

        # File was moved — locate the result (same size, newest, under out_dir).
        new_path: Optional[Path] = None
        if not mkv.exists():
            try:
                candidates = [p for p in out_dir.rglob("*.mkv")
                              if before_size is None or (p.exists() and p.stat().st_size == before_size)]
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    new_path = candidates[0]
            except Exception:
                pass

        if new_path is None:
            if mkv.exists():
                return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                              reason="unchanged")
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="renamed but result file not found")

        logging.info("Renamed: %s -> %s", mkv.name, new_path)
        return Result(kind=kind, source_items=[mkv], output_path=new_path, ok=True,
                      details={"old": str(mkv), "new": str(new_path)})

    except Exception as e:
        logging.exception("Rename failed: %s", mkv)
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False, reason=str(e))


def run_rename_pipeline(
    is_tv: bool,
    scan_root: Path,
    rename_into: bool,
    dry_run: bool,
    workers: int,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
) -> List[Result]:
    """FileBot-rename every MKV under scan_root. In-place unless rename_into."""
    targets = scan_mkvs(scan_root)
    logging.info("rename - %s: %d MKV(s) found in %s.%s",
                 "TV" if is_tv else "Movies", len(targets), scan_root,
                 " (organizing into library)" if rename_into else " (in-place)")

    target_root: Optional[Path] = None
    if rename_into:
        target_root = CFG.TV_ROOT if is_tv else CFG.MOVIES_ROOT

    results: List[Result] = []
    # FileBot holds a per-invocation lock on its cache; parallel invocations can
    # contend. Cap rename concurrency at 2 regardless of --workers.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, max(1, workers))) as ex:
        futs = {
            ex.submit(process_rename_one, p, is_tv, target_root, dry_run,
                      force_audio_langs, force_sub_langs): p
            for p in targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("rename worker crashed: %s", p)
                results.append(Result(kind="rename", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))

    if not dry_run:
        pairs = [(Path(r.details["old"]), Path(r.details["new"]))
                 for r in results if r.ok and r.details.get("old") and r.details.get("new")]
        batch_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        _append_rename_history(batch_id, pairs)
        if pairs:
            logging.info("Undo this batch anytime with: --rename-undo")

    return results


# =========================
# Subtitle downloading (--subtitles mode, OpenSubtitles.com REST API)
# =========================

_OS_API_BASE = "https://api.opensubtitles.com/api/v1"
# OpenSubtitles requires a descriptive User-Agent identifying the app.
_OS_USER_AGENT = "MediaCleanup v1.0"

# ISO 639-1 <-> 639-2 for the sidecar suffix and embedded-track comparison.
_ISO1_TO_ISO2 = {"en": "eng", "hi": "hin", "te": "tel", "ta": "tam", "ml": "mal", "kn": "kan"}


def compute_oshash(path: Path) -> Optional[str]:
    """
    Classic OpenSubtitles moviehash: filesize + 64-bit sums of the first and
    last 64 KiB. The strongest match signal — it identifies the exact release.
    """
    try:
        chunk = 65536
        size = path.stat().st_size
        if size < chunk * 2:
            return None
        h = size
        with path.open("rb") as f:
            for _ in range(chunk // 8):
                h = (h + int.from_bytes(f.read(8), "little")) & 0xFFFFFFFFFFFFFFFF
            f.seek(size - chunk)
            for _ in range(chunk // 8):
                h = (h + int.from_bytes(f.read(8), "little")) & 0xFFFFFFFFFFFFFFFF
        return f"{h:016x}"
    except Exception as e:
        logging.debug("oshash failed for %s: %s", path, e)
        return None


def subtitle_sidecar_path(mkv: Path, lang_iso1: str) -> Path:
    """
    Sidecar naming: with a single configured language (or for English), the
    sidecar is '<mkv stem>.srt' exactly. Additional languages get an ISO 639-2
    suffix so they can coexist: '<stem>.hin.srt'.
    """
    single = len(CFG.SUB_LANGS) == 1
    if single or lang_iso1 == "en":
        return mkv.with_suffix(".srt")
    iso2 = _ISO1_TO_ISO2.get(lang_iso1, lang_iso1)
    return mkv.with_suffix(f".{iso2}.srt")


def missing_subtitle_langs(mkv: Path, tracks: List[Track]) -> List[str]:
    """
    Return configured languages not already covered by an embedded subtitle
    track or an existing sidecar file.
    """
    embedded: set[str] = set()
    for t in tracks:
        if t.type == "subtitles":
            embedded.add((t.language or "und")[:2].lower())

    missing: List[str] = []
    for lang in CFG.SUB_LANGS:
        if lang in embedded:
            continue
        if subtitle_sidecar_path(mkv, lang).exists():
            continue
        missing.append(lang)
    return missing


class SubtitleFetcher:
    """
    OpenSubtitles.com REST client. Thread-safe; logs in once (JWT), searches by
    moviehash + IMDB id, downloads best match, and stops the whole run
    gracefully when the daily download quota is exhausted.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._login_failed = False
        self.quota_exhausted = False
        self.remaining: Optional[int] = None

    def _headers(self, with_auth: bool = False) -> Dict[str, str]:
        h = {"Api-Key": CFG.OS_API_KEY, "User-Agent": _OS_USER_AGENT,
             "Content-Type": "application/json", "Accept": "application/json"}
        if with_auth and self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 with_auth: bool = False) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        url = f"{_OS_API_BASE}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            req = urllib.request.Request(url, data=data, method=method,
                                         headers=self._headers(with_auth))
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            logging.debug("OpenSubtitles %s %s -> %s %s", method, path, e.code, body)
            return e.code, None
        except Exception as e:
            logging.debug("OpenSubtitles %s %s failed: %s", method, path, e)
            return None, None

    def _ensure_login(self) -> bool:
        with self._lock:
            if self._token:
                return True
            if self._login_failed:
                return False
            code, data = self._request("POST", "/login",
                                       {"username": CFG.OS_USERNAME, "password": CFG.OS_PASSWORD})
            if code == 200 and data and data.get("token"):
                self._token = data["token"]
                user = data.get("user") or {}
                allowed = user.get("allowed_downloads")
                logging.info("OpenSubtitles login OK (level=%s, allowed downloads/day=%s)",
                             user.get("level", "?"), allowed)
                return True
            self._login_failed = True
            logging.error("OpenSubtitles login failed (HTTP %s) — check [subtitles] "
                          "username/password/api_key in %s", code, CONFIG_FILE.name)
            return False

    def search_best(self, mkv: Path, imdb_id: Optional[str], lang_iso1: str) -> Optional[int]:
        """Return the best matching subtitle file_id, or None."""
        params = [f"languages={lang_iso1}"]
        oshash = compute_oshash(mkv)
        if oshash:
            params.append(f"moviehash={oshash}")
        if imdb_id:
            params.append(f"imdb_id={imdb_id.lstrip('tT')}")
        if not oshash and not imdb_id:
            # Last resort: query by cleaned filename
            title, _year = infer_movie_name_year_from_path(mkv)
            if not title:
                return None
            params.append(f"query={urllib.parse.quote(title)}")

        code, data = self._request("GET", f"/subtitles?{'&'.join(params)}")
        items = (data or {}).get("data") or []
        if not items:
            return None

        def rank(it: Dict[str, Any]) -> Tuple[int, int, int]:
            a = it.get("attributes") or {}
            return (0 if a.get("moviehash_match") else 1,
                    0 if a.get("from_trusted") else 1,
                    -int(a.get("download_count") or 0))

        for it in sorted(items, key=rank):
            files = (it.get("attributes") or {}).get("files") or []
            if files and files[0].get("file_id"):
                return int(files[0]["file_id"])
        return None

    def download(self, file_id: int) -> Optional[bytes]:
        """Download one subtitle; tracks remaining quota from the response."""
        if self.quota_exhausted or not self._ensure_login():
            return None
        code, data = self._request("POST", "/download", {"file_id": file_id}, with_auth=True)
        if code == 406 or (data and isinstance(data.get("remaining"), int) and data["remaining"] < 0):
            self.quota_exhausted = True
            logging.warning("OpenSubtitles daily download quota EXHAUSTED — remaining files skipped. "
                            "Quota resets in ~24h (UTC).")
            return None
        if not data or not data.get("link"):
            return None
        if isinstance(data.get("remaining"), int):
            self.remaining = data["remaining"]
            if self.remaining <= 0:
                self.quota_exhausted = True
        return _http_get_bytes(data["link"])


def process_subtitles_one(mkv: Path, is_tv: bool, fetcher: SubtitleFetcher, dry_run: bool) -> Result:
    """
    Download missing subtitles for one MKV as sidecar .srt files.
      1. Skip languages already covered (embedded track or existing sidecar).
      2. Search by moviehash + IMDB id (best-ranked result wins).
      3. Save as '<mkv stem>.srt' (extra languages get .<iso2>.srt suffix).
    """
    kind = "subtitles"
    try:
        meta = mkvmerge_identify_json(mkv)
        tracks = extract_tracks(mkv, meta)
        missing = missing_subtitle_langs(mkv, tracks)
        if not missing:
            logging.debug("Subtitles already covered, skipping: %s", mkv.name)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          reason="already_covered")

        if dry_run:
            logging.info("[DRY] Would search subtitles for %s: langs=%s", mkv.name, missing)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True, reason="dry-run")

        if fetcher.quota_exhausted:
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="quota_exhausted")

        imdb_id = (extract_imdb_id_from_tv_path(mkv) if is_tv
                   else extract_imdb_id_from_movie_path(mkv)) or extract_imdb_from_mkv_tags(mkv)

        got: List[str] = []
        for lang in missing:
            file_id = fetcher.search_best(mkv, imdb_id, lang)
            if file_id is None:
                logging.info("No %s subtitle found for: %s", lang, mkv.name)
                continue
            data = fetcher.download(file_id)
            if data is None:
                if fetcher.quota_exhausted:
                    break
                logging.warning("Subtitle download failed (%s): %s", lang, mkv.name)
                continue
            dst = subtitle_sidecar_path(mkv, lang)
            dst.write_bytes(data)
            got.append(lang)
            logging.info("Subtitle saved (%s%s): %s",
                         lang,
                         f", quota left: {fetcher.remaining}" if fetcher.remaining is not None else "",
                         dst.name)

        if got:
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          details={"langs": got})
        if fetcher.quota_exhausted:
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="quota_exhausted")
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                      reason=f"no subtitles found ({', '.join(missing)})")

    except Exception as e:
        logging.exception("Subtitles failed: %s", mkv.name)
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False, reason=str(e))


def run_subtitles_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
) -> List[Result]:
    """Scan Movies/TV roots and download missing sidecar subtitles."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root = tv_root or CFG.TV_ROOT

    if not dry_run and not (CFG.OS_API_KEY and CFG.OS_USERNAME and CFG.OS_PASSWORD):
        logging.error("--subtitles requires api_key, username, and password in the "
                      "[subtitles] section of %s.", CONFIG_FILE.name)
        return [Result(kind="subtitles", source_items=[], output_path=None, ok=False,
                       reason="missing OpenSubtitles credentials")]

    movie_set: set[Path] = set(scan_mkvs(movies_root)) if do_movies else set()
    tv_set: set[Path] = set(scan_mkvs(tv_root)) if do_tv else set()
    if do_movies:
        logging.info("subtitles - Movies: %d MKV(s) found in %s.", len(movie_set), movies_root)
    if do_tv:
        logging.info("subtitles - TV: %d MKV(s) found in %s.", len(tv_set), tv_root)

    tagged: List[Tuple[Path, bool]] = []
    for p in sorted(movie_set | tv_set):
        if p in movie_set and p in tv_set:
            is_tv = bool(_SEASON_EP_RE.search(p.stem))
        else:
            is_tv = p in tv_set
        tagged.append((p, is_tv))

    fetcher = SubtitleFetcher()
    results: List[Result] = []
    # Keep concurrency low: the API rate-limits, and quota is a shared resource.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, max(1, workers))) as ex:
        futs = {ex.submit(process_subtitles_one, p, is_tv, fetcher, dry_run): p
                for p, is_tv in tagged}
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("subtitles worker crashed: %s", p)
                results.append(Result(kind="subtitles", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))
    return results


# =========================
# Movie processing - ENHANCED
# =========================

def choose_best_video_across_files(metas: Dict[Path, Tuple[List[Track], int]]) -> Tuple[Path, Track]:
    """
    Choose the best video track across all files, preferring x265/HEVC.
    """
    best: Optional[Tuple[Tuple, Path, Track]] = None
    for f, (tracks, fsize) in metas.items():
        for t in tracks:
            if t.type != "video":
                continue
            sc = score_video(t, fsize)
            cand = (sc, f, t)
            if best is None or cand[0] < best[0]:
                best = cand
    if best is None:
        raise RuntimeError("No video track found across candidates.")
    return best[1], best[2]


def collect_all_audio_by_language(metas: Dict[Path, Tuple[List[Track], int]]) -> Dict[str, List[Tuple[Path, Track]]]:
    """
    ENHANCED: Collect ALL audio tracks for Hindi, Telugu, and English ONLY from all files.
    Returns Dict[canonical_lang, List[Tuple[file, track]]]
    
    This allows merging multiple audio tracks of the same language from different files.
    Tracks from other languages are completely excluded.
    Each list is sorted by quality (best first).
    """
    audio_collections: Dict[str, List[Tuple[Tuple, Path, Track]]] = {}
    
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "audio":
                continue
            if is_excluded_audio(t):
                continue
            
            # Detect language
            canon = detect_language_canonical(t)
            
            # ONLY include Hindi, Telugu, and English (skip all other languages)
            if canon not in CFG.LANG_CANONICAL_ORDER:
                logging.debug("Skipping audio track (unsupported language): %s | track=%d lang=%s name=%s", 
                            f.name, t.id, t.language, t.name)
                continue
            
            sc = score_audio(t)
            if canon not in audio_collections:
                audio_collections[canon] = []
            audio_collections[canon].append((sc, f, t))
    
    # Sort each language's tracks by score (best first) and convert to final format
    result: Dict[str, List[Tuple[Path, Track]]] = {}
    for canon, track_list in audio_collections.items():
        track_list.sort(key=lambda x: x[0])  # Sort by score
        result[canon] = [(f, t) for (_, f, t) in track_list]
    
    return result


def choose_best_audio_by_language(metas: Dict[Path, Tuple[List[Track], int]]) -> Dict[str, Tuple[Path, Track]]:
    """
    Original function: Choose only the BEST audio track for each language.
    Kept for backward compatibility with TV processing.
    """
    chosen: Dict[str, Tuple[Path, Track]] = {}
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "audio":
                continue
            if is_excluded_audio(t):
                continue
            canon = detect_language_canonical(t)
            if canon not in CFG.LANG_CANONICAL_ORDER:
                continue
            sc = score_audio(t)
            if canon not in chosen:
                chosen[canon] = (f, t)
            else:
                _, cur = chosen[canon]
                if sc < score_audio(cur):
                    chosen[canon] = (f, t)
    return chosen


def choose_best_english_sub(metas: Dict[Path, Tuple[List[Track], int]], include_forced: bool) -> Optional[Tuple[Path, Track]]:
    """Kept for reference; collect_all_subtitles is used in the pipeline instead."""
    candidates_normal: List[Tuple[Tuple, Path, Track]] = []
    candidates_forced: List[Tuple[Tuple, Path, Track]] = []
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "subtitles":
                continue
            canon = detect_language_canonical(t)
            if canon != "Eng":
                continue
            sc = score_sub(t, include_forced=include_forced)
            if t.forced:
                candidates_forced.append((sc, f, t))
            else:
                candidates_normal.append((sc, f, t))

    if candidates_normal:
        candidates_normal.sort(key=lambda x: x[0])
        return (candidates_normal[0][1], candidates_normal[0][2])

    if include_forced and candidates_forced:
        candidates_forced.sort(key=lambda x: x[0])
        return (candidates_forced[0][1], candidates_forced[0][2])

    return None


def collect_all_subtitles(
    metas: Dict[Path, Tuple[List[Track], int]]
) -> Dict[Path, List[Track]]:
    """
    Collect subtitle tracks from all source files, grouped by file.

    Rules applied:
    - Only keep tracks whose language is Hindi, Telugu, or English (target langs).
    - Keep BOTH regular AND SDH/hearing-impaired tracks for all three languages.
    - Strip commentary/SDH-excluded subtitle tracks (non-SDH exclusions only).
    - When the same (language, codec, sdh_flag) combination appears in more than
      one source file, keep only the best-scoring one to avoid duplicates.

    Returns Dict[file_path, List[Track]] sorted by original track id within each file.
    """
    target_langs = set(CFG.LANG_CANONICAL_ORDER)

    # key: (canonical_lang, codec_id, is_sdh) -> (score, file, track)
    best_by_key: Dict[Tuple[str, str, bool], Tuple[Tuple, Path, Track]] = {}

    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "subtitles":
                continue
            canon = detect_language_canonical(t)
            if canon not in target_langs:
                logging.debug("Dropping subtitle track (non-target language): file=%s track=%d lang=%s name=%r",
                              f.name, t.id, t.language, t.name)
                continue
            sdh = is_sdh_subtitle(t)
            codec_key = (t.codec_id or "").lower()
            dedup_key = (canon, codec_key, sdh)
            sc = score_sub(t, include_forced=True)
            if dedup_key not in best_by_key or sc < best_by_key[dedup_key][0]:
                best_by_key[dedup_key] = (sc, f, t)

    result: Dict[Path, List[Track]] = {}
    for (_lang, _codec, _sdh), (sc, f, t) in best_by_key.items():
        result.setdefault(f, []).append(t)

    for f in result:
        result[f].sort(key=lambda t: t.id)

    return result


def compute_relpath_under_root(p: Path, root: Path) -> Path:
    try:
        return p.relative_to(root)
    except ValueError:
        # Should not happen; fallback
        return Path(p.name)


def output_path_for_item(src_item: Path, root: Path, new_filename: str) -> Path:
    rel = compute_relpath_under_root(src_item, root)
    return CFG.OUTPUT_ROOT / rel.parent / new_filename


def working_path_for_item(src_item: Path, root: Path) -> Path:
    rel = compute_relpath_under_root(src_item, root)
    return CFG.WORK_ROOT / rel


def build_movie_output_name(
    movie_name: str,
    year: Optional[str],
    imdb_id: Optional[str],
    res_tag: str,
    source_tag: Optional[str],
    codec_tag: str,
    audio_langs: List[str],
) -> str:
    """
    Movies naming (requested):
      Movie Name (Year) - imdbID - RipType.Resolution.VideoCodec - [Lang1 + Lang2 + Lang3].mkv

    Example:
      The Film (2026) - tt1234567 - HDRip.1080p.x265 - [Telugu + Hindi].mkv
    """
    base = sanitize_filename(movie_name)
    title = f"{base} ({year})" if year else base

    bracket = build_audio_bracket(audio_langs)

    # Rip (source) is first; fall back to WebRip if unknown/missing
    rip = sanitize_filename(source_tag) if source_tag else "WebRip"
    mid = f"{rip}.{res_tag}.{codec_tag}"

    imdb_part = f"{sanitize_filename(imdb_id)}" if imdb_id else None
    if imdb_part:
        fn = f"{title} - {imdb_part} - {mid} - [{bracket}].mkv"
    else:
        fn = f"{title} - {mid} - [{bracket}].mkv"

    return fn


def process_movie_group(
    group: List[Path],
    movies_root: Path,
    dry_run: bool,
    overwrite: bool,
    include_forced_subs: bool,
    audio_lang_filter: Optional[List[str]] = None,
    skip_cleantags: bool = False,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
) -> Result:
    """
    ENHANCED: Process a group of similar movie files.
    
    When multiple files are found:
    - Select the best x265/HEVC video track from any file
    - Collect ALL Hindi, Telugu, and English audio tracks from ALL files (other languages excluded)
    - Select the best English subtitle
    - Merge everything into a single optimized MKV file
    
    Audio tracks in other languages (e.g., Japanese, French, Spanish) are NOT included.
    """
    kind = "movie_cleanup" if len(group) == 1 else "movie_merge"
    try:
        # Prepare working copies
        work_map: Dict[Path, Path] = {}
        work_files: List[Path] = []
        for src in group:
            work = working_path_for_item(src, movies_root)
            work = ensure_working_copy(src, work, dry_run=dry_run)
            work_map[src] = work
            work_files.append(work)

        # Identify tracks 
        metas: Dict[Path, Tuple[List[Track], int]] = {}
        for src in group:
            work = work_map[src]

            # Use source size for tie-break; safe even if dry_run
            fsize = src.stat().st_size if src.exists() else 0

            if dry_run:
                meta = mkvmerge_identify_json(work if work.exists() else src)
            else:
                meta = mkvmerge_identify_json(work)

            tracks = extract_tracks(work, meta)
            # Apply forced language overrides before any detection runs
            apply_track_lang_overrides(tracks, force_audio_langs or {}, force_sub_langs or {})
            metas[work] = (tracks, fsize)

        # Determine movie name/year/imdb (prefer FileBot-normalized working filename; fall back to heuristic)
        movie_name: str
        year: Optional[str]
        imdb_id: Optional[str]

        movie_name = ""
        year = None
        imdb_id = None

        # Prefer parsing from FileBot-normalized working filenames: 'Name (Year) - tt1234567'
        for wf in metas.keys():
            t, y, imdb = parse_title_year_imdb_from_filename(wf)
            if t and y:
                movie_name, year = t, y
                imdb_id = imdb_id or imdb
                break

        # Fallback: derive from original path(s)
        if not movie_name:
            movie_name, year = infer_movie_name_year_from_path(group[0])

        if not imdb_id:
            imdb_id = next((extract_imdb_id_from_movie_path(p) for p in group if extract_imdb_id_from_movie_path(p)), None)

        movie_title = f"{movie_name} ({year})" if year else movie_name

        # Best video (prefer x265/HEVC)
        best_video_file, best_video = choose_best_video_across_files(metas)

        # Keep ALL audio tracks per target language across all files (Hindi/English/Telugu only)
        audios = collect_all_audio_by_language(metas)

        # Apply user-supplied language filter if provided
        if audio_lang_filter is not None:
            audios = {k: v for k, v in audios.items() if k in audio_lang_filter}
            logging.info("Audio language filter applied: keeping %s", audio_lang_filter)

        # Collect subtitle tracks: Hindi + Telugu + English only, regular + SDH both kept
        all_subs: Dict[Path, List[Track]] = collect_all_subtitles(metas)

        selected_audio_langs = [k for k in CFG.LANG_CANONICAL_ORDER if k in audios]

        res_tag = infer_resolution_tag_from_video(best_video, fallback_filename=group[0].name)
        codec_tag = codec_tag_video(best_video)
        if codec_tag in ("unknown", "video"):
            codec_tag = infer_codec_tag_from_filename(group[0].name) or codec_tag

        source_tag = infer_source_tag_from_filename(group[0].name)

        # ── SKIP-REMUX / RULE-7 CHECKS (single-file groups only) ─────────────
        if len(group) == 1:
            _all_tracks_single = metas[list(metas.keys())[0]][0]
            _actual_audio_count = sum(1 for t in _all_tracks_single if t.type == "audio" and not is_excluded_audio(t))
            _total_target_audio_count = sum(len(v) for v in audios.values())

            # Rule 7: no target languages found — keep all tracks, just rename/tag
            if _actual_audio_count > 0 and _total_target_audio_count == 0:
                logging.warning("movie: no target audio languages (Hindi/English/Telugu) found in %s — skipping remux, renaming only.", group[0].name)
                src_file = group[0]
                out_done = src_file
                if not dry_run:
                    # In-place path: working copies aren't needed — remove them.
                    cleanup_working_copies(work_files, dry_run=False)
                    _single_tracks = metas[list(metas.keys())[0]][0]
                    fix_track_langs_inplace(src_file, _single_tracks, force_audio_langs or {}, force_sub_langs or {})
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                        ct = clean_mkv_tags(src_file, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags failed (non-fatal): %s", ct.reason)
                    fb_path = run_filebot_rename_final_mkv(src_file, db=CFG.FILEBOT_DB,
                                                           filebot_format=MOVIE_FILEBOT_FORMAT,
                                                           dry_run=False, query=movie_title)
                    if fb_path and fb_path.exists() and fb_path != src_file:
                        out_done = fb_path
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                        ct = clean_mkv_tags(out_done, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
                else:
                    logging.info("[DRY] Would rename/tag in-place (no target langs): %s", src_file.name)
                logging.info("movie_no_target_langs OK -> %s", out_done)
                return Result(kind="movie_no_target_langs", source_items=group, output_path=out_done, ok=True,
                              details={"reason": "no_target_languages_found"})

            # Rules 1,2,5,6: all audio tracks are target languages — no remux needed
            if _actual_audio_count == _total_target_audio_count:
                src_file = group[0]
                logging.info("movie_skip_remux: %s has %d audio track(s) %s, all target langs — skipping remux.",
                             src_file.name, _actual_audio_count, selected_audio_langs)
                out_done = src_file
                if not dry_run:
                    # In-place path: working copies aren't needed — remove them.
                    cleanup_working_copies(work_files, dry_run=False)
                    _single_tracks = metas[list(metas.keys())[0]][0]
                    fix_track_langs_inplace(src_file, _single_tracks, force_audio_langs or {}, force_sub_langs or {})
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                        logging.info("Auto-cleantags (pre-FileBot, in-place) on: %s", src_file.name)
                        ct = clean_mkv_tags(src_file, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)
                    logging.info("FileBot identify+rename (in-place): %s", src_file.name)
                    fb_path = run_filebot_rename_final_mkv(src_file, db=CFG.FILEBOT_DB,
                                                           filebot_format=MOVIE_FILEBOT_FORMAT,
                                                           dry_run=False, query=movie_title)
                    if fb_path and fb_path.exists() and fb_path != src_file:
                        logging.info("FileBot renamed -> %s", fb_path.name)
                        out_done = fb_path
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                        logging.info("Auto-cleantags (post-FileBot, in-place) on: %s", out_done.name)
                        ct = clean_mkv_tags(out_done, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
                else:
                    logging.info("[DRY] Would run FileBot + cleantags in-place on: %s", src_file.name)
                logging.info("movie_skip_remux OK -> %s", out_done)
                return Result(kind="movie_skip_remux", source_items=group, output_path=out_done, ok=True,
                              details={"audio_langs": selected_audio_langs, "reason": "already_has_required_tracks"})

            # Rules 3,4: has target langs + extra languages — remux to strip extras
            logging.info("movie: file has %d audio tracks total, %d are target langs — remuxing to strip extras.",
                         _actual_audio_count, _total_target_audio_count)
        # ─────────────────────────────────────────────────────────────────────

        # SAFETY (multi-file groups): if the sources have audio but NONE of it was
        # detected as a target language, a merge would produce a video-only file.
        # Refuse instead — mislabeled 'und' tracks should be fixed with
        # --force-audio-lang first.
        if len(group) > 1:
            _any_audio = any(
                t.type == "audio" and not is_excluded_audio(t)
                for tracks_, _fs in metas.values() for t in tracks_
            )
            if _any_audio and not audios:
                return Result(
                    kind=kind, source_items=group, output_path=None, ok=False,
                    reason=("no target-language audio detected across group — merging would drop "
                            "ALL audio; fix language tags with --force-audio-lang and retry"))

        out_name = build_movie_output_name(movie_name, year, imdb_id, res_tag, source_tag, codec_tag, selected_audio_langs)

        out_final = output_path_for_item(group[0], movies_root, out_name)

        out_done = out_final

        # Build mkvmerge parts: video + all audio tracks + all subtitle tracks
        parts: List[Tuple[Path, Dict[str, Any]]] = []

        # Video part (best video file only)
        v_opt = {
            "video_tracks": [best_video.id],
            "audio_tracks": None,
            "sub_tracks": None,
            "track_names": {best_video.id: sanitize_filename(movie_title)},
        }
        parts.append((best_video_file, v_opt))

        # Audio — output order: Hindi → English → Telugu (LANG_CANONICAL_ORDER)
        # All tracks per language kept (e.g. stereo + 5.1 both included)
        for canon in CFG.LANG_CANONICAL_ORDER:
            if canon not in audios:
                continue
            lang_full_name = CFG.LANG_DISPLAY_MAP.get(canon, canon)
            for (afile, atrack) in audios[canon]:
                a_opt = {
                    "video_tracks": None,
                    "audio_tracks": [atrack.id],
                    "sub_tracks": None,
                    "track_names": {atrack.id: lang_full_name},
                }
                parts.append((afile, a_opt))
                logging.info("Adding audio track: %s from %s (track %d, codec=%s, channels=%s)",
                             lang_full_name, afile.name, atrack.id, atrack.codec_id, atrack.channels)

        # Add ALL subtitle tracks grouped by source file (tags cleaned later by mkvpropedit)
        total_subs = sum(len(v) for v in all_subs.values())
        logging.info("Subtitle tracks to include: %d", total_subs)
        for sfile, stracks in all_subs.items():
            s_opt = {
                "video_tracks": None,
                "audio_tracks": None,
                "sub_tracks": [t.id for t in stracks],
                "track_names": {},
            }
            parts.append((sfile, s_opt))
            for st in stracks:
                logging.info("  Sub track %d: lang=%s codec=%s forced=%s name=%r",
                             st.id, st.language, st.codec_id, st.forced, st.name)

        out_tmp = out_final.with_suffix(".mkv.tmp")
        if out_tmp.exists() and not dry_run:
            try:
                out_tmp.unlink()
            except Exception:
                pass

        r = mkvmerge_build_and_run(out_tmp, parts, dry_run=dry_run, segment_title=movie_title)
        if not r.ok:
            return Result(kind=kind, source_items=group, output_path=None, ok=False,
                          reason=f"mkvmerge failed rc={r.rc}", details={"stderr": r.err, "cmd": r.cmd})

        if not dry_run:
            atomic_move(out_tmp, out_final, overwrite=overwrite)
            cleanup_working_copies(work_files, dry_run=False)

        out_done = out_final

        # Log selection details
        logging.info("%s OK -> %s", kind, out_done)
        logging.info("Selected video: %s | track=%d codec_id=%s %sx%s",
                     best_video_file.name, best_video.id, best_video.codec_id, best_video.width, best_video.height)

        # Log selected audio tracks
        total_audio_tracks = sum(len(v) for v in audios.values())
        logging.info("Audio tracks included: %d across %d language(s)", total_audio_tracks, len(selected_audio_langs))
        for canon in selected_audio_langs:
            for (afile, atrack) in audios[canon]:
                logging.info("  Audio %s: %s | track=%d codec_id=%s channels=%s",
                             canon, afile.name, atrack.id, atrack.codec_id, atrack.channels)

        if not dry_run:
            # Step 1: cleantags — strip release tags and write a clean segment title.
            # This gives FileBot the best possible signal for DB lookup in step 2.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (pre-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False)
                if not ct.ok:
                    logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)

            # Step 2: FileBot rename — identify movie via DB and apply canonical filename.
            logging.info("FileBot identify+rename: %s", out_done.name)
            fb_path = run_filebot_rename_final_mkv(
                out_done,
                db=CFG.FILEBOT_DB,
                filebot_format=MOVIE_FILEBOT_FORMAT,
                dry_run=dry_run,
                query=movie_title,
            )
            if fb_path and fb_path.exists() and fb_path != out_done:
                logging.info("FileBot renamed -> %s", fb_path.name)
                out_done = fb_path

            # Step 3: cleantags again on the final (possibly renamed) file so the segment
            # title matches the canonical FileBot-assigned filename.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (post-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False)
                if not ct.ok:
                    logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)

        return Result(kind=kind, source_items=group, output_path=out_done, ok=True,
                      details={"cmd": r.cmd, "audio_langs": selected_audio_langs})

    except FileExistsError as e:
        return Result(kind=kind, source_items=group, output_path=None, ok=False, reason=str(e))
    except Exception as e:
        logging.exception("Movie group failed: %s", [p.name for p in group])
        return Result(kind=kind, source_items=group, output_path=None, ok=False, reason=str(e))


# =========================
# TV processing (unchanged from original)
# =========================

def infer_tv_components(p: Path) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Infer TV components from path:
      returns (show_with_year, season_str, ep_str, episode_title)

    Tries hard to keep Plex/Jellyfin-friendly values:
      Show (Year) - SxxEyy - Title
    """
    stem = p.stem.replace('.', ' ').replace('_', ' ')
    stem = re.sub(r"\s+", " ", stem).strip()

    # Season/Episode
    m = _SEASON_EP_RE.search(stem)
    season_str = ep_str = None
    if m:
        season_str = f"S{int(m.group(1)):02d}"
        ep_str = f"E{int(m.group(2)):02d}"

    # Episode title heuristics: common pattern "Show - S01E01 - Title"
    episode_title: Optional[str] = None
    m2 = re.search(r"\s-\sS\d{1,2}E\d{1,2}\s-\s(.+)$", stem, flags=re.I)
    if m2:
        episode_title = m2.group(1).strip()
        # Strip trailing technical tags and language brackets
        episode_title = _MOVIE_NOISE_TOKENS.sub(" ", episode_title)
        episode_title = re.sub(r"\[[^\]]+\]", " ", episode_title)
        # Normalize spaces FIRST so multi-space gaps from removed tokens become single spaces.
        # Then strip any trailing junk: dashes, dots, spaces left behind after token removal
        # (e.g., "Title - . -" from "Title - 1080p.x264 - [langs]" -> "Title")
        episode_title = re.sub(r"\s+", " ", episode_title).strip()
        episode_title = re.sub(r"[\s.\-–—]+$", "", episode_title).strip()

    # Show (Year) from parent folder when available (best signal)
    parent = p.parent.name
    parent_clean = parent.replace('.', ' ').replace('_', ' ')
    parent_clean = re.sub(r"\s+", " ", parent_clean).strip()
    show_with_year = None
    pm = re.search(r"^(.+?\(\d{4}\))", parent_clean)
    if pm:
        show_with_year = pm.group(1).strip()
    else:
        # fallback: take left side of " - SxxExx - " pattern
        m3 = re.search(r"^(.+?)\s-\sS\d{1,2}E\d{1,2}\b", stem, flags=re.I)
        if m3:
            show_with_year = m3.group(1).strip()
        else:
            # fallback: remove SxxExx then clean
            tmp = stem
            if m:
                tmp = tmp[:m.start()] + tmp[m.end():]
            tmp = _MOVIE_NOISE_TOKENS.sub(" ", tmp)
            tmp = re.sub(r"\s+", " ", tmp).strip()
            show_with_year = tmp or parent_clean or "UnknownShow"

    show_with_year = sanitize_filename(show_with_year)

    if episode_title:
        episode_title = sanitize_filename(episode_title)

    return show_with_year, season_str, ep_str, episode_title



def build_tv_output_name(
    show_with_year: str,
    season_str: Optional[str],
    ep_str: Optional[str],
    episode_title: Optional[str],
    res_tag: str,
    codec_tag: str,
    audio_langs: List[str],
) -> str:
    """
    Plex/Jellyfin-friendly TV naming (fallback when FileBot is unavailable):

      Show (Year) - SxxEyy - Episode Title - 1080p.x265 - [Telugu + Hindi].mkv
    """
    base = sanitize_filename(show_with_year) or "UnknownShow"

    se = ""
    if season_str and ep_str:
        se = f"{season_str}{ep_str}"
    elif season_str:
        se = season_str

    title = sanitize_filename(episode_title) if episode_title else None

    bracket = build_audio_bracket(audio_langs)

    parts = [base]
    if se:
        parts.append(se)
    if title:
        parts.append(title)

    prefix = " - ".join(parts)
    fn = f"{prefix} - {res_tag}.{codec_tag} - [{bracket}].mkv"
    # Collapse any consecutive " - " sequences that slipped through (e.g., "Title - - 1080p")
    fn = re.sub(r"(\s+-\s+){2,}", " - ", fn)
    return sanitize_filename(fn)



def process_tv_file(
    src: Path,
    tv_root: Path,
    dry_run: bool,
    overwrite: bool,
    include_forced_subs: bool,
    audio_lang_filter: Optional[List[str]] = None,
    skip_cleantags: bool = False,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
) -> Result:
    """
    Process a single TV episode file.
    Uses the original logic (best single track per language).
    """
    kind = "tv_cleanup"
    try:
        work = working_path_for_item(src, tv_root)
        work = ensure_working_copy(src, work, dry_run=dry_run)

        fsize = src.stat().st_size if src.exists() else 0
        if dry_run:
            if work.exists():
                meta = mkvmerge_identify_json(work)
            else:
                meta = mkvmerge_identify_json(src)
        else:
            meta = mkvmerge_identify_json(work)

        tracks = extract_tracks(work, meta)
        # Apply forced language overrides before any detection runs
        apply_track_lang_overrides(tracks, force_audio_langs or {}, force_sub_langs or {})
        metas = {work: (tracks, fsize)}

        show_name, season_str, ep_str, ep_title = infer_tv_components(src)

        best_video_file, best_v = choose_best_video_across_files(metas)
        # Keep ALL audio tracks per target language (supports duplicate tracks, e.g. stereo + 5.1)
        audios = collect_all_audio_by_language(metas)

        # Apply user-supplied language filter if provided
        if audio_lang_filter is not None:
            audios = {k: v for k, v in audios.items() if k in audio_lang_filter}
            logging.info("Audio language filter applied: keeping %s", audio_lang_filter)

        # Collect subtitle tracks: Hindi + Telugu + English only, regular + SDH both kept
        all_subs: Dict[Path, List[Track]] = collect_all_subtitles(metas)

        selected_audio_langs = [k for k in CFG.LANG_CANONICAL_ORDER if k in audios]
        res_tag = infer_resolution_tag_from_video(best_v, fallback_filename=str(src))
        codec_tag = codec_tag_video(best_v)
        if codec_tag in ("unknown", "video"):
            codec_tag = infer_codec_tag_from_filename(str(src)) or codec_tag

        # ── SKIP-REMUX / RULE-7 CHECKS ───────────────────────────────────────
        _actual_audio_count = sum(1 for t in tracks if t.type == "audio" and not is_excluded_audio(t))
        _total_target_audio_count = sum(len(v) for v in audios.values())

        # Rule 7: file has no target languages at all — keep as-is, just rename/tag
        if _actual_audio_count > 0 and _total_target_audio_count == 0:
            logging.warning("tv: no target audio languages (Hindi/English/Telugu) found in %s — skipping remux, renaming only.", src.name)
            out_done = src
            if not dry_run:
                if work.exists() and work != src:
                    cleanup_working_copies([work], dry_run=False)
                fix_track_langs_inplace(src, tracks, force_audio_langs or {}, force_sub_langs or {})
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                    ct = clean_mkv_tags(src, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags failed (non-fatal): %s", ct.reason)
                fb_path = run_filebot_rename_final_mkv(src, db="TheTVDB", filebot_format=TV_FILEBOT_FORMAT,
                                                       dry_run=False, query=show_name)
                if fb_path and fb_path.exists() and fb_path != src:
                    out_done = fb_path
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                    ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
            else:
                logging.info("[DRY] Would rename/tag in-place (no target langs): %s", src.name)
            logging.info("tv_no_target_langs OK -> %s", out_done)
            return Result(kind="tv_no_target_langs", source_items=[src], output_path=out_done, ok=True,
                          details={"reason": "no_target_languages_found"})

        # Rules 1,2,5,6: all audio tracks in the file are already target languages — no remux needed
        _no_extra_tracks = _actual_audio_count == _total_target_audio_count
        if _no_extra_tracks:
            logging.info("tv_skip_remux: %s has %d audio track(s) %s, all target langs — skipping remux.",
                         src.name, _actual_audio_count, selected_audio_langs)
            out_done = src

            if not dry_run:
                if work.exists() and work != src:
                    cleanup_working_copies([work], dry_run=False)
                fix_track_langs_inplace(src, tracks, force_audio_langs or {}, force_sub_langs or {})
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                    logging.info("Auto-cleantags (pre-FileBot, in-place) on: %s", src.name)
                    ct = clean_mkv_tags(src, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)
                logging.info("FileBot identify+rename (in-place): %s", src.name)
                fb_path = run_filebot_rename_final_mkv(src, db="TheTVDB", filebot_format=TV_FILEBOT_FORMAT, dry_run=False,
                                                       query=show_name)
                if fb_path and fb_path.exists() and fb_path != src:
                    logging.info("FileBot renamed -> %s", fb_path.name)
                    out_done = fb_path
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                    logging.info("Auto-cleantags (post-FileBot, in-place) on: %s", out_done.name)
                    ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
            else:
                logging.info("[DRY] Would run FileBot + cleantags in-place on: %s", src.name)

            logging.info("tv_skip_remux OK -> %s", out_done)
            return Result(kind="tv_skip_remux", source_items=[src], output_path=out_done, ok=True,
                          details={"audio_langs": selected_audio_langs, "reason": "already_has_required_tracks"})

        # Rules 3,4: has target langs + extra languages — remux to strip extras
        logging.info("tv: file has %d audio tracks total, %d are target langs — remuxing to strip extras.",
                     _actual_audio_count, _total_target_audio_count)
        # ─────────────────────────────────────────────────────────────────────

        out_name = build_tv_output_name(show_name, season_str, ep_str, ep_title, res_tag, codec_tag, selected_audio_langs)
        out_final = output_path_for_item(src, tv_root, out_name)

        parts: List[Tuple[Path, Dict[str, Any]]] = []

        # Video
        parts.append((work, {
            "video_tracks": [best_v.id],
            "audio_tracks": None,
            "sub_tracks": None,
            "track_names": {best_v.id: f"{show_name} - {season_str}{ep_str}" if season_str and ep_str else show_name},
        }))

        # Audio — output order: Hindi → English → Telugu (LANG_CANONICAL_ORDER)
        # All tracks per language are kept (e.g. stereo + 5.1 both included)
        _lang_display = {"Tel": "Telugu", "Hin": "Hindi", "Eng": "English"}
        for canon in CFG.LANG_CANONICAL_ORDER:
            if canon not in audios:
                continue
            title = _lang_display[canon]
            for (afile, t) in audios[canon]:
                parts.append((afile, {
                    "video_tracks": None,
                    "audio_tracks": [t.id],
                    "sub_tracks": None,
                    "track_names": {t.id: title},
                }))

        # All subtitle tracks grouped by source file (tags cleaned later by mkvpropedit)
        total_subs = sum(len(v) for v in all_subs.values())
        logging.info("Subtitle tracks to include: %d", total_subs)
        for sfile, stracks in all_subs.items():
            parts.append((sfile, {
                "video_tracks": None,
                "audio_tracks": None,
                "sub_tracks": [t.id for t in stracks],
                "track_names": {},
            }))
            for st in stracks:
                logging.info("  Sub track %d: lang=%s codec=%s forced=%s name=%r",
                             st.id, st.language, st.codec_id, st.forced, st.name)

        out_tmp = out_final.with_suffix(".mkv.tmp")
        if out_tmp.exists() and not dry_run:
            try:
                out_tmp.unlink()
            except Exception:
                pass

        r = mkvmerge_build_and_run(out_tmp, parts, dry_run=dry_run)
        if not r.ok:
            return Result(kind=kind, source_items=[src], output_path=None, ok=False,
                          reason=f"mkvmerge failed rc={r.rc}", details={"stderr": r.err, "cmd": r.cmd})

        if not dry_run:
            atomic_move(out_tmp, out_final, overwrite=overwrite)
            cleanup_working_copies([work], dry_run=False)

        out_done = out_final

        logging.info("%s OK -> %s", kind, out_done)
        logging.info("Selected video: track=%d codec_id=%s %sx%s", best_v.id, best_v.codec_id, best_v.width, best_v.height)
        for canon, track_list in audios.items():
            for (_f, t) in track_list:
                logging.info("Selected audio %s: track=%d codec_id=%s channels=%s", canon, t.id, t.codec_id, t.channels)

        if not dry_run:
            # Step 1: cleantags — strip release tags and write clean segment title so
            # FileBot can identify the episode from clean metadata in step 2.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (pre-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                if not ct.ok:
                    logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)

            # Step 2: FileBot rename — identify episode via TheTVDB and rename.
            logging.info("FileBot identify+rename: %s", out_done.name)
            fb_path = run_filebot_rename_final_mkv(
                out_done,
                db="TheTVDB",
                filebot_format=TV_FILEBOT_FORMAT,
                dry_run=dry_run,
                query=show_name,
            )
            if fb_path and fb_path.exists() and fb_path != out_done:
                logging.info("FileBot renamed -> %s", fb_path.name)
                out_done = fb_path

            # Step 3: cleantags again on final path so segment title reflects the
            # canonical FileBot-assigned episode name.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (post-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                if not ct.ok:
                    logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)

        return Result(kind=kind, source_items=[src], output_path=out_done, ok=True,
                      details={"cmd": r.cmd, "audio_langs": selected_audio_langs})

    except FileExistsError as e:
        return Result(kind=kind, source_items=[src], output_path=None, ok=False, reason=str(e))
    except Exception as e:
        logging.exception("TV file failed: %s", src)
        return Result(kind=kind, source_items=[src], output_path=None, ok=False, reason=str(e))


# =========================
# Movies pipeline (per folder)
# =========================

def group_movies_by_folder(movies: List[Path]) -> Dict[Path, List[Path]]:
    folders: Dict[Path, List[Path]] = {}
    for p in movies:
        folders.setdefault(p.parent, []).append(p)
    return folders


# =========================
# Self-check
# =========================

def self_check() -> int:
    logging.info("Self-check: validating tools and folder access...")

    try:
        validate_tools()
    except Exception as e:
        logging.error("Self-check failed: tools: %s", e)
        return 2

    for d in (CFG.MOVIES_ROOT, CFG.TV_ROOT, CFG.WORK_ROOT, CFG.OUTPUT_ROOT):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.error("Self-check failed: cannot access/create: %s | %s", d, e)
            return 3

    # Validate any configured API keys (same checks as --validate-keys)
    if CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY:
        key_status = validate_api_keys()
        for source, st in key_status.items():
            logging.info("Self-check API key %-10s: %s", source, st.upper() if st == "invalid" else st)
        if any(st == "invalid" for st in key_status.values()):
            logging.error("Self-check failed: invalid API key(s) in [coverart] of %s", CONFIG_FILE)
            return 6

    # Attempt mkvmerge -J on a sample if any MKV exists
    sample = None
    for root in (CFG.MOVIES_ROOT, CFG.TV_ROOT):
        mkvs = scan_mkvs(root)
        if mkvs:
            sample = mkvs[0]
            break

    if not sample:
        logging.warning("Self-check: no MKV files found under Movies/TV roots; skipping JSON parse test.")
        return 0

    try:
        meta = mkvmerge_identify_json(sample)
        if "tracks" not in meta:
            logging.error("Self-check failed: mkvmerge JSON missing 'tracks'.")
            return 4
        logging.info("Self-check OK: mkvmerge JSON parsed: %s tracks=%d", sample.name, len(meta.get("tracks", [])))
        return 0
    except Exception as e:
        logging.error("Self-check failed: mkvmerge -J parse: %s", e)
        return 5


# =========================
# Main
# =========================

def main() -> int:
    ap = argparse.ArgumentParser(description="MediaCleanup.py (Enhanced) - MKV cleanup/merge tool (Movies + TV) using MKVToolNix")
    ap.add_argument("--dry-run", action="store_true", help="Log actions without copying/remuxing.")
    ap.add_argument("--verbose", action="store_true", help="Enable verbose debug logging.")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="Parallel workers.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    ap.add_argument("--log-file", type=str, default="", help="Optional log file path.")
    
    # Selection flags:
    # - If neither --movies nor --tv is provided, default is BOTH (Movies + TV).
    # - If one (or both) is provided, run exactly what is selected.
    ap.add_argument("--movies", action="store_true", help="Process Movies pipeline.")
    ap.add_argument("--tv", action="store_true", help="Process TV pipeline.")
    # Backward-compatibility (deprecated):
    ap.add_argument("--only-movies", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--only-tv", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--input", type=str, default="", metavar="PATH",
                    help="Override the scan root folder. With --movies, scans this path instead of "
                         "MOVIES_ROOT. With --tv, scans instead of TV_ROOT. With both (or neither), "
                         "applies to both pipelines. Also applies to --cleantags.")
    ap.add_argument("--self-check", action="store_true", help="Run unit-test-like self checks and exit.")
    ap.add_argument("--cleantags", action="store_true",
                    help="Standalone mode: clean promotional/watermark tags in-place on every MKV in the "
                         "scan root using mkvpropedit. Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--coverart", action="store_true",
                    help="Standalone mode: fetch and embed cover art (cover.jpg attachment) into every "
                         "MKV in the scan root that doesn't already have one. Source chain: local "
                         "poster.jpg/cover.jpg/folder.jpg, then TMDB, fanart.tv, OMDb (API keys in the "
                         "[coverart] section of MediaCleanup.toml). Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--coverart-overwrite", action="store_true",
                    help="With --coverart: replace existing embedded cover art instead of skipping the file.")
    ap.add_argument("--rename", action="store_true",
                    help="Standalone mode: rename MKVs into the canonical naming format via FileBot "
                         "(no remux, no tag changes unless --force-*-lang is given). Requires exactly "
                         "one of --movies or --tv, plus --input for the folder to scan. In-place by "
                         "default; see --rename-into. Every rename is logged for --rename-undo.")
    ap.add_argument("--rename-into", action="store_true",
                    help="With --rename: move files into the library structure under MOVIES_ROOT/TV_ROOT "
                         "(Movies: 'Title (Year)/...'; TV: 'Show (Year)/Season XX/...').")
    ap.add_argument("--rename-undo", action="store_true",
                    help="Revert the most recent --rename batch recorded in logs/rename_history.csv, then exit.")
    ap.add_argument("--subtitles", action="store_true",
                    help="Standalone mode: download missing subtitles from OpenSubtitles.com as sidecar "
                         ".srt files (no remux). Languages come from [subtitles] in MediaCleanup.toml "
                         "(default: English). Skips files that already have the language embedded or as "
                         "a sidecar. Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--validate-keys", action="store_true",
                    help="Test the API keys in MediaCleanup.toml with one cheap call each "
                         "(TMDB, fanart.tv, OMDb, OpenSubtitles), print a verdict per key, and exit. "
                         "Exit code 1 if any configured key is invalid.")
    ap.add_argument("--no-fetch-tags", action="store_true",
                    help="Disable rich metadata tagging (genre/director/actors/synopsis from TMDB+OMDb) "
                         "during tag cleaning. Default: enabled whenever API keys are configured.")
    ap.add_argument("--skip-cleantags", action="store_true",
                    help="Disable the automatic tag-clean step that normally runs after each remux.")
    ap.add_argument("--include-forced-subs", action="store_true", help="Allow forced English subtitle selection.")
    ap.add_argument(
        "--audio-langs", nargs="+", metavar="LANG", default=None,
        help=(
            "Restrict audio tracks to these languages only. "
            "Accepts full names or codes: Telugu/tel, Hindi/hin, English/eng. "
            "Example: --audio-langs Telugu Hindi"
        ),
    )
    ap.add_argument("--similarity-threshold", type=float, default=Config.SIMILARITY_THRESHOLD_DEFAULT,
                    help=f"Movies grouping similarity threshold (default {Config.SIMILARITY_THRESHOLD_DEFAULT}).")
    ap.add_argument(
        "--force-audio-lang", nargs=2, action="append", metavar=("TRACK_ID", "LANG"), default=None,
        help="Force a specific audio track ID to be treated as a given language. "
             "Can be repeated. Example: --force-audio-lang 1 Hindi --force-audio-lang 2 Telugu"
    )
    ap.add_argument(
        "--force-sub-lang", nargs=2, action="append", metavar=("TRACK_ID", "LANG"), default=None,
        help="Force a specific subtitle track ID to be treated as a given language. "
             "Can be repeated. Example: --force-sub-lang 3 English"
    )
    args = ap.parse_args()

    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(args.verbose, log_file)

    # Load paths from MediaCleanup.toml (same folder as this script).
    global CFG
    try:
        CFG = load_config()
    except ConfigError as e:
        logging.error("%s", e)
        return 2
    logging.debug("Config loaded from %s", CONFIG_FILE)

    global _FETCH_TAGS_ENABLED
    if args.no_fetch_tags:
        _FETCH_TAGS_ENABLED = False
        logging.info("Rich metadata tagging disabled (--no-fetch-tags).")

    # --validate-keys standalone: test each configured API key and exit.
    if args.validate_keys:
        status = validate_api_keys()
        for source, st in status.items():
            logging.info("%-10s: %s", source, st.upper() if st == "invalid" else st)
        invalid = [s for s, st in status.items() if st == "invalid"]
        if invalid:
            logging.error("Invalid key(s): %s — fix them in [coverart] of %s",
                          ", ".join(invalid), CONFIG_FILE)
            return 1
        return 0

    # Parse --audio-langs into canonical keys early so errors surface before any work starts.
    audio_lang_filter: Optional[List[str]] = None
    if args.audio_langs:
        try:
            audio_lang_filter = parse_audio_lang_filter(args.audio_langs)
        except ValueError as e:
            logging.error("--audio-langs error: %s", e)
            return 2
        logging.info("Audio language filter: %s", [CFG.LANG_DISPLAY_MAP.get(c, c) for c in audio_lang_filter])

    # Parse --force-audio-lang / --force-sub-lang overrides
    force_audio_langs: Dict[int, str] = {}
    force_sub_langs: Dict[int, str] = {}
    try:
        force_audio_langs = parse_force_lang_overrides(args.force_audio_lang)
        force_sub_langs = parse_force_lang_overrides(args.force_sub_lang)
    except ValueError as e:
        logging.error("--force-audio-lang / --force-sub-lang error: %s", e)
        return 2
    if force_audio_langs:
        logging.info("Force audio lang overrides: %s", {k: CFG.LANG_DISPLAY_MAP.get(v, v) for k, v in force_audio_langs.items()})
    if force_sub_langs:
        logging.info("Force subtitle lang overrides: %s", {k: CFG.LANG_DISPLAY_MAP.get(v, v) for k, v in force_sub_langs.items()})

    if args.self_check:
        return self_check()

    if (args.only_movies or args.only_tv) and (args.movies or args.tv):
        logging.error("Invalid arguments: do not mix deprecated --only-* flags with --movies/--tv.")
        return 2
    if args.only_movies and args.only_tv:
        logging.error("Invalid arguments: cannot set both Movies-only and TV-only at the same time.")
        return 2

    # Resolve --input into per-pipeline roots
    input_override = Path(args.input) if args.input else None
    if input_override and not input_override.exists():
        logging.error("--input path does not exist: %s", input_override)
        return 2

    # Standalone modes are mutually exclusive.
    modes = [m for m, on in (("--cleantags", args.cleantags), ("--coverart", args.coverart),
                             ("--rename", args.rename), ("--subtitles", args.subtitles),
                             ("--rename-undo", args.rename_undo)) if on]
    if len(modes) > 1:
        logging.error("Invalid arguments: %s are separate modes; run them one at a time.", " and ".join(modes))
        return 2

    # --rename-undo needs nothing else — do it and exit.
    if args.rename_undo:
        return run_rename_undo()

    # mkvpropedit is needed for cleantags (standalone or auto after remux) and for --coverart.
    # Skip validation failure if mkvpropedit is absent and --skip-cleantags was set.
    need_propedit = (not args.skip_cleantags) or args.coverart
    try:
        validate_tools(need_propedit=need_propedit)
    except Exception as e:
        logging.error("Tool validation failed: %s", e)
        return 2

    # Soft key check at run start: a definitively invalid key (HTTP 401) would
    # otherwise fail once per file — disable that source up front instead.
    # Dry runs stay offline, so skip it there.
    if not args.dry_run and (CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY):
        disable_invalid_api_keys()

    # Determine which pipelines to run
    if args.movies or args.tv:
        do_movies = args.movies
        do_tv = args.tv
    else:
        if args.only_movies:
            do_movies, do_tv = True, False
        elif args.only_tv:
            do_movies, do_tv = False, True
        else:
            do_movies, do_tv = True, True

    # SAFETY: --input with both pipelines active would point Movies AND TV at the
    # same folder — every file would be processed twice, concurrently. Require an
    # explicit choice instead.
    if input_override and do_movies and do_tv:
        logging.error("--input requires exactly one of --movies or --tv "
                      "(otherwise every file in %s would be processed twice, once per pipeline).",
                      input_override)
        return 2

    # Resolve effective roots (--input overrides per pipeline)
    if input_override:
        movies_root = input_override if do_movies else CFG.MOVIES_ROOT
        tv_root     = input_override if do_tv     else CFG.TV_ROOT
    else:
        movies_root = CFG.MOVIES_ROOT
        tv_root     = CFG.TV_ROOT

    # --cleantags standalone: scan roots, clean tags in-place, then exit.
    if args.cleantags:
        ct_results = run_cleantags_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
            skip_filebot=False,  # always attempt FileBot rename in --cleantags mode
        )
        ok_ct  = sum(1 for r in ct_results if r.ok)
        bad_ct = sum(1 for r in ct_results if not r.ok)
        logging.info("cleantags summary: total=%d OK=%d failed=%d", len(ct_results), ok_ct, bad_ct)
        if bad_ct:
            for r in ct_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s", r.source_items[0].name if r.source_items else "?", r.reason)
        return 0 if bad_ct == 0 else 1

    # --rename standalone: FileBot-rename every MKV in scope, then exit.
    if args.rename:
        if do_movies == do_tv:
            logging.error("--rename requires exactly one of --movies or --tv "
                          "(the two use different databases and naming formats).")
            return 2
        is_tv_mode = do_tv
        scan_root = tv_root if is_tv_mode else movies_root
        rn_results = run_rename_pipeline(
            is_tv=is_tv_mode,
            scan_root=scan_root,
            rename_into=args.rename_into,
            dry_run=args.dry_run,
            workers=args.workers,
            force_audio_langs=force_audio_langs,
            force_sub_langs=force_sub_langs,
        )
        ok_rn = sum(1 for r in rn_results if r.ok)
        bad_rn = sum(1 for r in rn_results if not r.ok)
        renamed = sum(1 for r in rn_results if r.ok and r.details.get("new"))
        logging.info("rename summary: total=%d renamed=%d OK=%d failed=%d",
                     len(rn_results), renamed, ok_rn, bad_rn)
        if bad_rn:
            for r in rn_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        return 0 if bad_rn == 0 else 1

    # --subtitles standalone: download missing sidecar subs, then exit.
    if args.subtitles:
        st_results = run_subtitles_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
        )
        ok_st = sum(1 for r in st_results if r.ok)
        bad_st = sum(1 for r in st_results if not r.ok)
        covered = sum(1 for r in st_results if r.ok and r.reason == "already_covered")
        quota = sum(1 for r in st_results if not r.ok and r.reason == "quota_exhausted")
        logging.info("subtitles summary: total=%d OK=%d (already covered: %d) failed=%d (quota-blocked: %d)",
                     len(st_results), ok_st, covered, bad_st, quota)
        if bad_st:
            for r in st_results:
                if not r.ok and r.reason != "quota_exhausted":
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        return 0 if bad_st == 0 else 1

    # --coverart standalone: scan roots, embed cover art in-place, then exit.
    if args.coverart:
        ca_results = run_coverart_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
            overwrite_cover=args.coverart_overwrite,
        )
        ok_ca = sum(1 for r in ca_results if r.ok)
        bad_ca = sum(1 for r in ca_results if not r.ok)
        skipped_ca = sum(1 for r in ca_results if r.ok and r.reason == "already_has_cover")
        logging.info("coverart summary: total=%d OK=%d (already had cover: %d) failed=%d",
                     len(ca_results), ok_ca, skipped_ca, bad_ca)
        if bad_ca:
            for r in ca_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        return 0 if bad_ca == 0 else 1

    # Ensure work/output roots exist
    for d in (CFG.WORK_ROOT, CFG.OUTPUT_ROOT):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.error("Cannot access/create folder: %s | %s", d, e)
            return 3

    results: List[Result] = []
    started = time.time()

    # Movies: group per-folder then per similarity group
    movie_tasks: List[Tuple[List[Path], Path]] = []
    if do_movies:
        movies = scan_mkvs(movies_root)
        logging.info("Movies scan: %d MKV(s) found in %s.", len(movies), movies_root)
        by_folder = group_movies_by_folder(movies)
        for folder, mkvs in by_folder.items():
            groups = group_movies_in_folder(mkvs, threshold=args.similarity_threshold)
            for g in groups:
                movie_tasks.append((g, movies_root))

    # TV: per-file
    tv_files: List[Path] = []
    if do_tv:
        tv_files = scan_mkvs(tv_root)
        logging.info("TV scan: %d MKV(s) found in %s.", len(tv_files), tv_root)

    # Parallel execution
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs: List[concurrent.futures.Future] = []

        for g, root in movie_tasks:
            futs.append(ex.submit(
                process_movie_group, g, root, args.dry_run, args.overwrite,
                args.include_forced_subs, audio_lang_filter, args.skip_cleantags,
                force_audio_langs, force_sub_langs
            ))

        for f in tv_files:
            futs.append(ex.submit(
                process_tv_file, f, tv_root, args.dry_run, args.overwrite,
                args.include_forced_subs, audio_lang_filter, args.skip_cleantags,
                force_audio_langs, force_sub_langs
            ))

        for fut in concurrent.futures.as_completed(futs):
            try:
                res = fut.result()
            except Exception as e:
                logging.exception("Worker crashed: %s", e)
                res = Result(kind="unknown", source_items=[], output_path=None, ok=False, reason=f"Worker exception: {e}")
            results.append(res)

    # Prune any leftover empty directories in WORK_ROOT (catches partial previous runs)
    if not args.dry_run and CFG.WORK_ROOT.exists():
        for d in sorted(CFG.WORK_ROOT.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and d != CFG.WORK_ROOT:
                try:
                    d.rmdir()
                    logging.debug("Pruned empty work dir: %s", d)
                except OSError:
                    pass

    # Summary report
    elapsed = time.time() - started
    ok = sum(1 for r in results if r.ok)
    bad = sum(1 for r in results if not r.ok)

    logging.info("========== SUMMARY ==========")
    logging.info("Elapsed: %s", str(_dt.timedelta(seconds=int(elapsed))))
    logging.info("Total tasks: %d | OK: %d | Failed: %d", len(results), ok, bad)

    if bad:
        logging.info("Failures:")
        for r in results:
            if not r.ok:
                srcs = ", ".join(p.name for p in r.source_items) if r.source_items else "(none)"
                logging.info("- %s | %s | %s", r.kind, srcs, r.reason)

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())