<div align="center">

# ⚙️ MediaCleanup — Configuration Reference

**Every `MediaCleanup.toml` key, and what it switches on.**

[📖 Usage guide](USAGE.md) · [🏠 README](../README.md) · [📝 Changelog](../CHANGELOG.md)

</div>

<br>

All configuration lives in **`MediaCleanup.toml`**, which must sit in the same folder as `MediaCleanup.py`. The script resolves it relative to its own location, so it works no matter which directory you run from.

Setup: `copy MediaCleanup.example.toml MediaCleanup.toml`, then edit.

> [!CAUTION]
> `MediaCleanup.toml` is git-ignored because it contains your private API keys and machine-specific paths. Never commit it; share `MediaCleanup.example.toml` instead.

> [!TIP]
> Use **single-quoted literal strings** for Windows paths — backslashes need no escaping: `movies_root = 'D:\Media\Movies'`.

**Relative paths resolve against the script folder** (not your current directory). The example config uses `runtimes\mkvtoolnix` and `runtimes\FileBot\filebot.exe`, so a fresh clone works as soon as the tools are dropped into `runtimes\` — see [runtimes/README.md](../runtimes/README.md). Absolute paths are used as-is.

## 🗺️ What each section controls

| Section | Controls | Required |
|---|---|---|
| 🔧 [`[tools]`](#tools) | Where MKVToolNix lives | 🔴 Yes |
| 🎞️ [`[filebot]`](#filebot) | Optional FileBot renaming | ⚪ No |
| 📁 [`[paths]`](#paths) | Movie, TV and output folders | 🔴 Yes |
| 🏷️ [`[naming]`](#naming) | Prefix stripping, and the LOCAL-name fallback | ⚪ No |
| 🔄 [`[updates]`](#updates) | The once-a-day "newer release" notice | ⚪ No |
| 🔤 [`[languages]`](#languages) | Which audio languages are kept; `und` detection | ⚪ No |
| 🔑 [`[coverart]`](#coverart) | TMDB, fanart.tv and OMDb keys — posters, tags, identification | ⚪ No (strongly recommended) |
| 💬 [`[subtitles]`](#subtitles) | OpenSubtitles credentials | ⚪ No |

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
| `db` | No | Movie database for FileBot lookups. Default: `"TheMovieDB"`. TV uses TheTVDB first, with TMDB and then TVmaze as fallbacks for a series TheTVDB cannot identify. |

> [!NOTE]
> FileBot is optional. Without it, films are still identified through TMDB and OMDb and can still be named, but TV episodes are renamed only through FileBot.

## `[paths]`

`movies_root`, `tv_root`, and `output_root` are **required** (`output_root` is unused in `--inplace` runs).

| Key | Description |
|---|---|
| `movies_root` | Source movies folder, scanned recursively for `.mkv`. |
| `tv_root` | Source TV folder, scanned recursively. |
| `work_root` | **Legacy — ignored.** Remuxing reads sources directly (mkvmerge never modifies its inputs). Old configs keep working; the key can be removed. |
| `output_root` | Output folder. Remuxed files land here, mirroring the source folder structure. |

The `--input` CLI flag overrides `movies_root`/`tv_root` for a single run without editing the TOML.

## `[naming]`

| Key | Required | Description |
|---|---|---|
| `strip_prefixes` | No (default `[]`) | Extra filename prefixes to remove before the title is read. Prefixes that look like a web address (`www.something.net - …`) are handled automatically; use this for names stamped on with no domain suffix (`SomeDistributor.The.Film.2024.1080p.mkv`). Matched case-insensitively, longest first, chained up to three deep, with a guard that stops it eating a short title. Also used by `--mp4tomkv` when deciding whether a subtitle cue or chapter name is an advertisement, so a name listed here is recognised in both places. |
| `local_fallback` | No (default `true`) | When **no database knows a title** (every source that could be asked found nothing), name and tag the file from facts in the file itself — the title and year its filename states, and the resolution, codec and audio languages read from the video — and report it `LOCAL`. Nothing is invented (no id, poster or description). Never applies to a title with several possible matches or when no database could be reached. Per-run override: `--no-local-name`. See [Titles no database knows](USAGE.md#titles-no-database-knows). |

```toml
[naming]
strip_prefixes = ["SomeDistributor", "AnotherName"]
local_fallback = true
```

## `[updates]`

| Key | Required | Description |
|---|---|---|
| `check` | No (default `true`) | Once a day, in the background, look for a newer published release and print a one-line notice at the end of a run. The answer is cached in `logs\update_check.json`. Per-run override: `--no-update-check`. `--check-update` always works regardless. See [Versions and updates](USAGE.md#versions-and-updates). |

```toml
[updates]
check = true
```

A **private** repository needs a read-only token in the `MEDIACLEANUP_GITHUB_TOKEN` environment variable (not in this file, so it cannot be committed by accident).

## `[languages]`

| Key | Required | Description |
|---|---|---|
| `targets` | No (default `["hin", "eng", "tel"]`) | Audio languages to **keep** — all others are stripped during remux. **List order = audio track order** in output files. Accepts every form — ISO 639-1 (`ko`), ISO 639-2 B/T (`kor`/`fra`), full English names (`Korean`) — against the complete built-in ISO 639 registry (189 languages). |
| `detect_undetermined` | No (default `true`) | Identify tracks tagged `und` instead of discarding them. A lone unlabelled audio track takes the title's TMDB original language; unlabelled text subtitles are identified from their own text. Anything that cannot be called confidently stays `und`. Per-run override: `--no-lang-detect`. |

Everything language-related derives from this list: track detection (including native-script track names for Indian languages), the display names in the filename `[...]` bracket, which subtitles are kept, what `--audio-langs`/`--force-audio-lang` accept, and the poster-language preference for cover art (English always first, then your targets). The video track language is set separately from the title's TMDB original language (override: `--force-video-lang`).

## `[coverart]`

API keys used by **both** `--coverart` (poster fetching) and rich metadata tagging (genre/director/actors/synopsis embedded during tag cleaning). All keys optional — an empty value disables that source. With no keys at all, `--coverart` still works using local poster files only, and tag cleaning writes basic tags.

Verify your keys anytime with `python MediaCleanup.py --validate-keys`.

> [!WARNING]
> Watch the key formats: TMDB and fanart.tv keys are 32 hex characters; OMDb keys are 8. If validation says a key is invalid, check you didn't swap them.

| Source | Posters | Tags | Identifies titles | Free tier |
|---|---|---|---|---|
| 🔵 **TMDB** | ✅ primary | ✅ primary | ✅ films and shows | generous |
| 🟣 **OMDb** | ✅ last resort | ✅ thinner, by id | ✅ second source for **films** | ~1,000 requests/day |
| 🟠 **fanart.tv** | ✅ first fallback | — | — | personal key |
| 🟢 **TVmaze** | — | — | ✅ third source for **shows** (via FileBot) | no key needed |

| Key | Description |
|---|---|
| `tmdb_api_key` | TMDB API key (v3 auth). Free signup: <https://www.themoviedb.org/settings/api>. **Primary source** — best coverage, especially for Indian/regional cinema; serves pre-sized 780×1170 posters. |
| `fanarttv_api_key` | fanart.tv project key: <https://fanart.tv/get-an-api-key/>. Curated high-quality art; first fallback. TV lookups require `tmdb_api_key` too (TMDB translates to the TVDB ID fanart.tv uses). |
| `omdb_api_key` | OMDb key (free tier 1,000 req/day): <https://www.omdbapi.com/apikey.aspx>. Last resort for posters (a ~300px image). It is also the **second source for identifying a film** when TMDB has no match, and supplies the tags for a film only OMDb knows. |

## `[subtitles]`

Credentials for the `--subtitles` mode (OpenSubtitles.com REST API). All three credentials are required for downloads; without them the mode refuses to run (dry-run works regardless).

| Key | Description |
|---|---|
| `api_key` | OpenSubtitles API key — register a consumer at <https://www.opensubtitles.com/en/consumers>. |
| `username` / `password` | Your opensubtitles.com account login (downloads are per-user; free ≈ 20/day, VIP ≈ 1000/day). |
| `languages` | List of ISO 639-1 codes to download, default `["en"]`. One language → sidecar named `<mkv stem>.srt`; extra languages get `.hin.srt`-style suffixes. |

---

## 🧪 A complete example

Every section in one file, with the defaults spelled out. Copy `MediaCleanup.example.toml` rather than this block — it carries the same keys with more comments.

```toml
[tools]
mkvtoolnix_dir = 'runtimes\mkvtoolnix'

[filebot]                              # optional
exe = 'runtimes\FileBot\filebot.exe'
db  = "TheMovieDB"

[paths]
movies_root = 'D:\Media\Movies'
tv_root     = 'D:\Media\TV'
output_root = 'D:\Media\Fixed'

[naming]
strip_prefixes = []                    # names stamped on files with no web address
local_fallback = true                  # name unknown titles from the file itself (LOCAL)

[languages]
targets = ["hin", "eng", "tel"]        # kept audio languages; list order = track order
detect_undetermined = true             # work out what 'und' tracks really are

[coverart]                             # every key optional
tmdb_api_key     = ""                  # primary source for everything
omdb_api_key     = ""                  # second film source, thinner tags, last-resort posters
fanarttv_api_key = ""                  # curated posters

[subtitles]                            # --subtitles only
api_key   = ""
username  = ""
password  = ""
languages = ["en"]
```

---

## What stays in the script

Behavioral constants are deliberately **not** in the TOML — they define what the tool *is*, and changing them means changing the spec:

- Video/audio/subtitle codec preference rankings
- Resolution targets (2160p/1080p/720p)
- Audio-exclusion tokens (commentary, descriptive, ...)
- Output naming formats and FileBot format strings
- Default similarity threshold (0.88 — overridable per run via `--similarity-threshold`)
