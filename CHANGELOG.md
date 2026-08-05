# Changelog

All notable changes to MediaCleanup are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [1.4.0] — 2026-08-05

### Fixed
- **Variant releases were not being merged** — grouping compared raw filenames, so `The Film 2025 Hindi DD5.1-224Kbps + Kannada Dual Audio UnCut South Movie HD 1080p ESub.mkv` and `The.Film.2025.WEB-DL.720p.Multi.Audio.ESub.mkv` scored 0.382 similarity (threshold 0.88) and were processed as two separate files instead of one merged release. Grouping now compares the **inferred title + year**, which both files resolve to identically.

### Added
- **Identity-based grouping** — releases whose titles differ too much to match (`The Film` vs `The Film Extended Title`) are merged when they resolve to the same IMDB/TMDB id. Free signals first (id in filename, folder, or MKV tags), database lookup only for folders with more than one candidate, results cached in `logs/movie_identity.csv`.
- **Runtime guard** — a merge candidate is split into same-duration cohorts before merging (±1%). Combining releases of different length (alternate cut, extra logos, PAL speed-up) would desync the added audio for the whole film; those files are now processed separately with a clear warning.

## [1.3.2] — 2026-07-29

### Fixed
- **Wrong-year matches** — `SiteName.Foo.The Film.2026...` was renamed to `The Film (1984)`. Movie lookups are now constrained to the filename year (±1 for release-date drift), so a same-title film from another year can never be matched. When nothing matches under the constraint the file is reported FAILED instead of silently renamed to a wrong guess. TV is never year-constrained.
- **Release-site names without a valid TLD** — `SiteName.Foo`, `ExampleSiteA`, `ExampleSiteB.GroupName`, `ExampleSiteC.MX`, `ExampleSiteD.nl` and ~40 other known sites are now stripped from movie and TV name inference (longest-match-first, chained, with an over-strip guard so `SiteName.Up.2009` still yields `Up`).

## [1.3.1] — 2026-07-24

### Fixed
- **Release-site prefixes broke identification** — filenames like `www.example-site.net_-_The Film_2026_...` produced the lookup query `www example-site net - The Film (2026)`, which no database could match. Leading `www.*`, `domain.tld`, and `[www.site.com]` prefixes are now stripped from movie *and* TV name inference. Legitimate dotted titles (`Dotted.Title.One`, `Dotted.Title.Two`) are explicitly protected.
- **FileBot query fallback** — when a lookup using our inferred title finds no match, FileBot is now retried once without `--query`, letting its own release-name parser identify the file (e.g. `ExampleSiteB.GroupName.Another Film.2014...` → `Another Film (2014) - tt1234567`).

## [1.3.0] — 2026-07-09

### Added
- **Complete ISO 639 language registry** (189 languages) built in — `[languages] targets`, `--audio-langs`, and the `--force-*-lang` flags now accept every form: 2-letter (`ko`), 3-letter bibliographic *and* terminological (`kor`, `fra`), full English names (`Korean`), and common alternates (Farsi, Punjabi, Bangla…).
- **BCP-47 track tags** — modern `language_ietf` tags (`zh-Hans`, `pt-BR`) are detected via their primary subtag when the legacy language field is `und`.
- Native-script track-name detection extended to ~25 languages (한국어, 中文, français, 日本語, русский, বাংলা, …).

### Fixed
- **Filename language brackets** for languages outside the original hardcoded set: FileBot formats now resolve any language generically — Korean/French/Chinese tracks render as `[Korean + French]` instead of `[Ko + Fr]`.

## [1.2.0] — 2026-07-09

### Changed
- **Remuxing reads sources directly** — the working-copy mirror (`work_root` / `ToFix`) was removed: half the I/O, half the temporary disk space, same safety (mkvmerge never modifies its inputs). Old configs with `work_root` keep working; the key is ignored.

### Added
- **`--inplace`** — remuxed output replaces the source file(s) in their own folder instead of going to `output_root`. A verification gate (exact track counts + container duration match) must pass before any source is touched; multi-file merges consume all variants.
- **`--backup`** — with `--inplace`, consumed sources are kept as `<name>.original.mkv` beside the new file instead of deleted. Backup files are excluded from every scan.

## [1.1.0] — 2026-07-08

### Added
- **Configurable target languages** — `[languages] targets` in `MediaCleanup.toml` (ISO codes or English names, ~40 languages built in). List order controls the output audio track order. Default remains Hindi/English/Telugu.
- **Video track language fix** — the video track (usually `und`) is stamped with the title's original language from TMDB during tag cleaning; `--force-video-lang` overrides.
- **Cover art in the main pipeline** — `--movies`/`--tv` now finish each file completely: remux, tags + metadata, FileBot rename, and cover art embed (ledger-backed; `--skip-coverart` to disable).
- Committed `runtimes\` folder skeleton with a setup guide; relative TOML paths resolve against the script folder for clone-and-go setup.

## [1.0.0] — 2026-07-08

First public release.

### Added

**Core pipelines**
- Movie pipeline: groups variant releases of the same movie by filename similarity, selects the best video track (HEVC preferred), collects **all** Hindi/English/Telugu audio tracks from every variant, keeps target-language subtitles (regular + SDH), and merges everything into one clean MKV.
- TV pipeline: same track selection and cleanup per episode file.
- Skip-remux fast path: files that already contain only target-language audio are tagged and renamed in place — no unnecessary remux.
- Safety model: working-copy mirroring (sources never modified by the remux path), atomic temp-file writes, `--dry-run` preview for every mode.

**Standalone modes**
- `--cleantags` — strips promotional/watermark tags and attachments in place; with API keys configured, embeds full metadata (genre, director, writers, top-10 cast with characters, synopsis, certification, IMDB rating, franchise collection; TV show/season/episode tag levels) from TMDB + OMDb.
- `--coverart` — embeds posters as MKV cover art via a local-file → TMDB → fanart.tv → OMDb chain with English-first poster language; per-run HTML review gallery and audit copies; persistent ledger so completed files are skipped instantly (`--coverart-overwrite` to redo).
- `--rename` / `--rename-undo` — FileBot renaming of messy downloads into the canonical format, with noise-stripped lookup queries, optional library organization (`--rename-into`), a full history CSV, and one-command undo.
- `--subtitles` — downloads missing subtitles from OpenSubtitles.com as sidecar `.srt` files (moviehash + IMDB matching, quota-aware, configurable languages).

**Quality of life**
- `MediaCleanup.toml` configuration — no hardcoded paths; git-ignored (API keys stay private) with a committed example template.
- `--filter` — case-insensitive glob scoping (folder or filename) for every mode.
- `--validate-keys` — one-call verification of all configured API keys.
- Colored log output and end-of-run summary tables when [rich](https://pypi.org/project/rich/) is installed (`--no-color` to disable).
- Documentation set: usage guide, configuration reference, illustrated README.
