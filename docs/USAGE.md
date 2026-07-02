# MediaCleanup Enhanced — Usage Guide

Full reference for running `MediaCleanup_Enhanced.py`. For configuration file details see [CONFIGURATION.md](CONFIGURATION.md); for the underlying processing rules see [PROMPT.md](PROMPT.md).

---

## Setup

1. Install Python 3.11+ and [MKVToolNix](https://mkvtoolnix.download/).
2. Copy `MediaCleanup.example.toml` to `MediaCleanup.toml` (same folder as the script) and edit the paths.
3. Validate: `python MediaCleanup_Enhanced.py --self-check`

All folder locations (media roots, tool paths) live in `MediaCleanup.toml` — the script has no hardcoded paths.

---

## Quick reference

```bat
:: Full pipeline (Movies + TV)
python MediaCleanup_Enhanced.py
python MediaCleanup_Enhanced.py --dry-run --verbose

:: One pipeline only
python MediaCleanup_Enhanced.py --movies
python MediaCleanup_Enhanced.py --tv

:: Custom input folder
python MediaCleanup_Enhanced.py --movies --input "D:\Downloads\NewMovies"

:: Standalone modes (in-place, no remux)
python MediaCleanup_Enhanced.py --cleantags
python MediaCleanup_Enhanced.py --coverart

:: Language control
python MediaCleanup_Enhanced.py --movies --audio-langs Telugu Hindi
python MediaCleanup_Enhanced.py --tv --force-audio-lang 1 Hindi --force-sub-lang 3 English
```

---

## All flags

### Pipeline scope

| Flag | Meaning |
|---|---|
| `--movies` | Process the Movies pipeline only. Default (no flag): both. |
| `--tv` | Process the TV pipeline only. Default (no flag): both. |
| `--input PATH` | Override the scan root. With `--movies` replaces the movies root; with `--tv` the TV root; with both/neither, applies to both. Also scopes `--cleantags` and `--coverart`. |

### Modes

| Flag | Meaning |
|---|---|
| *(none)* | Normal pipeline: group, select tracks, remux, tag-clean, rename. |
| `--cleantags` | Standalone: clean promotional/watermark tags in-place on every MKV in scope. No remux. |
| `--coverart` | Standalone: fetch and embed cover art into every MKV in scope that doesn't have one. No remux. See [Cover art](#cover-art) below. |
| `--coverart-overwrite` | With `--coverart`: replace an existing embedded cover instead of skipping the file. |
| `--self-check` | Validate tool paths and folder access, parse a sample MKV, exit. |

### Remux options

| Flag | Meaning |
|---|---|
| `--overwrite` | Overwrite existing output files. Default: fail the item if output exists. |
| `--audio-langs LANG...` | Keep only these languages. Accepted: `Telugu/tel/te`, `Hindi/hin/hi`, `English/eng/en` (case-insensitive). Default: all three when present. |
| `--force-audio-lang ID LANG` | Treat audio track `ID` as `LANG`, overriding the stored tag. For `und`/mislabeled tracks. Repeatable. Applies to **every** file in the run — scope with `--input`. |
| `--force-sub-lang ID LANG` | Same for subtitle tracks. |
| `--skip-cleantags` | Disable the automatic tag-clean that runs after each remux. |
| `--include-forced-subs` | Allow forced-flag subtitle selection. |
| `--similarity-threshold F` | Movie-grouping filename similarity (0–1, default 0.88). Lower = group more aggressively. |

### General

| Flag | Meaning |
|---|---|
| `--dry-run` | Log all planned actions; write nothing. `--coverart` dry-run also stays fully offline. |
| `--verbose` | Debug logging (track decisions, full command lines). |
| `--workers N` | Parallel worker threads (default: CPU count − 1). |
| `--log-file PATH` | Also write the log to a file. |

---

## Cover art

`--coverart` embeds a poster into each MKV as a `cover.jpg` attachment (the Matroska cover-art convention — shown by VLC, MPC-HC, Jellyfin, and Windows Explorer thumbnails). It edits attachments in-place; media streams are never touched.

**Source chain** (first hit wins):

1. **Local file** — `poster.jpg`/`cover.jpg`/`folder.jpg` (also `.jpeg`/`.png`) next to the MKV. For TV, the season folder and the show folder above it are both checked. A local poster applies to *every* MKV in that folder.
2. **TMDB** — looked up by IMDB ID from the filename/folder/MKV tags, falling back to a title+year search.
3. **fanart.tv** — by IMDB/TMDB ID.
4. **OMDb** — last resort (~300px image).

API keys go in the `[coverart]` section of `MediaCleanup.toml`. Missing keys simply disable that source; with no keys at all, only local files are used.

**Poster language:** English is always preferred. If no English poster exists, the file's own audio languages (Hindi/Telugu) are tried next, then textless posters.

**TV:** every episode gets the **show** poster (not episode stills). It's downloaded once per series per run and reused.

**Verification (automatic):** every run creates `logs\coverart_review\<timestamp>\` next to the script, containing a copy of each embedded poster **named after its MKV**, plus `coverart_report.html` — open it in a browser to visually verify the matches. Failures are listed at the top of the report; a wrong poster is fixed by dropping the correct `poster.jpg` into that movie's folder and re-running with `--coverart-overwrite` (scope it with `--input`). The review folder is an audit copy only — deleting it changes nothing in your MKVs.

```bat
:: Backfill the whole library (skips files that already have covers)
python MediaCleanup_Enhanced.py --coverart

:: One show only
python MediaCleanup_Enhanced.py --coverart --tv --input "D:\Media\TV\Show Name (2008)"

:: Replace existing covers in a folder
python MediaCleanup_Enhanced.py --coverart --movies --input "D:\Media\Fixed" --coverart-overwrite

:: Preview (offline — no API calls)
python MediaCleanup_Enhanced.py --coverart --dry-run --verbose
```

To hand-pick art for one movie: drop a `poster.jpg` in its folder and run `--coverart` (with `--coverart-overwrite` if a cover is already embedded).

---

## Handling "und" (undefined language) tracks

Hindi-dubbed releases often tag audio as `und` with a generic name like "2 channels". The script can't identify these automatically — tell it explicitly:

```bat
:: Step 1 — inspect track IDs (video=0, first audio=1, ...)
runtimes\mkvtoolnix\mkvmerge.exe -J "D:\Media\TV\Show\episode.mkv"

:: Step 2 — dry-run with the override
python MediaCleanup_Enhanced.py --tv --input "D:\Media\TV\Show" --force-audio-lang 1 Hindi --dry-run --verbose

:: Step 3 — apply
python MediaCleanup_Enhanced.py --tv --input "D:\Media\TV\Show" --force-audio-lang 1 Hindi
```

The override applies to every file in the scanned folder, and the corrected language tag is written into the MKV via mkvpropedit.

---

## Common recipes

```bat
:: Process a new movie dropped in Downloads
python MediaCleanup_Enhanced.py --movies --input "D:\Downloads"

:: Keep only Telugu and Hindi audio (drop English)
python MediaCleanup_Enhanced.py --movies --audio-langs Telugu Hindi

:: Re-clean tags on already-processed files (no remux)
python MediaCleanup_Enhanced.py --cleantags --movies --input "D:\Media\Fixed"

:: Add cover art to everything processed so far
python MediaCleanup_Enhanced.py --coverart --input "D:\Media\Fixed"

:: Fix "und" audio + subtitle across a season
python MediaCleanup_Enhanced.py --tv --input "D:\Media\TV\Show Season 1" --force-audio-lang 1 Hindi --force-sub-lang 2 English

:: Loose grouping when variant filenames differ a lot
python MediaCleanup_Enhanced.py --movies --similarity-threshold 0.80

:: Full run, verbose, logged to file
python MediaCleanup_Enhanced.py --verbose --log-file "logs\run.log"
```

---

## Troubleshooting

**"Config file not found" / "Missing required key"**
Copy `MediaCleanup.example.toml` to `MediaCleanup.toml` and fill in the `[tools]` and `[paths]` sections. The file must sit in the same folder as the script.

**"Missing MKVToolNix binary"**
Check `mkvtoolnix_dir` in `MediaCleanup.toml` — `mkvmerge.exe` and `mkvpropedit.exe` must exist there.

**Audio track dropped / not in output**
Run `--verbose --dry-run` and look for `Skipping audio track` lines. If the track is `lang=und` with no recognizable name, use `--force-audio-lang`.

**Files not grouped for merge**
Lower `--similarity-threshold` to 0.80 or 0.75. `--verbose --dry-run` shows the normalized names and similarity ratios.

**Cover art not found for a title**
Check the log for the lookup details (`[DRY]` run shows title/IMDB ID/languages used). If the online sources miss it, drop a `poster.jpg` in the folder and re-run.

**Cover not showing in a player**
The cover is a standard Matroska attachment named `cover.jpg`. Some players cache thumbnails — refresh the library. Verify it's embedded: `mkvmerge.exe -J file.mkv` → `attachments`.

**FileBot not renaming**
FileBot is optional. If its bundled JRE is missing/corrupt, the script auto-disables it for the run and falls back to heuristic naming. Check `[filebot] exe` in the TOML.

**mkvpropedit warnings (rc=1)**
Non-fatal — mkvpropedit exits 1 when a property being deleted doesn't exist. Changes still apply.

**Resolution tag looks wrong (e.g. 720p on a 480p file)**
Resolution is inferred from video width, snapped to the nearest of 3840/1920/1280. Run `--verbose` to see the dimensions mkvmerge reports.

**ToFix (work) folder not cleaned up**
Working copies are only deleted after a successful output. Files from failed runs remain for inspection; re-run (with `--overwrite` if needed) and they'll be cleaned on success.
