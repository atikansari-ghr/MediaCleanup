# Changelog

All notable changes to MediaCleanup are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [1.12.0] — 2026-10-22

This release makes the tool look after itself: it can tell you when a newer release exists, install it with every file verified, repair a damaged install, keep its helper tools current, and be installed from one command.

### Added
- **`--version`** prints the tool's version and the versions of what it runs on: Python, MKVToolNix, FileBot, `rich`, Pillow, and the optional `ffmpeg` and `x265`. It needs no configuration, so it works on a fresh install. `ffmpeg` and `x265` are reported but nothing calls them yet; a missing one is not an error.
- **`--check-update`** compares the installed version with the latest *published* GitHub release and prints the changelog entries since. It only reads. Exit code `0` is up to date, `10` a newer release exists, `1` the check could not be made. A private repository needs a read-only token in `MEDIACLEANUP_GITHUB_TOKEN`.
- **A once-a-day update notice.** Normal runs look for a newer release in the background and print one line at the end if there is one. It never delays a run, the answer is cached in `logs\update_check.json`, a failed check is not retried for an hour, and `--dry-run` stays offline. Off with `--no-update-check` or `[updates] check = false`.
- The script now carries a `__version__`, kept in step with the newest CHANGELOG entry.
- **`--update` / `--update-to TAG`** installs a published release. Every file is checked against the git hash GitHub lists for that tag (so it works for every release, with no separate checksum file) and nothing is written unless all of them match. Only files the release itself contains are written — never `MediaCleanup.toml`, `logs\`, `backup\` or the tools in `runtimes\`. Whatever is replaced is copied to `backup\` first and a failure part-way restores it. Files you edited are flagged in the plan; settings new in `MediaCleanup.example.toml` are reported, never applied. A git clone is updated with git (fast-forward, or a deliberate checkout of an older tag). Shows a plan and asks first; `--dry-run` only shows the plan; `--yes` is for unattended use. `--update-to` is the only way to move to an older release.
- **`--repair`** brings an install back to a working state: restores missing or modified project files from the release you have installed (backed up first), recreates folders, creates `MediaCleanup.toml` from the example if it is missing, reports a config that does not parse (never overwriting it), and re-installs a missing MKVToolNix. `--files-only` limits it to the project files.
- **`--update-runtimes` and `--install TOOL`** keep the tools current. MKVToolNix is updated from the official portable build, SHA-256 verified; ffmpeg is opt-in (`--install ffmpeg`) and kept updated once installed, on the channel and variant you already have (it carries libx265, so x265 comes with it); `rich` and Pillow are upgraded with pip. FileBot (licensed), a standalone x265 (third-party) and Python (cannot replace the running interpreter) are **reported only**. Downloads come only from `mkvtoolnix.download`, `www.gyan.dev` and `pypi.org`; a replaced tool is kept in `runtimes\_previous\` and put back automatically if the new one does not run.
- **`install.ps1`**, a one-command installer, also attached to each release: finds or installs Python (winget, per user), unpacks the release, verifies it with `--repair --files-only`, installs MKVToolNix, writes a first `MediaCleanup.toml` from your answers, and creates a launcher. Re-running it on an existing install updates it and never touches your config. It never calls `exit` under `irm | iex`, so it cannot close your window.

### Fixed
- Two installs or updates of the same tool within one second shared a rollback folder name, which could restore the wrong content. Rollback and backup folder names are now always unique.

### Documentation
- New diagram `docs/images/lifecycle.svg`: install, check, update, repair and runtime updates, and a matrix of exactly what each command may change. The README gains a one-command install and an "Install, update and repair" section; the usage guide gains `--update`, `--repair`, `--update-runtimes`, `--install` and the installer, with new Troubleshooting rows; `runtimes\README.md` describes `--install` and `--update-runtimes`.

## [1.11.0] — 2026-10-22

### Added
- **More sources when TMDB does not know a title.** Identification used to stop at TMDB for films and at TheTVDB/TMDB for shows, so anything those lacked (a title released straight to a streaming service, say) was left as it was. The chain is now:
  - **Films:** TMDB, then **OMDb** (needs `omdb_api_key`; it is IMDB-backed, so it covers titles TMDB lacks).
  - **Shows:** TheTVDB and TMDB as before, then **TVmaze** (no key needed), held to the same series-name check.
  - A source is passed over only when it found **nothing**. If it found several titles the chain stops and asks (`--pick`), because another database would only add more guesses; and if a source could not be reached at all, that is never treated as "not found".
  - Every hit is verified before it is used: the title must match exactly or as a whole-word prefix, the year must be within one for films, and the series name must match for shows. The log names the source that identified each title.
  - A film OMDb identifies is renamed with this script's own name template, `Title (Year) - ttNNNNNNN - …`, so it does not depend on FileBot reaching OMDb. The same applies to a film chosen with `--imdb` or `--pick` that only OMDb lists: if FileBot cannot serve the id, OMDb supplies the name. Tags for such a film come from OMDb's record of that id — thinner than TMDB's (no collection, no original language) but never a guess.
- **A title no database knows is named from its own file** instead of being left with its release name. When every source that could be asked found nothing, the file is renamed from facts that are in it — the title and year its filename states, and the resolution, codec and audio languages read from the video — e.g. `Movie (2023) - WebRip.1080p.x264 - [Hindi + English].mkv`, and for an episode `Show Name - S01E02 - 1080p.x264 - [English].mkv`. Its tags are cleaned as usual. Nothing is invented: no id, no poster, no synopsis, no cast.
  - It is reported as **`LOCAL`**, separate from `OK`, and every such rename is appended to `logs\local_named.csv` (old path, new path, why), so a name no database confirmed can always be told from one that was. It carries no id, so a later run renames it normally once a database knows the title.
  - It applies **only** when the answer is "nothing found". A title with several possible matches is never named this way (it is listed for `--pick`), and neither is one when no database could be reached. A file with no usable title and year, or no season and episode number, is left as it is and the reason is shown.
  - Off with `--no-local-name` or `[naming] local_fallback = false`.
  - `--dry-run` previews the `LOCAL` name; for a show TMDB does not know, a dry run cannot know whether TheTVDB or TVmaze would find it, and says what happens if neither does.

### Changed
- **A film is no longer tagged from a title search.** Rich tags (genre, director, cast, synopsis) were fetched by an id when the file carried one and otherwise by a title search that took the top hit — which, for a title shared by several films or a title no database knows, embedded another film's cast and synopsis. They are now fetched by id only: a film with no verified id gets basic tags.
- `--rename` identifies a film through the same chain, so a film only OMDb lists can be renamed (in place or with `--rename-into`). It never names a file from the file alone; that fallback belongs to the processing modes and `--cleantags`/`--cleanmetadata`.
- OMDb's search results are kept for the run; the free tier allows about a thousand requests a day.

### Documentation
- **New diagrams** in `docs/images/`: `pipeline.svg` (the seven stages, the fast path that skips the remux, and a chart of which command runs which stages) and `identify.svg` (how a title is identified through the source chain, and what happens when every source finds nothing).
- **README rewritten as a visual user guide:** feature table, "which command do I need?" table, a status legend for the summary table (OK, LOCAL, PARTIAL, SKIP, FAIL), the identification rules, and callouts for the safety model.
- **Usage guide:** a "where to look" index, a stage-by-stage description of a run, a "reading the results" section, a symptom table at the top of Troubleshooting, and new entries for `LOCAL` names and unreachable databases. Corrected two stale statements (cover-art source chain; `und` track handling).
- **Configuration reference:** a section map, a table of what each API key unlocks, and a complete annotated example.

## [1.10.0] — 2026-10-04

This release also contains everything in 1.6.1 through 1.9.2 below. Those were development milestones and were never tagged on their own, so 1.10.0 follows 1.6.0 directly.

### Fixed
- **A TV episode could be renamed as a different show.** The rename searched TheTVDB by title, and the safeguards around that search all had gaps. The year filter does nothing when the filename carries no year. The name filter ignores punctuation, so `Name!` passed for `Name`. And a final "retry without query" step let FileBot parse the filename itself, which for a title nothing matched landed on whichever show it found: an episode of a show TMDB has never heard of was renamed to an unrelated 2024 series. A series is now **identified before it is renamed**, by the same exact-title check used for TV language, metadata and posters, and FileBot is given the series **by id** — a direct lookup with no search, so there is nothing left for it to substitute. TheTVDB is still the first source, addressed by the series' TheTVDB id; the TMDB entry is the fallback for a series TheTVDB lacks or holds broken.
  - **When more than one series shares the exact title**, the file is left unrenamed and reported `PARTIAL` with its numbered candidates, and `--pick` resolves it — the same as for films. One pick now settles a show's rename, language, metadata and poster together.
  - **A show TMDB does not know** is still looked up on TheTVDB, but only by name and year, and the fuzzy retry is gone for series. If that finds nothing the file is reported as not renamed instead of being given another show's name.
  - A renewed show whose TheTVDB search used to fail now renames by id. Its name carries the series' first-air year, which is also what the dry-run preview predicts.
  - Applies to the main pipeline, standalone `--rename`, `--cleantags` and `--cleanmetadata`; the dry run reports the same refusal.
- **A `--pick` for a show was lost partway through a run.** Picks were keyed by the filename's year, which changes when the file is renamed (`Show` becomes `Show (2026)`), so later steps no longer found it. A show is identified by title alone, so its key now ignores the year.

## [1.9.2] — 2026-10-03

### Fixed
- **TV posters were found by a title search of their own, with two faults.** A renewed show got **no poster at all**: the lookup required the filename's year to match the series' first-air year, but a release carries the year *that season* aired, so a season released years after the debut missed. And a show whose filename carried no parenthesised year fell through to an unconstrained search that took the top hit, so a title shared by several series got whichever the database ranked first. Cover art now identifies the series with the same exact-title check already used for TV language and metadata, which is year-agnostic and refuses to guess: a renewed show gets its own poster, and a title shared by several series is left **exactly as it is**, with its numbered candidates listed for `--pick`. The poster fetch is id-only, as the film path became in 1.9.1.
  - A show that already has an IMDB id in the filename, folder or tags is used as-is, and the OMDb source still works from it without a TMDB lookup.
  - One `--pick` now settles a show's language, metadata and poster together, because all three identify it the same way.
- "Identifying N film(s) from your picks" now says "title(s)", since picks cover shows too.

## [1.9.1] — 2026-10-03

### Fixed
- **Cover art could embed a different film's poster.** When several films share a title and a year, the poster was looked up by title alone and the top search hit was taken, so an ambiguous film was given whichever film's artwork the database ranked first — silently, and in place of the cover that came with the file. In a test the guessed poster was 306 KB and the correctly identified film's was 129 KB. Cover art now requires the film to be pinned to one IMDB id first, by the same check the rename uses, and a film that cannot be pinned is **left exactly as it is**: no poster embedded, no existing cover replaced, nothing recorded in the ledger. It is reported as a skip with the reason, and its numbered candidates are listed so `--pick` can resolve it. The poster fetch itself is now id-only, so the title-search guess cannot come back through another caller.
  - Applies to standalone `--coverart`, the cover step at the end of `--movies`/`--tv`, and `--cleanmetadata`. A film that is identified but has no poster anywhere is likewise left untouched.
  - A local `poster.jpg` next to the file still wins, since that is an explicit choice rather than a guess.
- **`--rename` and `--mp4tomkv` printed numbered candidates that `--pick` could not find**, the same gap fixed for `--cleantags` in 1.9.0. All three modes that list candidates now save the list.
- A film passing through several steps in one run no longer prints its full candidate list each time; later steps refer back to the numbers already shown.
- "Third-party cover found — replacing" was logged before the check that decides whether anything is replaced. It is now logged only when a poster has actually been found.

## [1.9.0] — 2026-10-03

### Added
- **`--cleanmetadata` — `--cleantags` and `--coverart` as one command.** Cleans tags, embeds metadata and renames in place, then embeds cover art on the final filenames, with no remux. `--filter`, `--input`, `--dry-run` and `--coverart-overwrite` apply; the two modes it combines are unchanged. With `--clear` it undoes both at once — every tag, the segment title and all track names wiped, the cover art and its ledger entry removed — and never renames.
  - **The cover art step is handed the files the first step produced** rather than rescanning. `--cleantags` may rename a file, and a `--filter` written for the old name would no longer match the new one, so a rescan would quietly skip exactly the files that had just been renamed.
  - **A film that could not be identified gets no poster.** When several films share a title and year the file is left unrenamed, and cover art is now skipped for it too: a poster chosen by title alone is whichever film the database ranked first.

### Fixed
- **`--cleantags` printed numbered candidates that `--pick` could never find.** The list was only saved at the end of the main pipeline, so any other mode offered a choice that could not be acted on. Saving the list and printing the `--pick` command is now one shared step used by every mode that can list candidates.
- **A `--cleantags` dry run never showed which films the real run would refuse.** The identity check only ran for real runs, so "dry run, read the numbers, then `--pick`" could not work for it. The dry run now performs the same read-only lookup and reports the same refusal.

## [1.8.4] — 2026-08-29

### Fixed
- **Renewed shows never got their `und` audio/video language resolved, or their genre/cast/director metadata.** The lookup required the filename's year to match the series' TMDB *first-air* year within ±1 — which holds for a show's first season, but a filename almost always carries the *current* season's air year, not the year the show debuted. A season 3 episode released three years after a series began missed by more than the tolerance and was silently skipped, in both the language-resolution path and the metadata-tagging path.
- Both now resolve a series by an **exact, year-agnostic title match** instead — the same safety rule already used for the FileBot rename fallback, just reached from the paths that were refusing too early. When more than one series shares that exact title, nothing is guessed: it goes into the same numbered `--pick` list used for ambiguous movies (see below), annotated with the language each candidate was made in and marked when it matches the file's own audio.
- The FileBot rename mechanism itself is untouched — it already resolves per-season years correctly via TheTVDB/TMDB and was not affected by this bug.

### Added
- **`--pick` now covers ambiguous TV shows too**, sharing the exact mechanism built for movies: numbered candidates, saved to `logs/pending_identity.csv`, read back rather than recomputed, one pick per title. The pending list now carries a `kind` column so a movie and a show of the same name can never collide.

## [1.8.3] — 2026-08-27

### Added
- **`--pick N …` — choose an ambiguous film by number.** Candidates are numbered across the whole run, so a preview ends with a command you can run as-is: `--pick 1 3` identifies two different films at once, one number each. Numbers are **written to `logs/pending_identity.csv` and read back**, never recomputed — a later search could rank differently, and then the same number would quietly mean a different film. The list is rewritten each run and removed once nothing is outstanding.
- Refusals now end with the number to use (`-> choose one of these with --pick, e.g. --pick 3`), and the run summary prints one suggested number per film.

### Changed
- `--imdb` remains for pinning a film by id without a preview first; `--pick` and `--imdb` are mutually exclusive.

## [1.8.2] — 2026-08-27

### Added
- **`--imdb ttNNNNNNN`** — identify the film in scope when its title is too ambiguous to resolve. The run must be narrowed to one film with `--filter`/`--input`, so it cannot stamp one id across a library. The id is written into the file's tags as part of the normal tag pass, so the film identifies itself from then on and never needs the flag again.
- **The refusal now shows enough to choose from.** Candidates are listed with the language the film was made in, its original title, release date, a one-line synopsis and a direct IMDB link — all of it already present in the search response, so it costs no extra lookups. Candidates whose language matches one the file actually carries are listed **first** and marked, which usually settles it at a glance: a release carrying Kannada audio against three same-titled films, only one of which is Kannada. The match only orders and annotates the list — it never decides, because a dubbed release would defeat it. The exact command to run is printed underneath.

### Fixed
- **Non-Latin text could kill the worker that logged it.** A Windows console is usually cp1252, and the tool legitimately prints text it cannot encode — a film's original title in Kannada or Telugu, a track name in its own script. That raised `UnicodeEncodeError` inside the logging handler. Unencodable characters are now replaced instead.

## [1.8.1] — 2026-08-27

### Fixed
- **A film could be renamed as a completely different film, discarding a correct IMDB id it already had.** A file whose name already carried the right id was renamed to an unrelated film with a similar title, and its tags overwritten with that film's genre, director and cast. Three faults combined:
  - **The IMDB id was known and never used.** The dry-run preview read it and predicted correctly; the rename passed only the title to the database. The id is now passed as a direct lookup (`--q ttNNNNNNN`), which resolves the film outright — no search, and no fallback that could substitute another title.
  - **The year filter could not disambiguate.** A one-word title plus a year matched a dozen films, all released inside the `y >= Y-1 && y <= Y+1` window, so the database's own ranking decided which one won. Films are now resolved to a single id before any rename: the year as a hard constraint, then an exact title match, then a title the database merely extends at a word boundary (`The Film` → `The Film: A Longer Subtitle`, but never `The Filmmaker`). Ampersands are matched through, so `A & B` still matches `A.And.B`.
  - **Ambiguity was resolved by guessing.** When more than one film survives, the file is now left **unrenamed** and reported as `PARTIAL`, listing each candidate with its IMDB id so the id can be added to the filename and the next run pinned exactly. A wrong rename is worse than none, because it also rewrites the tags and a later run then trusts the wrong id.
- Applies to every path that renames a film — the remux and skip-remux pipelines, the standalone `--rename` mode, and `--cleantags`. The dry run reports the same refusal, so the preview still matches what a real run does.

## [1.8.0] — 2026-08-25

### Added
- **`--mp4tomkv` — convert MP4/M4V into finished MKVs.** MP4 carries no Matroska tags and usually leaves every track `und`, so these files could not be tagged, language-labelled or cover-arted at all. The new mode remuxes them with `mkvmerge` (lossless, never re-encoded), muxes in any sidecar `.srt`, and then runs the ordinary finishing chain — tag cleaning, TMDB/OMDb metadata, language resolution, cover art and the database rename — so a release goes from `Some.Film.2026.1080p.WEBRip.x264-GRP.mp4` to `Some Film (2026) - tt… - WEBRip.1080p.x264 - [English].mkv` in one command. Sources are only ever read: the `.mp4` and `.srt` are always kept. Scoped by `--movies`/`--tv`/`--input`/`--filter` like the other standalone modes, with a ledger so re-runs skip work already done.
  - **Advertising cues are stripped from sidecar subtitles.** Some subtitles carry promotional cues at the very start or end, where they play over the film instead of translating it. Cues whose text is structurally an advert — a web address, or stock phrasing such as "downloaded from" or "please visit" — are removed when they fall in the first or last minute, so dialogue that happens to mention a web address mid-film is left alone. Each removal is logged. As with filename prefixes, no distributor or site names ship in the source: the names from `[naming] strip_prefixes` in your own config are folded into the match at runtime. This is a deliberate, narrowly-scoped exception to the G4 guarantee, the only place the tool edits stream content rather than metadata.
  - **Forced subtitles are detected and flagged.** A track carrying under two cues per minute only covers foreign dialogue, not everything; it gets the Matroska forced flag so players show it automatically over untranslated speech, and it is kept even though forced tracks are normally excluded, because dropping the only subtitle a film has is worse.
  - **Subtitle language comes from the subtitle text**, audio and video from the title's TMDB original language — MP4 supplies none of them.
  - **Chapters are preserved**, with any chapter *name* that advertises rewritten to a plain `Chapter NN`. (The main remux still strips chapters outright; that inconsistency is left as-is for now.)

## [1.7.3] — 2026-08-22

### Fixed
- **Files that were already correctly named were reported as not renamed.** FileBot answers `Skipped [X] because [X] already exists` and exits non-zero when a file already carries the name it would be given — indistinguishable from a real failure by return code. Such files were flagged `PARTIAL`. Source and destination being the same path is now recognised as work already done.
- **The bare-year blind spot reached the metadata and preview paths too.** `_show_metadata` and `predict_tv_final_name` also parsed only a parenthesised `(2026)`, so a `Show Name 2026` episode was previewed and tagged as `Show Name Extended` even after the rename itself was fixed. Both now use `split_show_year`. Where no year can be established at all, the series is resolved only by an exact, unambiguous title match; otherwise metadata is skipped rather than taken from another show.

## [1.7.2] — 2026-08-22

### Fixed
- **A series could be renamed as a different, similarly-named show.** FileBot's fuzzy search answers a query for `Show Name` with `Show Name Extended` — also a 2026 series, so the year constraint could not separate them — and because that lookup *succeeded*, nothing questioned it: the episode was renamed and tagged with the wrong show's episode titles. The lookup now also constrains the series **name**: a candidate whose name is not the one asked for is dropped (a trailing parenthetical is stripped first, so TheTVDB's `Show Name (2024)` and `Some Show (US)` still match). With no candidate left the attempt fails and the TMDB series-id fallback resolves the show by exact title. The constraint applies only to the attempt carrying our query — the later "retry without query", which exists for when the inferred title is wrong, is deliberately left unconstrained.
- **Bare-year show labels left the lookup unconstrained.** `infer_tv_components` returns either `Show (2026)` or a bare `Show 2026` depending on the release; two places parsed only the parenthesised form. For the bare form no year was found, so the year filter was empty *and* the TMDB fallback could not run — a file could be renamed to a same-named series from any year (a 2026 episode matched `Show Name! (2022)` in testing). Both now use `split_show_year`, and the resolved year is passed to the filter builder instead of being re-parsed from the raw label.

## [1.7.1] — 2026-08-22

### Fixed
- **Dry-run previews disagreed with what a real run produced.** Three separate causes, all now closed:
  - **Resolution tag.** The preview bucketed by raw pixel width while FileBot's `{vf}` normalises to a 16:9-equivalent height, so an ultra-wide 2582x1080 encode previewed as `1080p` and was renamed `1440p`. This script now owns the tag outright: it is computed once from the file's own video track and substituted into FileBot's format string in place of `{vf}`, so the preview and the rename cannot disagree. A frame is named for its **height** when that height is standard (within 5%, which absorbs coded padding — an encoder stores 1080 rows as 1088), and for its width class only when the height is non-standard because the frame is letterboxed. A 2582x1080 scope encode is therefore `1080p`: it has exactly 1080 rows, and naming it `1440p` would claim vertical detail it does not have.
  - **Series with no year in the filename were never rescued.** When TheTVDB cannot identify a show, the code falls back to pinning FileBot to the TMDB series id — but that fallback was gated on a year parsed from the filename, so it only fired for files an earlier run had already canonicalised. Releases still carrying their original names, which is exactly when the rescue is needed, dropped to a weaker retry and failed. A show can now also be resolved by name alone (`resolve_tv_series_by_name`), accepted only on an exact title match and only when a single series matches — two same-named series with no year to separate them is reported, not guessed.
  - **Failed renames were reported `OK`.** A rename failure returned the original path, indistinguishable from "no rename needed", so a run could report `OK: 16 | Failed: 0` while eight files silently kept their release names. Renames now report their outcome; such tasks show as **PARTIAL** with the reason (`not renamed: TheTVDB entry is broken (id 000000)`) and are listed after the summary.

## [1.7.0] — 2026-08-22

### Added
- **Tracks tagged `und` are now identified instead of discarded.** Some releases strip the language metadata from every track; such a file looks like it contains none of your target languages and is reported `NoAudioMatch`, even when the audio is in a language you keep. A single unlabelled audio track now takes the title's TMDB original language, and unlabelled text subtitles are identified from **their own text** — writing system first (decisive for Hangul, Thai, Hebrew, Greek, the Indic scripts, kana and Han), then function-word frequency for the alphabets several languages share. On a test release carrying one `und` audio track and 42 `und` subtitle tracks, all 42 subtitle languages were identified correctly, recovering the English, Hindi, Korean, Telugu and Chinese tracks that track-order guessing would have missed. Anything that cannot be called confidently keeps its `und` tag. Off with `--no-lang-detect` or `[languages] detect_undetermined = false`.

### Fixed
- **Corrected track languages were never written into remuxed output.** The merge builder has always accepted a per-part `languages` map, but nothing populated it — so `--force-audio-lang` (and now detected languages) affected track selection and naming while the remuxed file kept the original tags. The skip-remux path was unaffected. Both pipelines now pass the resolved language for every audio and subtitle track they include.
- **Track names for non-target languages** were written as raw ISO codes (`fre`) rather than display names (`French`), since the display map only covers configured targets.

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
