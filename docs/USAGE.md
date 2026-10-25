<div align="center">

# 📖 MediaCleanup — Usage Guide

**Every flag, every workflow, and how a title gets its name.**

[⚙️ Configuration](CONFIGURATION.md) · [🏠 README](../README.md) · [📝 Changelog](../CHANGELOG.md)

</div>

<br>

> [!NOTE]
> Looking for the one-page overview? The [README](../README.md) has the pipeline diagram, a "which command do I need?" table and the quick start. This guide is the full reference.

## 🗺️ Where to look

| I want to… | Go to |
|---|---|
| Install and run it for the first time | [Setup](#setup) |
| See every command at a glance | [Quick reference](#quick-reference) |
| Understand what the pipeline does to a file | [How a run works](#how-a-run-works) |
| Understand the summary table | [Reading the results](#reading-the-results) |
| Know every flag | [All flags](#all-flags) |
| Preview before changing anything | [Previewing a run](#previewing-a-run) |
| Control which languages are kept | [Target languages](#target-languages) · [Releases with no language tags](#releases-with-no-language-tags) |
| Turn MP4 files into finished MKVs | [Converting MP4 to MKV](#converting-mp4-to-mkv) |
| Tags, metadata and posters | [Metadata tags](#metadata-tags) · [Cover art](#cover-art) · [Cleaning tags and cover art together](#cleaning-tags-and-cover-art-together) |
| Know how titles are identified | [Titles no database knows](#titles-no-database-knows) |
| Fix a wrong or missing name | [Renaming messy filenames](#renaming-messy-filenames) · [Troubleshooting](#troubleshooting) |
| See my version, or check for a newer one | [Versions and updates](#versions-and-updates) |
| Install on a new machine, update, repair, or update MKVToolNix | [Installing, updating and repairing](#installing-updating-and-repairing) |

---

## Setup

1. Install Python 3.11+ and [MKVToolNix](https://mkvtoolnix.download/).
2. Copy `MediaCleanup.example.toml` to `MediaCleanup.toml` (same folder as the script) and edit the paths.
3. Validate: `python MediaCleanup.py --self-check`

All folder locations (media roots, tool paths) live in `MediaCleanup.toml` — the script has no hardcoded paths.

> [!TIP]
> `pip install rich` is recommended: it enables coloured log levels and the end-of-run summary table (`File | Action | Status | Detail`). Without it the script runs identically with plain-text output.

---

## How a run works

<div align="center">
<img src="images/pipeline.svg" alt="MediaCleanup pipeline: scan, group, select tracks, remux, clean tags, identify and rename, cover art" width="100%">
</div>

| Stage | What happens | Skipped when |
|---|---|---|
| 🔵 **1 · Scan & filter** | Finds every `.mkv` under the roots (or `--input`), narrowed by `--filter`. | — |
| 🔵 **2 · Group variants** | Releases of the same film in one folder are grouped by inferred title + year and matching runtime. | A file has no variants. |
| 🟣 **3 · Select tracks** | Best video (HEVC preferred); every audio track in your target languages from all variants; matching subtitles. | — |
| 🟣 **4 · Remux** | mkvmerge writes one clean MKV to a `.tmp` file, then renames it into place. Sources are only read. | The file already has exactly the tracks it needs. |
| 🟢 **5 · Clean tags** | Strips ads, junk tags and attachments; writes a clean title and track names; embeds rich metadata by verified id. | `--skip-cleantags` |
| 🟢 **6 · Identify & rename** | Identifies the title through the source chain, then renames by id — or names it from the file if no database knows it. | The title is ambiguous (left as it is). |
| 🩷 **7 · Cover art** | Embeds the poster of the verified title. | `--skip-coverart`, or the title is unidentified. |

The dashed arrow in the diagram is the **fast path**: a file that is already clean skips stages 3 and 4 and goes straight to tag cleaning and renaming. The coverage chart underneath shows which stages each standalone mode runs.

---

## Reading the results

Every run ends with a summary table. The **Status** column tells you what happened to each file:

| Status | Meaning | What to do |
|---|---|---|
| 🟢 **OK** | Processed, and renamed from a verified database match. | Nothing. |
| 🔵 **LOCAL** | No database knows the title, so it was named and tag-cleaned **from the file alone**. No id, poster or description was added. Listed in `logs\local_named.csv`. | Review the name if you like; a later run renames it properly once a database learns the title. `--no-local-name` disables this. |
| 🟡 **PARTIAL** | Processed, but **not renamed**: several titles share the name, or the rename failed. The reason is in the Detail column. | For several matches, [`--pick`](#choosing-between-ambiguous-titles). Otherwise read the reason. |
| ⚪ **SKIP** | Nothing needed doing: already covered, already named, or a film too ambiguous to give a poster. | Nothing. |
| 🔴 **FAIL** | Something went wrong. Sources are untouched. | Read the reason; see [Troubleshooting](#troubleshooting). |

A real summary, with one file in each state:

<div align="center">
<img src="images/results-table.svg" alt="The run summary table showing OK, LOCAL, PARTIAL, SKIP and FAIL rows" width="100%">
</div>

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
| `--version` | Print this tool's version and the versions of what it runs on (Python, MKVToolNix, FileBot, ffmpeg, x265, `rich`, Pillow), then exit. Needs no config. See [Versions and updates](#versions-and-updates). |
| `--check-update` | Compare with the latest published release and show what changed. Exit code `0` up to date, `10` newer available, `1` could not check. Downloads nothing. |
| `--update` / `--update-to TAG` | Install the latest (or a specific) published release, verified file by file, with a backup and automatic rollback. See [Installing, updating and repairing](#installing-updating-and-repairing). |
| `--repair` | Restore missing or modified project files, recreate folders, report config problems, re-install a missing MKVToolNix. `--files-only` limits it to the project files. |
| `--update-runtimes` | Update MKVToolNix, ffmpeg (once installed) and the pip packages; report FileBot, x265 and Python. |
| `--install TOOL` | Install `mkvtoolnix`, `ffmpeg`, `rich` or `pillow`. |
| `--yes` | Answer yes to the confirmation the update, repair and install modes ask. |

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
| `--no-local-name` | Leave a title that no database knows exactly as it is, instead of naming it from its own file (see [Titles no database knows](#titles-no-database-knows)). Config equivalent: `[naming] local_fallback = false`. |
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
| `--log-file PATH` | Also write the log to a file (always plain text, debug level). API keys, passwords and tokens are masked in it. |
| `--no-color` | Disable colored output and summary tables (`NO_COLOR` env also honored). |
| `--no-update-check` | Skip the once-a-day look for a newer release for this run. Config equivalent: `[updates] check = false`. |

---

> [!TIP]
> **Sharing a log?** Everything the tool logs, to the console and to `--log-file`, passes through a redactor that masks your API keys, passwords and tokens (including keys that travel in URLs, which TMDB, OMDb and fanart.tv require). Still look before you paste, and never attach `MediaCleanup.toml`.

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

> [!IMPORTANT]
> **Your source files are never touched.** The `.mp4` and `.srt` stay exactly where they were, whatever else happens — `--inplace` does not apply here. A ledger (`logs\mp4tomkv_done.csv`) records what has been converted so re-runs skip it; `--overwrite` ignores the ledger and redoes the work.

**Sidecar subtitles.** Any `.srt` whose name matches the video's (`<stem>.srt`, `<stem>.<tag>.srt`) is muxed in. Three things happen to it first:

- **Advertising is removed.** Some subtitles open or close with promotional cues that play over the film rather than translating it. A cue is treated as an advert when its text is structurally one — a web address, or stock phrasing such as "downloaded from" or "please visit" — and only when it falls in the first or last minute, so a line of dialogue that mentions a web address mid-film survives. Site names are not built in: whatever you list in `[naming] strip_prefixes` is matched too, the same list used to strip those names from filenames. Every removal is logged.
- **Forced tracks are flagged.** A subtitle carrying fewer than two cues a minute translates foreign dialogue rather than everything. It gets the forced flag, so players show it automatically over untranslated speech — and it is kept even though forced tracks are normally excluded, since dropping a film's only subtitle helps nobody.
- **The language is read from the text itself** (see [Releases with no language tags](#releases-with-no-language-tags)), because sidecar files rarely say what language they are.

**Languages**, since MP4 supplies none: a lone audio track and the video track take the title's TMDB original language; the subtitle is identified from its own text.

**Chapters are kept** — they are real navigation data — but any chapter *name* that advertises is rewritten to a plain `Chapter NN`.

> [!WARNING]
> This is the one place the tool edits stream content rather than metadata alone — a deliberate exception to the safety model, made so that advertising cannot be welded permanently into your library.

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
2. **TMDB** — looked up by the film's verified IMDB id (from the filename, folder or MKV tags, or resolved by the identification chain). Never by a title search.
3. **fanart.tv** — by IMDB/TMDB ID.
4. **OMDb** — last resort (~300px image).

API keys go in the `[coverart]` section of `MediaCleanup.toml`. Missing keys simply disable that source; with no keys at all, only local files are used.

**Films that cannot be identified.** A poster is only embedded for a film that has been pinned to one IMDB id — read from the filename, folder or tags, or resolved by the same check the rename uses. When several films share a title and a year, a title search would simply return whichever the database ranks first, so the file is **left exactly as it is**: nothing is embedded, a cover it already has is not replaced, and nothing is recorded in the ledger. It shows as a skip, with the numbered candidates listed so you can choose one and run again:

```bash
python MediaCleanup.py --coverart --pick 2
```

**Shows follow the same rule, for the rename as well.** A series is identified before its episodes are renamed, and FileBot is handed the series by id rather than searching for it, so it cannot land on a similarly named show. When more than one series shares the exact title the file is left unrenamed, reported `PARTIAL` with its candidates, and `--pick` resolves it. A show TMDB does not know is looked up on TheTVDB by name and year only, then on TVmaze, each held to the series name; if neither finds it the episode is named from its own file ([below](#titles-no-database-knows)), never given another show's name.

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

> [!NOTE]
> Plex and Jellyfin scrape their own metadata and mostly ignore embedded tags. The payoff is in VLC, MPC-HC and Kodi, and in archival self-containment — the file carries its metadata forever, independent of any server.

---

## Titles no database knows

A rename starts by **identifying** the title. The sources are tried in order, and a source is passed over only when it found **nothing**:

<div align="center">
<img src="images/identify.svg" alt="Identification chain: films try TMDB then OMDb, shows try TheTVDB and TMDB then TVmaze; a verified match renames by id, otherwise the file is named from itself" width="100%">
</div>

| | 🔵 1st | 🟣 2nd | 🟠 3rd |
|---|---|---|---|
| **Films** | TMDB | OMDb (needs `omdb_api_key`) | Named from the file |
| **Shows** | TheTVDB and TMDB | TVmaze (no key) | Named from the file |

Four rules hold throughout:

1. 🔴 **Several matches stop the chain.** If TMDB finds three films with the exact title, OMDb is not asked: the file is left alone and the candidates are numbered for `--pick`, because another database would only add more guesses.
2. 🟢 **Every hit is verified.** The title must match exactly or as a whole-word prefix; for films the year must be within one; for shows the series name must match. A near miss counts as "nothing found".
3. 🟠 **A database that cannot be reached is not "nothing found".** A network outage, a bad key or a rate limit leaves the file untouched; it never leads to anything being renamed.
4. 🔵 **The source is named in the log**, e.g. `Identified 'The Film' (2023) as The Film (2023) — tt1234567, via OMDb (TMDB has no match)`.

### Choosing between ambiguous titles

When several titles share a name, the run stops for that file, lists them **numbered**, and saves the list. You pick by number and run again:

```bat
python MediaCleanup.py --movies --dry-run     :: lists the candidates, writes nothing
python MediaCleanup.py --movies --pick 2 3    :: resolve titles 2 and 3 — films and shows can be mixed
python MediaCleanup.py --movies --filter "The.Film.2026*" --imdb tt1111111   :: or give the id directly
```

<div align="center">
<img src="images/pick-candidates.svg" alt="A numbered list of films that share a title, with the --pick command to resolve it" width="100%">
</div>

> [!IMPORTANT]
> Always pick from the **most recent** listing. The numbers are read back from `logs\pending_identity.csv` exactly as the last run wrote them, so a number always means the title you were shown. The full walkthrough, with sample output, is in [Troubleshooting](#troubleshooting).

A film OMDb identifies is renamed with this script's own name template — `Title (Year) - ttNNNNNNN - Source.Resolution.Codec - [Languages]` — rather than through FileBot, so it works without FileBot reaching OMDb. Its tags come from OMDb's record of that id (genre, director, cast, plot, rating): thinner than TMDB's, but the film itself.

### When every source finds nothing

The file is still named and its tags cleaned, **from facts that are in the file**:

```
movie.2023.Web.x264.mkv   ->   Movie (2023) - WebRip.1080p.x264 - [Hindi + English].mkv
show.name.s01e02.web.x264.mkv   ->   Show Name - S01E02 - 1080p.x264 - [English].mkv
```

- The **title and year** are the ones the filename states (a title written in all lower case is capitalised; one with any capital is left as written). The **resolution, codec and audio languages** are read from the video and its tracks, and the source tag (`WEB-DL`, `BluRay`…) from the filename.
- **Nothing is invented.** No IMDB id, no poster, no synopsis, no cast. The cover art already in the file is kept.
- The result is reported **`LOCAL`** in the summary, separate from `OK`, and every such rename is appended to `logs\local_named.csv` (old path, new path, why) so a name no database confirmed can always be told from one that was.
- It carries no id, so a later run renames it normally if a database learns the title.

It applies only to "found nothing". It never applies to a title with **several** possible matches (that is a choice for you, via `--pick`), and never when no database could be reached. A film needs a plausible year in its filename and an episode needs a season and episode number; without them the file is left as it is and the reason is shown.

`--no-local-name` (or `[naming] local_fallback = false`) turns it off, restoring "leave it as it is".

**Previews.** `--dry-run` shows the `LOCAL` name for a film. For a show TMDB does not know, a dry run cannot tell whether TheTVDB or TVmaze would find it (that needs FileBot's own search; `--preview-exact` asks it), so it states what happens if neither does.

**Scope.** The fallback belongs to the processing modes (`--movies`, `--tv`), `--cleantags` and `--cleanmetadata`. `--rename` uses the same sources, so it can rename a film only OMDb lists, but it never names a file from the file alone. TV episodes are named through FileBot, so that path needs FileBot to be installed.

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

> [!NOTE]
> `--rename` identifies titles through the same [source chain](#titles-no-database-knows), so it can rename a film only OMDb lists. It never names a file from the file alone — that fallback belongs to the processing modes and `--cleantags`/`--cleanmetadata`.

Details: requires exactly one of `--movies`/`--tv` (different databases + formats); the DB lookup uses a cleaned title query so filename noise doesn't mislead it; every rename is appended to `logs\rename_history.csv`; `--rename-undo` reverts the most recent batch (skipping files that moved since) and removes it from the history. Note the language bracket in the new name reflects the audio tags *inside* the file — fix `und` tracks with the force flags or the bracket may be wrong.

---

## Subtitles

`--subtitles` downloads missing subtitles from OpenSubtitles.com as **sidecar `.srt` files** — no remux, media streams untouched. The log shows your remaining quota after each download, and the run stops gracefully when it is used up.

**Only the API key is required.** Per OpenSubtitles' own manual, the key alone can search without limit and download **5 subtitles per IP address per day**. Adding your account's `username` and `password` logs you in, which raises the download limit:

| Setup | Search | Downloads per day |
|---|---|---|
| `api_key` only | unlimited | 5 per IP address |
| `api_key` + `username` + `password` (free account) | unlimited | about 20 |
| VIP account | unlimited | up to 1000 |

Download counters reset at midnight UTC.

> [!IMPORTANT]
> The `username` is your OpenSubtitles **username, not your email address**. A login with an email is refused (HTTP 400: *"remember to use your username and not your email"*). If the login fails for any reason the run **carries on with the API key alone** and tells you why, in the server's own words.

> [!NOTE]
> OpenSubtitles asks that an application use its own API key and warns against apps that make each user create one. This is a script you run yourself, with your own consumer key from <https://www.opensubtitles.com/en/consumers>; do not share that key. If you ever distribute MediaCleanup to others, read the integrator terms linked from the [manual](https://opensubtitles.stoplight.io/docs/opensubtitles-api/e3750fd63a100-getting-started) first.

- **Naming**: single configured language → exact MKV stem + `.srt` (`Night of the Living Dead (1968) - tt0063350 - ... - [Hindi + English].srt`). Extra languages get a suffix: `.hin.srt`, `.tel.srt`.
- **Languages**: `[subtitles] languages = ["en"]` (ISO 639-1; English is the default).
- **Skips** files already covered — embedded subtitle track in the wanted language OR an existing sidecar.
### How a subtitle is found and chosen

The service's search results say nothing about how *long* a subtitle is, so the choice is made in two stages: **score before downloading, verify after.**

**1. Which title is this?** An id already on the file (its name, folder or tags) is used as-is. Otherwise the title is identified the way a rename identifies it. A film that cannot be pinned to **one** title is skipped with the reason — **there is no search by title alone**, because the top hit of a title search can be another film. An exact-release hash match is still allowed, since that is an exact match and not a guess.

**2. Search** (free — searching uses no download quota). At most three searches, most precise first:

| | 1st | 2nd | 3rd |
|---|---|---|---|
| **Film** | id + file hash | id alone | exact-release hash only |
| **Episode** | series id + season + episode (+ hash) | series id + season + episode | exact-release hash only |

An episode is searched by its **series** id with the season and episode from the filename — the series id alone would only find the show's own entry, not the episode. The TMDB series id is used when no IMDB id is known.

**3. Score the candidates before downloading**, using only what the results carry:

| Signal | Effect |
|---|---|
| Exact-release **hash** match | Decisive: beats any amount of popularity |
| **Source** (WEB / BluRay / HDTV / DVD) matches your file | Up if it matches, down if it differs |
| **Edition** words (Colorized, Remastered, Extended, Unrated, Director's Cut, Uncut, Theatrical, Anniversary, Restored) | Up if shared; down if the subtitle is for an edition your file is not |
| **Frame rate** | Up if it equals your video's; down if it clearly differs (a different rate drifts over the film). Unknown (`0`) is neutral. |
| A **runtime** written in the release text (`… 1:35:08`) | Up if it matches your video's duration; down if it clearly differs |
| **Release group** | Up if the same |
| Hearing-impaired, AI-translated | Mildly down |
| Trusted uploader, rating, download count | Small tie-breakers |
| Split over several discs (`nb_cd > 1`), machine-translated, foreign-parts-only | **Excluded** |

**4. Download the best, then verify it against your video.** The subtitle's advertising cues are stripped first (they can run past the end of the video), then it **fits** when its last line ends within about 70%–100% of the video's duration (30 seconds of tolerance), its first line is not past a third of the video, and it has a sensible number of lines. This catches a wrong cut, a wrong film and a truncated file. It cannot catch a small frame-rate drift, which is why frame rates are compared *before* downloading.

<div align="center">
<img src="images/subtitle-fit.svg" alt="The first subtitle does not fit the video's length, so the next-best is tried and saved" width="100%">
</div>

**5. If it does not fit, the next-best candidate is tried once.** That uses one more download from your quota, and only happens if quota remains. If that one does not fit either, **nothing is saved** and the summary says why:

```
no en subtitle fit the video (runs to 2:01:41 but the video is only 1:35:08; ends at 0:40:00, only 42% of the video's 1:35:08)
```

A subtitle that passes is saved, with its advertising cues removed, as `<video name>.srt`.

> [!NOTE]
> With the API key alone you have 5 downloads a day, so a retry is a real cost: the scoring in step 3 is there so the first download is usually right. Each file uses one download when it works first time, two at most.

**Also handled**
- **Language already present:** embedded subtitle languages are recognised by their real language code (German `ger` is `de`, Spanish `spa` is `es`, Chinese `chi` is `zh`); previously only the first two letters were compared, which is wrong for those.
- **Titles that need a choice:** a film or show that has several possible matches lists numbered candidates, and `--pick` resolves it, exactly as for renames.
- **Polite to the service:** requests are spaced (the limit is about 5 a second), a rate-limit answer is waited out, a refused login is never retried, and the login token is renewed if a long run outlives its 24 hours.

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

Hindi-dubbed releases often tag audio as `und` with a generic name like "2 channels".

> [!NOTE]
> The script now tries to work these out itself (a lone unlabelled audio track takes the title's original language; subtitles are identified from their own text — see [Releases with no language tags](#releases-with-no-language-tags)). The explicit override below is for the cases it cannot call confidently, such as two or more unlabelled audio tracks.

Tell it explicitly:

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

:: See which films are ambiguous, then resolve them by number
python MediaCleanup.py --movies --dry-run
python MediaCleanup.py --movies --pick 1 3

:: Leave titles no database knows exactly as they are
python MediaCleanup.py --movies --no-local-name

:: Convert MP4 downloads you own into finished MKVs
python MediaCleanup.py --mp4tomkv --movies --input "D:\Downloads"

:: Tags + metadata + rename + poster for a folder, no remux
python MediaCleanup.py --cleanmetadata --movies --input "D:\Media\Fixed"
```

---

## Versions and updates

```bat
python MediaCleanup.py --version          :: what is installed
python MediaCleanup.py --check-update     :: is there a newer release, and what changed
```

<div align="center">
<img src="images/version.svg" alt="The output of --version" width="100%">
</div>

`--version` prints the tool's version and the version of everything it runs on, so a bug report or a "which build do I have?" question has one command to answer it:

```
MediaCleanup 1.11.0
  Python       3.13.14   [C:\...\python.exe]
  Platform     Windows-11-10.0.26100-SP0
  mkvmerge     mkvmerge v103.0 ('The Darkness') 64-bit   [runtimes\mkvtoolnix\mkvmerge.exe]
  mkvpropedit  mkvpropedit v103.0 ('The Darkness') 64-bit   [runtimes\mkvtoolnix\mkvpropedit.exe]
  FileBot      FileBot 5.3.0 (r11096)   [runtimes\FileBot\filebot.exe]
  ffmpeg       not installed (optional, not used yet)
  x265         not installed (optional, not used yet)
  rich         15.0.0
  Pillow       12.2.0
```

`ffmpeg` and `x265` are listed because future features will use them; today nothing calls them, and "not installed" is not an error. They are looked for in `runtimes\ffmpeg\bin\` and `runtimes\x265\`, then on the `PATH`.

<div align="center">
<img src="images/check-update.svg" alt="--check-update showing a newer release and what changed" width="100%">
</div>

**Checking for a newer release.** `--check-update` asks GitHub for the latest *published release* — never a branch — and compares it with your version. If a newer one exists it prints the release address and the changelog entries since your version:

```
A newer release is available: 1.12.0, published 2026-11-01
  https://github.com/atikansari-ghr/MediaCleanup/releases/tag/v1.12.0

What changed since your version:
  [1.12.0] - 2026-11-01
    ### Added
    - ...
```

It only reads: nothing is downloaded or installed. The exit code is `0` when you are current, `10` when a newer release exists and `1` when the check could not be made, so it works in a script.

**The daily notice.** Normal runs also look once a day, **in the background**, and print one line at the end if a newer release exists:

```
MediaCleanup 1.12.0 is available (you have 1.11.0) - run: python MediaCleanup.py --check-update
```

- It never delays a run: the check runs beside the work, and at the end the tool waits at most a second and a half for it.
- The answer is cached in `logs\update_check.json` for a day, and a failed check is not retried for an hour, so being offline costs nothing.
- `--dry-run` stays offline: it only shows a notice an earlier check already found.
- Turn it off with `--no-update-check` for one run, or `[updates] check = false` in the config.

> [!NOTE]
> The only thing sent is an ordinary request to `api.github.com` carrying a `MediaCleanup/<version>` user-agent. There is no telemetry.

> [!TIP]
> The update check needs no token because the repository is public. If you run a **private fork**, GitHub answers "not found" to an anonymous request: set the environment variable `MEDIACLEANUP_GITHUB_TOKEN` to a read-only personal access token and the check will use it. The token is only ever sent to `api.github.com`, and is dropped if a download is redirected to another host.

### Installing, updating and repairing

<div align="center">
<img src="images/lifecycle.svg" alt="Install, check, update, repair and runtime updates, with a matrix of what each command may change" width="100%">
</div>

| Command | What it does |
|---|---|
| `install.ps1` | One-command install: Python, the tool, MKVToolNix, a first config, a launcher. See [the installer](#the-installer). |
| `--update` | Installs the latest published release over this one. |
| `--update-to vX.Y.Z` | The same, to a specific release — the only way to move to an **older** one. |
| `--repair` | Brings an install back to a working state. |
| `--update-runtimes` | Updates MKVToolNix, ffmpeg (once installed) and the pip packages. |
| `--install TOOL` | Installs `mkvtoolnix`, `ffmpeg`, `rich` or `pillow`. |
| `--yes` | Answers yes to the confirmation these ask — needed when there is no terminal. |

All of them show a **plan first and ask**, `--dry-run` shows the plan and stops, and a failed step restores what it changed. Exit codes: `0` done (or nothing to do), `1` failed with nothing changed, `5` you declined.

#### `--update`

```bat
python MediaCleanup.py --update --dry-run     :: show exactly what would change
python MediaCleanup.py --update               :: ask, then do it
```

```
Release v1.12.0, published 2026-11-01

  [1.12.0] - 2026-11-01
    ### Added
    - ...

  New files (2):
    docs/images/lifecycle.svg
  Replaced (6):
    MediaCleanup.py
    ...
  Already identical: 9 file(s)

  Everything replaced is copied to backup\update-1.11.0-to-1.12.0-20261101-093000 first.
  MediaCleanup.toml, logs\ and runtimes\ are never touched.

Install v1.12.0? [y/N]
```

<div align="center">
<img src="images/update-plan.svg" alt="--update --dry-run showing which files would change" width="100%">
</div>

- **Every file is verified.** GitHub publishes a hash for each file in a release. The download is unpacked, each file is checked against its published hash, and nothing is written unless every one matches — so what lands on disk is exactly what was released.
- **Only files the release contains are written.** `MediaCleanup.toml`, `logs\`, `backup\` and the tools in `runtimes\` are never touched, whatever a release lists.
- **Anything replaced is backed up first** under `backup\update-<from>-to-<to>-<time>\`, and a failure part-way puts every file back. To undo a finished update, copy the files from that folder back, or run `--update-to` the previous version.
- **Files you edited are flagged.** If a file differs from the release you have installed, it is listed in the plan and your copy is kept in the backup.
- **New settings are reported, not applied.** Afterwards the tool lists any setting in `MediaCleanup.example.toml` that your `MediaCleanup.toml` lacks (the defaults apply until you add it). Your config is never edited.
- **A git clone is updated with git:** it fetches the tags and fast-forwards (or checks out the tag). It refuses if you have uncommitted changes, and an older tag is a deliberate checkout, never a silent no-op.

#### `--repair`

```bat
python MediaCleanup.py --repair --dry-run
```

```
Checking this MediaCleanup 1.11.0 install...

  [ok]   folders
  [fix]  restore 2 project file(s) from v1.11.0: README.md, docs/USAGE.md
  [ok]   MediaCleanup.toml reads correctly
  [--]   setting not in your MediaCleanup.toml (the default applies): updates.check = true
  [ok]   MKVToolNix runs (mkvmerge v103.0 ('The Darkness') 64-bit)
  [--]   FileBot not installed (optional)
```

<div align="center">
<img src="images/repair.svg" alt="--repair --dry-run restoring a deleted and a modified file" width="100%">
</div>

| Line | Meaning |
|---|---|
| `[ok]` | Checked and fine. |
| `[fix]` | Will be repaired if you confirm. |
| `[--]` | Information; nothing to do. |
| `[FAIL]` | Needs you — for example a `MediaCleanup.toml` that is not valid TOML. It is reported, never overwritten. |

It restores missing or modified **project files** from the release you have installed (backed up first), recreates missing folders, creates `MediaCleanup.toml` from the example if it is missing, and re-installs MKVToolNix when it is missing or does not run and lives inside `runtimes\`. A git clone's files are left to git. `--files-only` checks just the project files (the installer uses it to verify a fresh download).

#### `--update-runtimes` and `--install`

```bat
python MediaCleanup.py --update-runtimes --dry-run
```

```
  Component   Installed                  Latest                     Status
  ----------  -------------------------  -------------------------  ------
  MKVToolNix  103.0                      103.0                      up to date
  ffmpeg      2026-01-12-git-21a3e44fbe  2026-10-22-git-bf0e831606  UPDATE: newer git build available (includes libx265)
  x265        4.1+211-9e551a994          -                          standalone builds are third-party, so it is not updated automatically
  FileBot     5.3.0                      -                          licensed software - check https://www.filebot.net/ for a newer version
  Python      3.13.14                    -                          not updated by this tool; use: winget upgrade Python.Python.3.13
  rich        15.0.0                     15.0.0                     up to date
  Pillow      12.2.0                     13.0.0                     UPDATE: newer version available (pip)
```

<div align="center">
<img src="images/update-runtimes.svg" alt="--update-runtimes --dry-run listing each tool with its installed and latest versions" width="100%">
</div>

| Tool | Handling |
|---|---|
| **MKVToolNix** | Updated automatically from the official portable build, **SHA-256 verified**. Only a copy inside `runtimes\` is managed; one installed elsewhere is reported. |
| **ffmpeg** | **Opt-in**: `--install ffmpeg` adds it, then it is kept updated like MKVToolNix. Only gyan.dev builds in `runtimes\ffmpeg\` are managed, on the channel (release or git) and variant (full or essentials) you already have. It carries libx265, so x265 comes with it. Nothing calls it yet. |
| **`rich`, Pillow** | Upgraded with `pip` when installed; `--install rich` / `--install pillow` add them. |
| **x265, FileBot, Python** | **Reported only.** x265 binaries are third-party, FileBot is licensed software, and Python cannot replace the interpreter that is running it. |

Downloads come only from `mkvtoolnix.download`, `www.gyan.dev` and `pypi.org`, over HTTPS, and each is checked against a SHA-256 published beside it before it is unpacked. The folder being replaced is moved to `runtimes\_previous\` and **put back automatically if the new tool does not run**; only the newest previous copy is kept. A `.7z` is unpacked with 7-Zip or Windows' built-in `tar`; if neither exists the tool says so.

#### The installer

`install.ps1` gets a machine from nothing to a working install with one command. It is deliberately thin: it finds or installs Python, unpacks the release, writes a first `MediaCleanup.toml`, and then uses the tool's own `--repair --files-only` (to verify every file) and `--install` (for MKVToolNix and the packages).

```powershell
# from the latest release (no account, no token)
irm https://github.com/atikansari-ghr/MediaCleanup/releases/latest/download/install.ps1 | iex

# or download it, read it, and run it with options
powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallDir D:\Tools\MediaCleanup
```

| Parameter | Meaning |
|---|---|
| `-InstallDir` | Where to install (default `%USERPROFILE%\MediaCleanup`). |
| `-Tag` | A specific release such as `v1.12.0` (default: the latest). |
| `-MoviesRoot` `-TvRoot` `-OutputRoot` | Your folders. Asked for when omitted. |
| `-TmdbKey` `-OmdbKey` `-FanartKey` | Your API keys (all optional). |
| `-MkvToolNixDir` / `-FileBotExe` | Use an existing MKVToolNix or FileBot instead of installing one. |
| `-WithFfmpeg` `-WithPillow` `-NoRich` | Optional packages. |
| `-SkipRuntimes` | Do not install MKVToolNix or any package. |
| `-AddToPath` | Add the folder to your user PATH so `mediacleanup` works anywhere. |
| `-Yes` | Never ask: use the defaults and the parameters given. |
| `-FromDir` | Install from a local checkout (developers, offline use). |

- **Re-running it updates.** On an existing install it runs `--update` and never touches `MediaCleanup.toml`. An install older than 1.12.0 has no `--update`, so the installer instead replaces its files from the latest release (verified, with the old script and example config copied to `backup\pre-installer-<time>\`) and keeps your config.
- **No administrator rights.** Python is installed per user with winget when it is missing.
- **FileBot is never downloaded.** It is licensed; the installer only tells you where to get it.
- **Failure leaves nothing half-done outside the install folder**, and the script exits non-zero when run as a file. Under `irm | iex` it never calls `exit`, so your window stays open.

> [!WARNING]
> `irm … | iex` runs a script straight from the internet. If you would rather read it first, download `install.ps1` from the release, open it, and run it with `-File`. It is plain, commented PowerShell.

---

## Troubleshooting

| Symptom | Likely cause | Jump to |
|---|---|---|
| 🟡 `PARTIAL`, "pick one — …" | Several titles share the name | [A film left unrenamed](#troubleshooting) · [`--pick`](#choosing-between-ambiguous-titles) |
| 🔵 `LOCAL` | No database knows the title | [A file was given a LOCAL name](#a-file-was-given-a-local-name) |
| 🟡 `PARTIAL`, "no database could be reached" | Network, key or rate-limit problem | [Nothing renamed, "could be reached"](#nothing-renamed-no-database-could-be-reached) |
| 🔴 Wrong poster or tags | A different title was matched | [Wrong metadata or poster](#troubleshooting) |
| 🔴 FileBot errors | Java or `TEMP` path | [FileBot not renaming](#troubleshooting) |
| ⚪ Files not merged | Different runtime, year or folder | [Files not grouped for merge](#troubleshooting) |
| 🟠 "GitHub shows no release here" | The repository is private, or no release is published | Set `MEDIACLEANUP_GITHUB_TOKEN` — see [Versions and updates](#versions-and-updates) |
| 🟠 Update says a file "does not match" | The download was corrupted or altered | Nothing was changed; run `--update` again. If it persists, do not install it. |
| 🟠 "is it running?" while updating MKVToolNix | A tool from `runtimes\` is open | Close it (and any run in progress) and retry; nothing was changed. |
| 🟠 "nothing here can unpack" a `.7z` | No 7-Zip and no Windows `tar.exe` | `winget install 7zip.7zip`, or use Windows 10 1803 or newer. |
| 🟠 "uncommitted changes" on `--update` | The folder is a git clone with edits | Commit or stash them; clones are updated with git. |
| 🟠 A broken install | Files deleted or edited by accident | `python MediaCleanup.py --repair` |
| 🟠 OpenSubtitles "login failed (HTTP 400 …)" | The `[subtitles] username` is an email address | Use your OpenSubtitles **username**. The run continues with the API key alone (5 downloads per IP per day). |
| 🟠 `--subtitles` says the quota is used up | The daily limit was reached | The message gives the renewal time (UTC midnight). Log in (username + password) for about 20 a day. |
| 🟠 "no en subtitle fit the video (…)" | The best two candidates were for a different cut or length | Nothing was saved, on purpose. The reasons show how they differed; try again tomorrow, or fetch one by hand. |
| 🟠 A film is skipped with "pick one — …" | Several films share the title | `--pick N`, exactly as for renames; subtitles need an identified title. |

### A file was given a LOCAL name

No database that could be asked knew the title, so it was named from its own filename and the video's properties, and its tags were cleaned. Nothing was invented: no id, poster or description. Every such rename is listed in `logs\local_named.csv` (old path, new path, why).

- If the title *is* in a database under a different spelling, rename the file to that spelling (or give `--imdb`) and run again — there is no id in the name, so it will be renamed normally.
- To keep unknown titles exactly as they are, use `--no-local-name` or set `[naming] local_fallback = false`.
- A film needs a plausible year in its filename and an episode needs a season and episode number; without them the file is left as it is and the reason is shown.

### Nothing renamed, "no database could be reached"

Every source that could have answered failed to — no key configured, a rejected key, no network, or a rate limit. The file is deliberately **not** treated as unknown: it is left untouched. Run `python MediaCleanup.py --validate-keys`, check your connection, and run again. OMDb's free tier allows about a thousand requests a day.

### Everything else

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
The Film.2026.tt1111111.1080p.mkv      The Film (2026) - tt1111111file.mkv
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
