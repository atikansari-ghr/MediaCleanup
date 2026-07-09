# MediaCleanup — Usage Guide

Full reference for running `MediaCleanup.py`. For configuration file details see [CONFIGURATION.md](CONFIGURATION.md).

---

## Setup

1. Install Python 3.11+ and [MKVToolNix](https://mkvtoolnix.download/).
2. Copy `MediaCleanup.example.toml` to `MediaCleanup.toml` (same folder as the script) and edit the paths.
3. Validate: `python MediaCleanup.py --self-check`

All folder locations (media roots, tool paths) live in `MediaCleanup.toml` — the script has no hardcoded paths.

**Recommended:** `pip install rich` — enables colored log levels and end-of-run summary tables (`File | Action | Status | Detail` with green OK / yellow SKIP / red FAIL). Without it the script runs identically with plain-text output.

---

## Quick reference

```bat
:: Full pipeline (Movies + TV)
python MediaCleanup.py
python MediaCleanup.py --dry-run --verbose

:: One pipeline only
python MediaCleanup.py --movies
python MediaCleanup.py --tv

:: Custom input folder
python MediaCleanup.py --movies --input "D:\Downloads\NewMovies"

:: Standalone modes (in-place, no remux)
python MediaCleanup.py --cleantags
python MediaCleanup.py --coverart

:: Language control
python MediaCleanup.py --movies --audio-langs Telugu Hindi
python MediaCleanup.py --tv --force-audio-lang 1 Hindi --force-sub-lang 3 English
```

---

## All flags

### Pipeline scope

| Flag | Meaning |
|---|---|
| `--movies` | Process the Movies pipeline only. Default (no flag): both. |
| `--tv` | Process the TV pipeline only. Default (no flag): both. |
| `--input PATH` | Override the scan root. **Requires exactly one of `--movies`/`--tv`** (safety: pointing both pipelines at one folder would process every file twice). Also scopes `--cleantags`, `--coverart`, `--rename`, and `--subtitles`. |

### Modes

| Flag | Meaning |
|---|---|
| *(none)* | Normal pipeline: group, select tracks, remux, tag-clean + metadata, FileBot rename, cover art. One run fully finishes each file. |
| `--cleantags` | Standalone: clean promotional/watermark tags in-place on every MKV in scope. No remux. When API keys are configured, also embeds rich metadata — see [Metadata tags](#metadata-tags) below. |
| `--coverart` | Standalone: fetch and embed cover art into every MKV in scope that doesn't have one. No remux. See [Cover art](#cover-art) below. |
| `--coverart-overwrite` | With `--coverart`: replace an existing embedded cover instead of skipping the file. |
| `--rename` | Standalone: FileBot-rename every MKV in scope into the canonical format. Requires exactly one of `--movies`/`--tv`. See [Renaming downloads](#renaming-downloads). |
| `--rename-into` | With `--rename`: move files into the library structure under the configured roots. |
| `--rename-undo` | Revert the most recent `--rename` batch, then exit. |
| `--subtitles` | Standalone: download missing subtitles from OpenSubtitles.com as sidecar `.srt` files. See [Subtitles](#subtitles). |
| `--validate-keys` | Test each configured API key (TMDB, fanart.tv, OMDb, OpenSubtitles) with one cheap call, print a verdict per source, exit (code 1 if any configured key is invalid). |
| `--no-fetch-tags` | Disable rich metadata tagging; tag cleaning reverts to basic (title + IMDB id only). |
| `--self-check` | Validate tool paths, folder access, and API keys; parse a sample MKV; exit. |

### Remux options

| Flag | Meaning |
|---|---|
| `--overwrite` | Overwrite existing output files. Default: fail the item if output exists. |
| `--inplace` | Remuxed output **replaces the source file(s)** in their own folder instead of going to `output_root`. The output is verified (track counts + duration) before any source is touched; multi-file merges consume **all** variants. |
| `--backup` | With `--inplace`: keep each consumed source as `<name>.original.mkv` next to the new file. Backups are invisible to all scans. Recovery: delete the new file, strip `.original` from the backup's name. |
| `--audio-langs LANG...` | Keep only a subset of your configured `[languages]` targets for this run (names or ISO codes, case-insensitive). Default: all targets when present. |
| `--force-audio-lang ID LANG` | Treat audio track `ID` as `LANG`, overriding the stored tag. For `und`/mislabeled tracks. Repeatable. Applies to **every** file in the run — scope with `--input`. |
| `--force-sub-lang ID LANG` | Same for subtitle tracks. |
| `--force-video-lang LANG` | Stamp the **video** track with this language instead of the title's TMDB original language. Accepts any supported language, not just targets. |
| `--skip-cleantags` | Disable the automatic tag-clean that runs after each remux. |
| `--skip-coverart` | Disable the automatic cover art embed at the end of the pipeline. |
| `--include-forced-subs` | Allow forced-flag subtitle selection. |
| `--similarity-threshold F` | Movie-grouping filename similarity (0–1, default 0.88). Lower = group more aggressively. |

### General

| Flag | Meaning |
|---|---|
| `--filter PATTERN` | Only process items matching a case-insensitive glob (`A*` ≡ `a*`), tested against the movie/show **folder name** and the **MKV filename** (either match includes the file). Repeatable: `--filter "A*" --filter "B*"`. Works in every mode. |
| `--dry-run` | Log all planned actions; write nothing. `--coverart` dry-run also stays fully offline. |
| `--verbose` | Debug logging (track decisions, full command lines). |
| `--workers N` | Parallel worker threads (default: CPU count − 1). |
| `--log-file PATH` | Also write the log to a file (always plain text). |
| `--no-color` | Disable colored output and summary tables (`NO_COLOR` env also honored). |

---

## Target languages

Which audio languages are kept (everything else is stripped during remux) is configured in `MediaCleanup.toml`:

```toml
[languages]
targets = ["hin", "eng", "tel"]     # the default — Hindi, English, Telugu
```

- **List order = audio track order** in the output file (and the `[...]` filename bracket).
- Accepts **every form**: ISO 639-1 (`"ko"`), ISO 639-2 bibliographic (`"kor"`) *and* terminological (`"fra"`), full English names (`"Korean"`), and common alternates (Farsi, Punjabi, Bangla…). The complete ISO 639 registry is built in (189 languages); BCP-47 track tags like `zh-Hans` are understood too.
- Detection, display names, subtitle keeping, and cover art poster-language preference all follow the configured targets automatically.
- **Video track language**: encoders usually leave it `und`; during tag cleaning the script sets it to the title's original language from TMDB (The Film → `eng`, RRR → `tel`). Override per run with `--force-video-lang`.

## Cover art

Cover art is embedded **automatically at the end of every pipeline run** (after the FileBot rename; disable with `--skip-coverart`). The standalone `--coverart` mode below is for backfills and redo work. Either way, a poster is embedded into each MKV as a `cover.jpg` attachment (the Matroska cover-art convention — shown by VLC, MPC-HC, Jellyfin, and Windows Explorer thumbnails). Attachments are edited in-place; media streams are never touched.

**Skip/redo logic (ledger):** every embed is recorded in `logs\coverart_done.csv`. On later runs, recorded files are skipped **instantly** (no probing, no API calls), so whole-library re-runs cost seconds. Files with a cover the script embedded earlier but missing from the ledger (renamed file, rebuilt ledger) are recognized by the "Cover art" attachment marker and re-recorded without re-downloading. Covers that **came with the release** are treated as junk and **replaced** by default. `--coverart-overwrite` ignores the ledger and re-fetches/re-embeds everything in scope — combine with `--filter`/`--input` to redo specific titles. Stale ledger rows (files that no longer exist) are pruned automatically.

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
python MediaCleanup.py --coverart

:: One show only
python MediaCleanup.py --coverart --tv --input "D:\Media\TV\Show Name (2008)"

:: Replace existing covers in a folder
python MediaCleanup.py --coverart --movies --input "D:\Media\Fixed" --coverart-overwrite

:: Preview (offline — no API calls)
python MediaCleanup.py --coverart --dry-run --verbose
```

To hand-pick art for one movie: drop a `poster.jpg` in its folder and run `--coverart` (with `--coverart-overwrite` if a cover is already embedded).

---

## Metadata tags

Whenever tag cleaning runs — the automatic pass after each remux **and** standalone `--cleantags` — the script fetches full metadata (TMDB primary, OMDb supplement) and embeds it as standard Matroska tags, provided API keys are configured. Disable with `--no-fetch-tags`; without keys (or offline/`--dry-run`) it silently falls back to basic tags (title + IMDB id).

**Movies** (tag level 50): `TITLE`, `DATE_RELEASED`, `GENRE`, `DIRECTOR`, `WRITTEN_BY`, `ACTOR` (top 10, each with nested `CHARACTER`), `DESCRIPTION` (tagline/short), `SYNOPSIS` (full plot), `LAW_RATING` (PG-13…), `RATING` (IMDB score), `IMDB`, `TMDB` — plus a collection tag (level 70) for franchise movies.

**TV** (three levels): show (70) — `TITLE`, `GENRE`, `NETWORK`, `LAW_RATING`, cast; season (60) — season title + number; episode (50) — episode title, number, `DATE_RELEASED` (airdate), `DIRECTOR`, `DESCRIPTION`/`SYNOPSIS`, `RATING`.

**Segment title** (the "main title" players display) stays clean — no technical suffixes:

```
Movies: The Film (2021)
TV:     Show Name (2006) - S01E23 - An Episode Title
```

A full season costs one show lookup + one season lookup total (cached per run), regardless of episode count.

```bat
:: Verify keys first
python MediaCleanup.py --validate-keys

:: Enrich an already-processed library
python MediaCleanup.py --cleantags --input "D:\Media\Fixed"

:: Clean tags the old way (offline, no metadata)
python MediaCleanup.py --cleantags --no-fetch-tags --input "D:\Media\Fixed"
```

> Note: Plex/Jellyfin scrape their own metadata and mostly ignore embedded tags. The payoff is in VLC/MPC-HC/Kodi and archival self-containment — the file carries its metadata forever, independent of any server.

---

## Renaming downloads

`--rename` fixes badly-named downloads via FileBot without remuxing or touching tags:

```bat
:: Preview (FileBot's test mode shows the actual proposed names)
python MediaCleanup.py --rename --movies --input "D:\Downloads" --dry-run

:: Rename in place
python MediaCleanup.py --rename --movies --input "D:\Downloads"

:: Rename AND organize into the library (Movies\Title (Year)\..., TV\Show\Season XX\...)
python MediaCleanup.py --rename --tv --input "D:\Downloads\Show.S01.Complete" --rename-into

:: Fix mislabeled 'und' audio first so the [language] bracket comes out right
python MediaCleanup.py --rename --tv --input "D:\Downloads\Show" --force-audio-lang 1 Hindi

:: Changed your mind? Revert the last batch
python MediaCleanup.py --rename-undo
```

Details: requires exactly one of `--movies`/`--tv` (different databases + formats); the DB lookup uses a cleaned title query so release junk in the filename doesn't mislead it; every rename is appended to `logs\rename_history.csv`; `--rename-undo` reverts the most recent batch (skipping files that moved since) and removes it from the history. Note the language bracket in the new name reflects the audio tags *inside* the file — fix `und` tracks with the force flags or the bracket may be wrong.

---

## Subtitles

`--subtitles` downloads missing subtitles from OpenSubtitles.com as **sidecar `.srt` files** — no remux, media streams untouched. Requires `api_key`, `username`, and `password` in the `[subtitles]` TOML section (free account ≈ 20 downloads/day, VIP ≈ 1000/day; the log shows your remaining quota after each download and the run stops gracefully when it's exhausted).

- **Naming**: single configured language → exact MKV stem + `.srt` (`The Film (2021) - tt1234567 - ... - [Hindi + English + Telugu].srt`). Extra languages get a suffix: `.hin.srt`, `.tel.srt`.
- **Languages**: `[subtitles] languages = ["en"]` (ISO 639-1; English is the default).
- **Skips** files already covered — embedded subtitle track in the wanted language OR an existing sidecar.
- **Matching**: file hash (identifies the exact release — best sync) + IMDB ID, ranked by hash-match → trusted uploader → download count.

```bat
:: See what's missing (offline, no quota spent)
python MediaCleanup.py --subtitles --dry-run

:: Download for one show
python MediaCleanup.py --subtitles --tv --input "D:\Media\TV\Show Name (2006)"

:: Whole library
python MediaCleanup.py --subtitles
```

---

## Handling "und" (undefined language) tracks

Hindi-dubbed releases often tag audio as `und` with a generic name like "2 channels". The script can't identify these automatically — tell it explicitly:

```bat
:: Step 1 — inspect track IDs (video=0, first audio=1, ...)
runtimes\mkvtoolnix\mkvmerge.exe -J "D:\Media\TV\Show\episode.mkv"

:: Step 2 — dry-run with the override
python MediaCleanup.py --tv --input "D:\Media\TV\Show" --force-audio-lang 1 Hindi --dry-run --verbose

:: Step 3 — apply
python MediaCleanup.py --tv --input "D:\Media\TV\Show" --force-audio-lang 1 Hindi
```

The override applies to every file in the scanned folder, and the corrected language tag is written into the MKV via mkvpropedit.

---

## Common recipes

```bat
:: Process a new movie dropped in Downloads
python MediaCleanup.py --movies --input "D:\Downloads"

:: Keep only Telugu and Hindi audio (drop English)
python MediaCleanup.py --movies --audio-langs Telugu Hindi

:: Re-clean tags on already-processed files (no remux)
python MediaCleanup.py --cleantags --movies --input "D:\Media\Fixed"

:: Add cover art to everything processed so far
python MediaCleanup.py --coverart --input "D:\Media\Fixed"

:: Fix "und" audio + subtitle across a season
python MediaCleanup.py --tv --input "D:\Media\TV\Show Season 1" --force-audio-lang 1 Hindi --force-sub-lang 2 English

:: Loose grouping when variant filenames differ a lot
python MediaCleanup.py --movies --similarity-threshold 0.80

:: Full run, verbose, logged to file
python MediaCleanup.py --verbose --log-file "logs\run.log"
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

**FileBot fails with "Unable to establish loopback connection"**
FileBot's Java runtime creates internal sockets in the `TEMP` directory, which has a ~108-character path limit. If your `TEMP`/`TMP` environment variable points at a very long path, every FileBot lookup fails with this error. Fix: point `TEMP` at a short path for the session (`set TEMP=C:\Windows\Temp`) or permanently in Windows settings.

**mkvpropedit warnings (rc=1)**
Non-fatal — mkvpropedit exits 1 when a property being deleted doesn't exist. Changes still apply.

**Resolution tag looks wrong (e.g. 720p on a 480p file)**
Resolution is inferred from video width, snapped to the nearest of 3840/1920/1280. Run `--verbose` to see the dimensions mkvmerge reports.

**Where did the ToFix folder go?**
Remuxing now reads sources directly (mkvmerge never modifies its inputs) — the working-copy mirror was removed, halving remux I/O and disk usage. `work_root` in old configs is accepted but ignored.
