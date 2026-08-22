# Changelog

All notable changes to MediaCleanup are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [1.6.1] — 2026-08-22

### Fixed
- **Another film's metadata, poster and IMDB id attached to movies whose title is a substring of a more popular one.** TMDB's `year` search parameter only re-ranks results, it does not filter them — a search for `The Film` with `year=2026` still returns the far more popular `Franchise: The Film` (2017) first, and the code took `results[0]` without checking. The FileBot rename was protected by its hard year filter, but the metadata, cover art, dry-run prediction and identity-grouping paths were not. Movie and series searches now require a result whose release year actually matches (exact, then ±1 for release-date drift), and return nothing when a year is known and none matches.

## [1.6.0] — 2026-08-10

### Changed
- **Filename prefix list moved to configuration.** The list of distributor/site names stripped from filenames is no longer shipped in the source — it now lives in `[naming] strip_prefixes` in your own `MediaCleanup.toml`, empty by default. The generic `www.*`/domain rule still works out of the box with no configuration.
- **Documentation reframed around personal media.** Wording throughout the project, docs and screenshots now describes what the tool actually does — reorganising media you already own — rather than framing it around any particular source of files.

### Added
- **"Intended use" section** in the README: the tool downloads no media, circumvents no copy protection, and only rewrites container metadata and track selection for files you point it at.
- **Third-party service credits**, including the attribution required by the TMDB API terms, plus fanart.tv, OMDb and OpenSubtitles.
- Screenshots regenerated using a public-domain film (*Night of the Living Dead*, 1968).

## [1.5.1] — 2026-08-10

### Fixed
- **Films whose title ends in a year were mis-parsed** — a name like `The.Film.1984.2020.1080p...` carries two year tokens; the first was read as the release year, truncating the title. The year filter built from it then excluded the correct match, which FileBot had already found. The last token of an adjacent year run is now the release year, keeping earlier ones in the title. Also fixes titles that are *entirely* a year, which previously lost their name altogether.
- **Title-with-year retry** — when a filename carries no release year (`The.Film.1984.1080p...`), the parsed year is retried as part of the title, verified against TMDB first (the film found must carry the year in its own title) and pinned to that film's real year. Without the verification an unconstrained search returns a different film in the same series.
- **Release tags mistaken for a domain** — `The.Film.Name.2025.1080p.WEB-DL.Hindi.TV-DL.Chinese...` matched `...Hindi.TV` as a site domain (`tv` is a TLD, and the following `-` passed the guard), leaving the title as `DL Chinese`. Domain detection is now limited to three labels and rejects a TLD followed by a hyphen.

## [1.5.0] — 2026-08-07

### Added
- **Dry-run shows the real final filename.** Previews reported the intermediate remux target, omitting everything the database rename adds — `Night of the Living Dead (1968) - WEB-DL.1080p.x264 - [Hindi + English].mkv` where a real run produces `Night of the Living Dead (1968) - tt0063350 - WEB-DL.1080p.x264 - [Hindi + English].mkv`. `--dry-run` now resolves the canonical title and IMDB id (cached TMDB call) and reports the predicted final name in the log and the summary table, for the skip-remux path as well.
- **`--preview-exact`** — with `--dry-run`, asks FileBot itself for each name instead of predicting it. Authoritative but launches a JVM per item (~4 s vs ~1 s); both modes produced identical names in testing.

## [1.4.2] — 2026-08-06

### Fixed
- **Wrong show's metadata and poster embedded into TV episodes** — the tag and cover art paths searched TMDB by show name with the year deliberately dropped, so a 2026 series resolved to a same-named 1998 sitcom (TMDB's most popular match for that name) and embedded its genre, network, cast, episode titles and poster. Both paths are now year-constrained via `resolve_tv_series_tmdb_id()`; when no series matches the year, nothing is written rather than another show's data.

### Added
- **`--clear`** — removal modifier for the standalone modes. `--cleantags --clear` wipes all tags, the segment title and every track name, writing nothing back (fully offline, no database lookups, no rename). `--coverart --clear` deletes embedded cover art and removes the file's ledger row so a later run re-fetches it. Both honor `--dry-run`, `--filter` and `--input`.

## [1.4.1] — 2026-08-06

### Fixed
- **TV episodes matched to the wrong same-named show** — a 2026 regional series was renamed into a same-named 2024 documentary, complete with a doubled year. Four series shared that name, and the one being processed had no TheTVDB entry at all (`tvdb=None`), so FileBot's fuzzy search silently substituted another. TV lookups are now year-constrained, and when TheTVDB has no matching series the show is resolved on TMDB and FileBot is pinned to that exact series id.
- **Doubled year in TV names** (`Show Name (2024) (2024)`) — TheTVDB disambiguates same-named series by embedding the year in the series name; the format now strips a trailing `(YYYY)` from the show name before appending the year. Applies to episode filenames and `--rename-into` folders.

## [1.4.0] — 2026-08-05

### Fixed
- **Variant releases were not being merged** — grouping compared raw filenames, so `The Film 2025 Hindi DD5.1-224Kbps + Kannada Dual Audio HD 1080p ESub.mkv` and `The.Film.2025.WEB-DL.720p.Multi.Audio.ESub.mkv` scored 0.382 similarity (threshold 0.88) and were processed as two separate files instead of one merged release. Grouping now compares the **inferred title + year**, which both files resolve to identically.

### Added
- **Identity-based grouping** — releases whose titles differ too much to match (a main title alone vs the same title with its subtitle) are merged when they resolve to the same IMDB/TMDB id. Free signals first (id in filename, folder, or MKV tags), database lookup only for folders with more than one candidate, results cached in `logs/movie_identity.csv`.
- **Runtime guard** — a merge candidate is split into same-duration cohorts before merging (±1%). Combining releases of different length (alternate cut, extra logos, PAL speed-up) would desync the added audio for the whole film; those files are now processed separately with a clear warning.

## [1.3.2] — 2026-07-29

### Fixed
- **Wrong-year matches** — a 2026 film was renamed as a same-titled film from 1984. Movie lookups are now constrained to the filename year (±1 for release-date drift), so a same-title film from another year can never be matched. When nothing matches under the constraint the file is reported FAILED instead of silently renamed to a wrong guess. TV is never year-constrained.
- **Distributor prefixes without a valid TLD** — names stamped onto filenames with no domain suffix (`SiteName.Foo.The.Film.2024...`) are now stripped from movie and TV name inference, from a user-supplied list (longest-match-first, chained, with an over-strip guard so `SiteName.Up.2009` still yields `Up`).

## [1.3.1] — 2026-07-24

### Fixed
- **Release-site prefixes broke identification** — filenames like `www.example-site.net_-_The.Film_1927_...` produced the lookup query `www example-site net - The Film (1927)`, which no database could match. Leading `www.*`, `domain.tld`, and `[www.site.com]` prefixes are now stripped from movie *and* TV name inference. Legitimate dotted titles whose second token happens to be a valid TLD (`in`, `to`, `me`, …) are explicitly protected.
- **FileBot query fallback** — when a lookup using our inferred title finds no match, FileBot is now retried once without `--query`, letting its own release-name parser identify the file (e.g. `GroupName.Extra.The.Film.2014...` → the correct `The Film (2014) - tt…`).

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
- `--cleantags` — strips promotional/advertising tags and attachments in place; with API keys configured, embeds full metadata (genre, director, writers, top-10 cast with characters, synopsis, certification, IMDB rating, franchise collection; TV show/season/episode tag levels) from TMDB + OMDb.
- `--coverart` — embeds posters as MKV cover art via a local-file → TMDB → fanart.tv → OMDb chain with English-first poster language; per-run HTML review gallery and audit copies; persistent ledger so completed files are skipped instantly (`--coverart-overwrite` to redo).
- `--rename` / `--rename-undo` — FileBot renaming of messy downloads into the canonical format, with noise-stripped lookup queries, optional library organization (`--rename-into`), a full history CSV, and one-command undo.
- `--subtitles` — downloads missing subtitles from OpenSubtitles.com as sidecar `.srt` files (moviehash + IMDB matching, quota-aware, configurable languages).

**Quality of life**
- `MediaCleanup.toml` configuration — no hardcoded paths; git-ignored (API keys stay private) with a committed example template.
- `--filter` — case-insensitive glob scoping (folder or filename) for every mode.
- `--validate-keys` — one-call verification of all configured API keys.
- Colored log output and end-of-run summary tables when [rich](https://pypi.org/project/rich/) is installed (`--no-color` to disable).
- Documentation set: usage guide, configuration reference, illustrated README.
