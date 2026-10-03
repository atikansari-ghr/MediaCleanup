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
| `--cleantags` | Standalone: clean promotional/advertising tags in-place on every MKV in scope. No remux. When API keys are configured, also embeds rich metadata — see [Metadata tags](#metadata-tags) below. |
| `--coverart` | Standalone: fetch and embed cover art into every MKV in scope that doesn't have one. No remux. See [Cover art](#cover-art) below. |
| `--cleanmetadata` | Standalone: `--cleantags` and `--coverart` in one command — clean tags, embed metadata, rename in place, then embed cover art on the final filenames. No remux. See [Cleaning tags and cover art together](#cleaning-tags-and-cover-art-together). |
| `--coverart-overwrite` | With `--coverart`: replace an existing embedded cover instead of skipping the file. |
| `--clear` | Removal modifier. With `--cleantags`: wipe **all** tags, the segment title and every track name, writing nothing back (offline). With `--coverart`: delete embedded cover art and forget the file in the ledger so a later run re-fetches it. With `--cleanmetadata`: both at once, and never a rename. |
| `--rename` | Standalone: FileBot-rename every MKV in scope into the canonical format. Requires exactly one of `--movies`/`--tv`. See [Renaming messy filenames](#renaming-messy-filenames). |
| `--rename-into` | With `--rename`: move files into the library structure under the configured roots. |
| `--rename-undo` | Revert the most recent `--rename` batch, then exit. |
| `--subtitles` | Standalone: download missing subtitles from OpenSubtitles.com as sidecar `.srt` files. See [Subtitles](#subtitles). |
| `--mp4tomkv` | Standalone: remux MP4/M4V (plus any sidecar `.srt`) into MKV beside the source, then finish it completely. Sources are never modified or deleted. See [Converting MP4 to MKV](#converting-mp4-to-mkv). |
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
| `--pick N [N …]` | Identify films or TV shows by the numbers shown in the previous run's candidate list, e.g. `--pick 1 3`. One number per title; movies and shows can be mixed in one command. |
| `--imdb ttNNNNNNN` | Identify the film in scope as this IMDB id, when the title is too ambiguous to resolve. Requires `--filter` or `--input` so it applies to one film. The id is written into the file's tags, so it is only ever needed once. |
| `--no-lang-detect` | Do not try to identify tracks tagged `und` (see [Releases with no language tags](#releases-with-no-language-tags)). Config equivalent: `[languages] detect_undetermined = false`. |
| `--skip-cleantags` | Disable the automatic tag-clean that runs after each remux. |
| `--skip-coverart` | Disable the automatic cover art embed at the end of the pipeline. |
| `--include-forced-subs` | Allow forced-flag subtitle selection. |
| `--similarity-threshold F` | Movie-grouping filename similarity (0–1, default 0.88). Lower = group more aggressively. |

### General

| Flag | Meaning |
|---|---|
| `--filter PATTERN` | Only process items matching a case-insensitive glob (`A*` ≡ `a*`), tested against the movie/show **folder name** and the **MKV filename** (either match includes the file). Repeatable: `--filter "A*" --filter "B*"`. Works in every mode. |
| `--dry-run` | Log all planned actions; write nothing. Shows the **predicted final filename** for every item (see below). `--coverart` dry-run stays fully offline. |
| `--preview-exact` | With `--dry-run`: ask FileBot itself for each predicted name instead of predicting it from the database. Authoritative but much slower — one FileBot launch per item. |
| `--verbose` | Debug logging (track decisions, full command lines). |
| `--workers N` | Parallel worker threads (default: CPU count − 1). |
| `--log-file PATH` | Also write the log to a file (always plain text). |
| `--no-color` | Disable colored output and summary tables (`NO_COLOR` env also honored). |

---

## Previewing a run

`--dry-run` reports, for every file, the name it would end up with **after** the database rename — not the intermediate remux target:

```
[DRY] Final name would be: Night of the Living Dead (1968) - tt0063350 - WEB-DL.1080p.x264 - [Hindi + English].mkv
```

The prediction resolves the canonical title and IMDB id through TMDB (cached, one cheap call per title); resolution, codec, source tag and languages are computed from the files themselves. It covers the skip-remux path too, so files that are only renamed also show their new name.

`--preview-exact` instead asks FileBot for each name — the same tool that performs the real rename. It is authoritative but launches a JVM per item (roughly 4 s vs 1 s in testing), so it suits spot-checking a few titles rather than sweeping a library:

```bat
python MediaCleanup.py --dry-run --movies --filter "Night*" --preview-exact
```

The resolution tag is computed by this script and substituted into FileBot's format, so the preview and the rename always agree on it. A frame is named for its **height** whenever that height is standard — an ultra-wide 2582x1080 scope encode is `1080p`, because it has exactly 1080 rows — and for its width class only when the height is non-standard because the frame is letterboxed (1920x804 is `1080p`, not `720p`). Coded padding is absorbed, so a 1088-row stored frame is still `1080p`. Even so, a preview remains an estimate: the database is consulted again at run time. `--no-fetch-tags` disables prediction and falls back to the heuristic name.

## Target languages

Which audio languages are kept (everything else is stripped during remux) is configured in `MediaCleanup.toml`:

```toml
[languages]
targets = ["hin", "eng", "tel"]     # the default — Hindi, English, Telugu
```

- **List order = audio track order** in the output file (and the `[...]` filename bracket).
- Accepts **every form**: ISO 639-1 (`"ko"`), ISO 639-2 bibliographic (`"kor"`) *and* terminological (`"fra"`), full English names (`"Korean"`), and common alternates (Farsi, Punjabi, Bangla…). The complete ISO 639 registry is built in (189 languages); BCP-47 track tags like `zh-Hans` are understood too.
- Detection, display names, subtitle keeping, and cover art poster-language preference all follow the configured targets automatically.
- **Video track language**: encoders usually leave it `und`; during tag cleaning the script sets it to the title's original language from TMDB. Override per run with `--force-video-lang`.

## Releases with no language tags

Some releases arrive with **every** track tagged `und` — no language field, no BCP-47 tag, no track name. There is nothing to match against, so such a file looks like it contains none of your target languages and gets reported `NoAudioMatch`, even when the audio is in a language you keep.

Rather than guess from track order, the script works out what those tracks actually are (on by default; `--no-lang-detect`, or `detect_undetermined = false`, turns it off):

- **Audio** — a release stripped of metadata still carries the original audio, so a **single** unlabelled audio track takes the title's original language from TMDB. With two or more unlabelled audio tracks there is no way to tell which is which: they stay `und`, and `--force-audio-lang` remains the answer. When the title cannot be resolved to a specific year, no lookup is made at all — an unconstrained search returns whatever is most popular under that name, whose language is not necessarily this title's.
- **Subtitles** — text tracks (SRT/ASS/SSA/WebVTT) are identified from **their own text**. Writing system settles most languages outright (Hangul, Thai, Hebrew, Greek, Tamil, Telugu, kana, Han…); the ones that share an alphabet are separated by function-word frequency, with near-exclusive letters as a tiebreak for close pairs like Czech/Slovak and Danish/Norwegian. Image subtitles (PGS/VobSub) carry no text and are skipped.

Anything that cannot be called confidently keeps its `und` tag — a wrong language tag is worse than an honest unknown. Detected languages are written into the file, so the tracks are labelled correctly in Plex/Jellyfin whether the file is remuxed or finished in place.

A real example — a release with one `und` audio track and 42 `und` subtitle tracks:

```
Audio track 1 ... is unlabelled — Show Name is in English per TMDB, using that.
Identified 42 of 42 unlabelled subtitle tracks: 2=English(0.795), 3=English(0.795),
  4=Arabic(0.994), 5=Bulgarian(0.445), ... 22=Korean(1.0), 36=Telugu(1.0), 41=Chinese(1.0)
[DRY] Final name would be: Show Name (2026) - S01E03 - An Episode Title - 1080p.x265 - [English].mkv
```

The number after each language is confidence: `1.0` means the writing system alone was decisive.

## Converting MP4 to MKV

MP4 has no Matroska tags and normally leaves every track `und`, so those files cannot be tagged, language-labelled or given cover art. `--mp4tomkv` fixes that in one command:

```bash
python MediaCleanup.py --mp4tomkv --movies
```

Each `.mp4`/`.m4v` is remuxed with `mkvmerge` — **lossless, never re-encoded** — into an `.mkv` beside it, then handed to the ordinary finishing chain: tag cleaning, TMDB/OMDb metadata, language resolution, cover art, database rename.

```
Some.Film.2026.1080p.WEBRip.x264-GRP.mp4  +  Some.Film.2026.1080p.WEBRip.x264-GRP.srt
      -> Some Film (2026) - tt1234567 - WEBRip.1080p.x264 - [English].mkv
```

**Your source files are never touched.** The `.mp4` and `.srt` stay exactly where they were, whatever else happens — `--inplace` does not apply here. A ledger (`logs\mp4tomkv_done.csv`) records what has been converted so re-runs skip it; `--overwrite` ignores the ledger and redoes the work.

**Sidecar subtitles.** Any `.srt` whose name matches the video's (`<stem>.srt`, `<stem>.<tag>.srt`) is muxed in. Three things happen to it first:

- **Advertising is removed.** Some subtitles open or close with promotional cues that play over the film rather than translating it. A cue is treated as an advert when its text is structurally one — a web address, or stock phrasing such as "downloaded from" or "please visit" — and only when it falls in the first or last minute, so a line of dialogue that mentions a web address mid-film survives. Site names are not built in: whatever you list in `[naming] strip_prefixes` is matched too, the same list used to strip those names from filenames. Every removal is logged.
- **Forced tracks are flagged.** A subtitle carrying fewer than two cues a minute translates foreign dialogue rather than everything. It gets the forced flag, so players show it automatically over untranslated speech — and it is kept even though forced tracks are normally excluded, since dropping a film's only subtitle helps nobody.
- **The language is read from the text itself** (see [Releases with no language tags](#releases-with-no-language-tags)), because sidecar files rarely say what language they are.

**Languages**, since MP4 supplies none: a lone audio track and the video track take the title's TMDB original language; the subtitle is identified from its own text.

**Chapters are kept** — they are real navigation data — but any chapter *name* that advertises is rewritten to a plain `Chapter NN`.

This is the one place the tool edits stream content rather than metadata alone, a deliberate exception to the safety model in [Safety](#safety-model) made so that advertising cannot be welded permanently into your library.

## Cleaning tags and cover art together

`--cleanmetadata` is `--cleantags` followed by `--coverart`, as one command and without remuxing:

```bash
python MediaCleanup.py --cleanmetadata --movies
python MediaCleanup.py --cleanmetadata --tv --filter "Show*"
```

It is the finishing half of the main `--movies`/`--tv` pipeline for files that need no track changes: tags cleaned, metadata embedded, the file renamed in place, and a poster embedded under the final name. `--filter`, `--input`, `--dry-run` and `--coverart-overwrite` all apply, and the old `--cleantags` and `--coverart` modes are unchanged.

**Order matters, so the second step is handed the first step's files.** `--cleantags` may rename a file, and a `--filter` written for the old name (`Some.Film.2026.*`) would no longer match the new one (`Some Film (2026) - …`). The cover art step therefore processes exactly the files cleantags produced instead of rescanning, so a rename can never cause a file to be skipped.

**A film that cannot be identified gets no poster.** When more than one film shares a title and year, cleantags leaves the file unrenamed (see [A film left unrenamed](#troubleshooting)) and the cover step skips it too: a poster chosen by title alone would be whichever film the database ranked first, which is as wrong as a wrong rename. Pick the film with `--pick`, run again, and it gets its tags, name and poster together.

**`--clear` undoes both and never renames.** `--cleanmetadata --clear` wipes every tag, the segment title and all track names, and removes the embedded cover art and its ledger entry, leaving the file bare under its current name. It is offline — no database lookups. Add `--dry-run` to see what would be removed first.

## Cover art

Cover art is embedded **automatically at the end of every pipeline run** (after the FileBot rename; disable with `--skip-coverart`). The standalone `--coverart` mode below is for backfills and redo work. Either way, a poster is embedded into each MKV as a `cover.jpg` attachment (the Matroska cover-art convention — shown by VLC, MPC-HC, Jellyfin, and Windows Explorer thumbnails). Attachments are edited in-place; media streams are never touched.

**Skip/redo logic (ledger):** every embed is recorded in `logs\coverart_done.csv`. On later runs, recorded files are skipped **instantly** (no probing, no API calls), so whole-library re-runs cost seconds. Files with a cover the script embedded earlier but missing from the ledger (renamed file, rebuilt ledger) are recognized by the "Cover art" attachment marker and re-recorded without re-downloading. Covers that **came with the release** are treated as junk and **replaced** by default. `--coverart-overwrite` ignores the ledger and re-fetches/re-embeds everything in scope — combine with `--filter`/`--input` to redo specific titles. Stale ledger rows (files that no longer exist) are pruned automatically.

**Source chain** (first hit wins):

1. **Local file** — `poster.jpg`/`cover.jpg`/`folder.jpg` (also `.jpeg`/`.png`) next to the MKV. For TV, the season folder and the show folder above it are both checked. A local poster applies to *every* MKV in that folder.
2. **TMDB** — looked up by IMDB ID from the filename/folder/MKV tags, falling back to a title+year search.
3. **fanart.tv** — by IMDB/TMDB ID.
4. **OMDb** — last resort (~300px image).

API keys go in the `[coverart]` section of `MediaCleanup.toml`. Missing keys simply disable that source; with no keys at all, only local files are used.

**Films that cannot be identified.** A poster is only embedded for a film that has been pinned to one IMDB id — read from the filename, folder or tags, or resolved by the same check the rename uses. When several films share a title and a year, a title search would simply return whichever the database ranks first, so the file is **left exactly as it is**: nothing is embedded, a cover it already has is not replaced, and nothing is recorded in the ledger. It shows as a skip, with the numbered candidates listed so you can choose one and run again:

```bash
python MediaCleanup.py --coverart --pick 2
```

**Shows follow the same rule, for the rename as well.** A series is identified before its episodes are renamed, and FileBot is handed the series by id rather than searching for it, so it cannot land on a similarly named show. When more than one series shares the exact title the file is left unrenamed, reported `PARTIAL` with its candidates, and `--pick` resolves it. A show TMDB does not know is looked up on TheTVDB by name and year only; if that finds nothing the file keeps its name and is reported as not renamed, never given another show's.

**Shows follow the same rule.** The series is identified by an **exact title match, ignoring the year** — a renewed show's filename carries the year *that season* aired, not the year it debuted, so a year-strict lookup would find nothing for it. One match is used; more than one is never guessed between: the file is left as it is and the candidates are listed (with the language each was made in and its origin country) for `--pick`. The same pick settles the show's language, metadata and poster together.

A film that is identified but has no poster in any source is left untouched in the same way. A local `poster.jpg` next to the file always wins, because that is an explicit choice. A `--dry-run` stays fully offline, so it cannot say in advance which films will be skipped.

**Poster language:** English is always preferred. If no English poster exists, the file's own audio languages (Hindi/Telugu) are tried next, then textless posters.

**TV:** every episode gets the **show** poster (not episode stills). It's downloaded once per series per run and reused.

**Verification (automatic):** every run creates `logs\coverart_review\<timestamp>\` next to the script, containing a copy of each embedded poster **named after its MKV**, plus `coverart_report.html` — open it in a browser to visually verify the matches. Failures are listed at the top of the report; a wrong poster is fixed by dropping the correct `poster.jpg` into that movie's folder and re-running with `--coverart-overwrite` (scope it with `--input`). The review folder is an audit copy only — deleting it changes nothing in your MKVs.

```bat
:: Backfill the whole library (skips files that already have covers)
python MediaCleanup.py --coverart

:: One show only
python MediaCleanup.py --coverart --tv --input "D:\Media\TV\Show Name (2019)"

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
Movies: Night of the Living Dead (1968)
TV:     Show Name (2019) - S01E23 - Episode Title
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

## Renaming messy filenames

`--rename` fixes badly-named files via FileBot without remuxing or touching tags:

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

Details: requires exactly one of `--movies`/`--tv` (different databases + formats); the DB lookup uses a cleaned title query so filename noise doesn't mislead it; every rename is appended to `logs\rename_history.csv`; `--rename-undo` reverts the most recent batch (skipping files that moved since) and removes it from the history. Note the language bracket in the new name reflects the audio tags *inside* the file — fix `und` tracks with the force flags or the bracket may be wrong.

---

## Subtitles

`--subtitles` downloads missing subtitles from OpenSubtitles.com as **sidecar `.srt` files** — no remux, media streams untouched. Requires `api_key`, `username`, and `password` in the `[subtitles]` TOML section (free account ≈ 20 downloads/day, VIP ≈ 1000/day; the log shows your remaining quota after each download and the run stops gracefully when it's exhausted).

- **Naming**: single configured language → exact MKV stem + `.srt` (`Night of the Living Dead (1968) - tt0063350 - ... - [Hindi + English].srt`). Extra languages get a suffix: `.hin.srt`, `.tel.srt`.
- **Languages**: `[subtitles] languages = ["en"]` (ISO 639-1; English is the default).
- **Skips** files already covered — embedded subtitle track in the wanted language OR an existing sidecar.
- **Matching**: file hash (identifies the exact release — best sync) + IMDB ID, ranked by hash-match → trusted uploader → download count.

```bat
:: See what's missing (offline, no quota spent)
python MediaCleanup.py --subtitles --dry-run

:: Download for one show
python MediaCleanup.py --subtitles --tv --input "D:\Media\TV\Show Name (2019)"

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
Grouping compares the *inferred title + year*, not raw filenames, so junk like `DD5.1-224Kbps + Dual Audio UnCut` no longer blocks a match. If two releases still aren't merged, check the log:
- `Runtime mismatch — not merging …` — the files have different durations (alternate cut, extra logos). Merging them would desync the added audio, so they are processed separately by design.
- Different inferred years — a remake never merges with the original.
- Different folders — grouping never crosses folder boundaries.
Otherwise lower `--similarity-threshold` (0.80/0.75) to allow looser title matches; `--verbose --dry-run` shows every comparison.

**Cover art not found for a title**
Check the log for the lookup details (`[DRY]` run shows title/IMDB ID/languages used). If the online sources miss it, drop a `poster.jpg` in the folder and re-run.

**Cover not showing in a player**
The cover is a standard Matroska attachment named `cover.jpg`. Some players cache thumbnails — refresh the library. Verify it's embedded: `mkvmerge.exe -J file.mkv` → `attachments`.

**A show's `und` tracks stay `und`, or its tags stay thin**

A renewed show's release year is the year *that season* aired, not the year the series began — a season 3 episode released three years after the show's debut no longer matches its first-air year, so year-constrained lookups miss it. Both the language resolution below and the show/season/episode metadata tags now identify the series by an **exact, year-agnostic title match** instead, with the same `--pick` mechanism as movies when more than one series shares that exact title:

```
Cannot identify the show 'Show Name' — 3 series share that exact title.
    This file's audio: Kannada
    [1] Show Name (2026)  Kannada  IN <- matches this file's audio
       https://www.themoviedb.org/tv/123456
    [2] Show Name (2007)  English  US
    ...
    -> choose one of these with --pick, e.g. --pick 1
```

```bash
python MediaCleanup.py --tv --pick 1
```

Movies and shows share one numbered list and one `--pick` command — pick several titles of either kind in one run, e.g. `--pick 1 3 5`.

**A film left unrenamed, reported `PARTIAL`**

A title and a year do not identify a film — several releases can share both. Rather than let the database's ranking decide, the tool resolves each film to a single IMDB id first, and when it cannot, it leaves the file alone and shows you what it found:

```
Cannot identify The.Film.2026...mkv — 3 films match 'The Film' (2026).
    This file's audio: Hindi, Kannada, Tamil, Telugu
    1. The Film: A Longer Subtitle (2026)  Kannada <- matches this file's audio
       tt1111111    https://www.imdb.com/title/tt1111111/
       original title: <in its own script>
       A powerful drug cartel pulls the strings behind a facade of sun-soaked...
    2. The Film Returns (2026)  English
       (no IMDB id) https://www.themoviedb.org/movie/123456
       What happens when a community's coastline becomes a dumping ground...
    Choose one, then either rerun scoped to this file with its id:
        python MediaCleanup.py --movies --filter 'The.Film.2026*' --imdb tt1111111
    or put the id in the filename (e.g. 'The Film (2026).tt1111111.mkv') and rerun.
```

**Choosing.** The language a film was made in usually settles it, so candidates whose language matches one your file actually carries are listed first and marked. That ordering is a hint only — it never picks for you, because a dubbed release would defeat it.

**Selecting by number.** Every candidate in a run is numbered, and the summary ends with a command you can run as-is:

```
2 film(s) need identifying — pick from the numbered list above, then rerun:
    python MediaCleanup.py --movies --pick 1 3
```

One number per film, and several films can be resolved in a single run:

```bash
python MediaCleanup.py --movies --pick 2 3
```

```
Pick 2: Another Film (2022) -> tt2222222
Pick 3: The Film: A Longer Subtitle (2026) -> tt1111111
Identifying 2 film(s) from your picks.
```

The numbers come from `logs\pending_identity.csv`, written by the run that listed them and read back verbatim — never recomputed, so a number always means the film you were shown. The file is rewritten each run and deleted once nothing is outstanding, so **always pick from the most recent listing**.

Bad picks are refused rather than guessed at: a number that isn't in the list, one whose candidate has no IMDB id, two numbers for the same film, or `--pick` with no saved list all stop the run with an explanation.

**Selecting by id.** If you already know the id, skip the preview:

```bash
python MediaCleanup.py --movies --filter "The.Film.2026*" --imdb tt1111111
```

Either way the id is written into the file's Matroska tags during the tag pass, so the film identifies itself on every later run — you choose once, never again. An id already in the filename, a parent folder or the tags is always used as-is, with no lookup at all. These filename shapes all work and none disturb title parsing:

```
The Film (2026).tt1111111.mkv          The Film 2026 [tt1111111].mkv
The Film.2026.tt1111111.1080p.mkv      The Film (2026) - tt1111111ile.mkv
```

**Renamed as a different, similarly-named show**

A query for `Show Name` can be answered by `Show Name Extended` — same year, so the year constraint cannot tell them apart. The lookup now requires the matched series name to be the one asked for, so a longer name that merely contains it is dropped and the show is resolved through TMDB by exact title instead. If two series share a name exactly and the filename carries no year, nothing is guessed: the file is left unrenamed and reported `PARTIAL`.

**Wrong metadata or poster embedded (from a different title)**
Lookups are year-verified for films and series alike, so a title no longer resolves to a better-known one that merely contains the same words — a search for a 2026 film is not satisfied by a more popular film from 2017 with a longer name. A series likewise no longer resolves to a same-named show from another year — which is what TMDB returns first when several share a name. When no series matches the year, the script now embeds **nothing** rather than another show's data. To repair files tagged before this fix:

```bat
python MediaCleanup.py --cleantags --tv --filter "Show Name*"                     :: re-tag correctly
python MediaCleanup.py --coverart --tv --filter "Show Name*" --coverart-overwrite :: re-fetch the poster
```

To strip a file bare instead, use `--clear`:

```bat
python MediaCleanup.py --cleantags --clear --tv --filter "Show Name*"  :: remove all tags/title/track names
python MediaCleanup.py --coverart  --clear --tv --filter "Show Name*"  :: remove the embedded cover
```

**A TV episode is renamed to a different show with the same name**
Shouldn't happen any more. TV lookups are constrained to the series year from the folder/filename, and if TheTVDB has no matching series the script resolves it on TMDB and pins FileBot to that exact series id. This matters for regional shows, which often have no TheTVDB entry at all — FileBot used to silently substitute a same-named series instead. Make sure the show folder or filename carries the right year — that year is the constraint.

**A film whose title contains or ends in a year**
Handled. Such releases carry two year tokens — `The.Film.1984.2020.1080p...` — and the last one is taken as the release year, keeping the earlier one in the title. When the filename has no release year at all (`The.Film.1984.1080p...`), the parsed year is retried as part of the title, but only after checking against the database that a film by that name really exists — so it resolves to the right entry rather than another film in the same series.

**A movie is renamed to the wrong year (e.g. a 2026 film matched to a 1984 remake)**
Shouldn't happen any more: movie lookups are constrained to the year in the filename (±1 for release-date drift), so a same-title film from another year can never win. If the correct title genuinely can't be found under that year, the file is reported **FAILED** rather than renamed to a wrong guess — check the summary table.

**A file named `www.SomeSite.xyz - Movie.2024...` fails to identify**
Prefixes that look like a web address are stripped automatically before the database lookup. For prefixes that are just a name with no domain suffix, add them to `[naming] strip_prefixes` in your config. If a title still fails, the script also retries once letting FileBot parse the raw filename itself — check the log for `retrying without query`. If both attempts miss, the title may genuinely not be in TheMovieDB/TheTVDB yet; rename the file manually to `Title (Year).mkv` and re-run.

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
