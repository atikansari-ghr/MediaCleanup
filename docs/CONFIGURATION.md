# MediaCleanup Enhanced — Configuration Reference

All configuration lives in **`MediaCleanup.toml`**, which must sit in the same folder as `MediaCleanup_Enhanced.py`. The script resolves it relative to its own location, so it works no matter which directory you run from.

Setup: `copy MediaCleanup.example.toml MediaCleanup.toml`, then edit.

> `MediaCleanup.toml` is git-ignored because it contains your private API keys and machine-specific paths. Never commit it; share `MediaCleanup.example.toml` instead.

TOML tip: use **single-quoted literal strings** for Windows paths — backslashes need no escaping: `movies_root = 'D:\Media\Movies'`.

---

## `[tools]`

| Key | Required | Description |
|---|---|---|
| `mkvtoolnix_dir` | **Yes** | Folder containing the MKVToolNix binaries. Download: <https://mkvtoolnix.download/> |
| `mkvmerge` | No | Override path to `mkvmerge.exe`. Default: `<mkvtoolnix_dir>\mkvmerge.exe` |
| `mkvpropedit` | No | Override path to `mkvpropedit.exe`. Default: `<mkvtoolnix_dir>\mkvpropedit.exe` |
| `mkvinfo` | No | Override path to `mkvinfo.exe`. Default: `<mkvtoolnix_dir>\mkvinfo.exe` |
| `mkvextract` | No | Override path to `mkvextract.exe`. Default: `<mkvtoolnix_dir>\mkvextract.exe`. Used to read IMDB IDs from existing MKV tags. |

`mkvmerge` and `mkvpropedit` must exist for the main pipeline. `mkvpropedit` is also required for `--cleantags` and `--coverart` (validation is skipped only when `--skip-cleantags` is set and `--coverart` is not used).

## `[filebot]`

| Key | Required | Description |
|---|---|---|
| `exe` | No | Path to `filebot.exe`. If omitted or nonexistent, all FileBot steps are skipped and the script uses its built-in filename heuristics. |
| `db` | No | Movie database for FileBot lookups. Default: `"TheMovieDB"`. TV always uses TheTVDB. |

## `[paths]`

All four are **required**.

| Key | Description |
|---|---|
| `movies_root` | Source movies folder, scanned recursively for `.mkv`. |
| `tv_root` | Source TV folder, scanned recursively. |
| `work_root` | Working-copy folder. Sources are mirrored here before remuxing; copies are auto-deleted after success. Needs free space ≥ the largest movie group being processed. |
| `output_root` | Output folder. Remuxed files land here, mirroring the source folder structure. |

The `--input` CLI flag overrides `movies_root`/`tv_root` for a single run without editing the TOML.

## `[coverart]`

API keys used by **both** `--coverart` (poster fetching) and rich metadata tagging (genre/director/actors/synopsis embedded during tag cleaning). All keys optional — an empty value disables that source. With no keys at all, `--coverart` still works using local poster files only, and tag cleaning writes basic tags.

Verify your keys anytime with `python MediaCleanup_Enhanced.py --validate-keys`.

> Watch the key formats: TMDB and fanart.tv keys are 32 hex characters; OMDb keys are 8. If validation says a key is invalid, check you didn't swap them.

| Key | Description |
|---|---|
| `tmdb_api_key` | TMDB API key (v3 auth). Free signup: <https://www.themoviedb.org/settings/api>. **Primary source** — best coverage, especially for Indian/regional cinema; serves pre-sized 780×1170 posters. |
| `fanarttv_api_key` | fanart.tv project key: <https://fanart.tv/get-an-api-key/>. Curated high-quality art; first fallback. TV lookups require `tmdb_api_key` too (TMDB translates to the TVDB ID fanart.tv uses). |
| `omdb_api_key` | OMDb key (free tier 1,000 req/day): <https://www.omdbapi.com/apikey.aspx>. Last resort — returns a ~300px poster. |

## `[subtitles]`

Credentials for the `--subtitles` mode (OpenSubtitles.com REST API). All three credentials are required for downloads; without them the mode refuses to run (dry-run works regardless).

| Key | Description |
|---|---|
| `api_key` | OpenSubtitles API key — register a consumer at <https://www.opensubtitles.com/en/consumers>. |
| `username` / `password` | Your opensubtitles.com account login (downloads are per-user; free ≈ 20/day, VIP ≈ 1000/day). |
| `languages` | List of ISO 639-1 codes to download, default `["en"]`. One language → sidecar named `<mkv stem>.srt`; extra languages get `.hin.srt`-style suffixes. |

---

## What stays in the script

Behavioral constants are deliberately **not** in the TOML — they define what the tool *is*, and changing them means changing the spec (see [PROMPT.md](PROMPT.md)):

- Target languages (Hindi, English, Telugu) and their detection tokens
- Video/audio/subtitle codec preference rankings
- Resolution targets (2160p/1080p/720p)
- Audio-exclusion tokens (commentary, descriptive, ...)
- Output naming formats and FileBot format strings
- Default similarity threshold (0.88 — overridable per run via `--similarity-threshold`)
