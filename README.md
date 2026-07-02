# MediaCleanup Enhanced

Windows MKV media cleanup, merge, and tagging tool built on **MKVToolNix**, with optional **FileBot** renaming and **cover art** embedding.

For **movies**: scans a folder, groups variant releases of the same movie (e.g. a Telugu release + a Hindi/English release), selects the best video track (HEVC preferred), collects **all Hindi/English/Telugu audio tracks** from every variant, keeps target-language subtitles, and merges everything into one clean MKV.

For **TV**: applies the same track selection and tag cleaning to each episode file.

Plus two standalone maintenance modes:

- `--cleantags` — strip promotional/watermark tags, attachments, and junk track names in-place, no remux.
- `--coverart` — fetch movie/show posters (TMDB → fanart.tv → OMDb, or a local `poster.jpg`) and embed them as MKV cover art.

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10/11 | Uses Windows long-path handling; paths are Windows-style |
| Python 3.11+ | Standard library only — no pip installs required |
| [MKVToolNix](https://mkvtoolnix.download/) | `mkvmerge` + `mkvpropedit` (+ `mkvextract` for IMDB tag reads) |
| [FileBot](https://www.filebot.net/) | *Optional* — canonical renaming via TheMovieDB/TheTVDB |
| [Pillow](https://pypi.org/project/pillow/) | *Optional* — downscales oversized local posters for `--coverart` |

## Quick start

```bat
:: 1. Get the code
git clone <this-repo> && cd MediaCleanup

:: 2. Create your config (git-ignored; holds your paths + API keys)
copy MediaCleanup.example.toml MediaCleanup.toml
notepad MediaCleanup.toml

:: 3. Validate tools and folders
python MediaCleanup_Enhanced.py --self-check

:: 4. Preview what would happen (nothing is written)
python MediaCleanup_Enhanced.py --dry-run --verbose

:: 5. Run
python MediaCleanup_Enhanced.py
```

## Common commands

```bat
python MediaCleanup_Enhanced.py --movies                          :: movies only
python MediaCleanup_Enhanced.py --tv                              :: TV only
python MediaCleanup_Enhanced.py --movies --input "D:\Downloads"   :: specific folder
python MediaCleanup_Enhanced.py --audio-langs Telugu Hindi        :: keep only these languages
python MediaCleanup_Enhanced.py --cleantags                       :: clean tags in-place, no remux
python MediaCleanup_Enhanced.py --coverart                        :: embed cover art in-place
python MediaCleanup_Enhanced.py --rename --movies --input "D:\Downloads"  :: FileBot-rename downloads
python MediaCleanup_Enhanced.py --subtitles                       :: download missing sidecar subs
python MediaCleanup_Enhanced.py --validate-keys                   :: test all configured API keys
python MediaCleanup_Enhanced.py --tv --force-audio-lang 1 Hindi   :: fix "und" mislabeled tracks
```

## Output naming

```
Movies:  The Film (2021) - tt1234567 - WEB-DL.1080p.x265 - [Hindi + English + Telugu].mkv
TV:      Show Name (2008) - S01E01 - Pilot - 1080p.x265 - [English].mkv
```

## Safety model

- Source files are copied to a working folder before any remux; originals are untouched by the remux path.
- Output is written to a `.tmp` file, then atomically renamed into place.
- `--dry-run` previews every action, including mkvmerge command lines, without writing anything.
- In-place modes (`--cleantags`, `--coverart`, and the skip-remux fast path) edit metadata/attachments only — never the media streams.

## Documentation

| Document | Contents |
|---|---|
| [docs/USAGE.md](docs/USAGE.md) | Full usage guide — every flag, workflows, recipes, troubleshooting |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `MediaCleanup.toml` key explained |
| [docs/PROMPT.md](docs/PROMPT.md) | Complete behavioral specification — processing rules, track scoring, naming formats. Doubles as an AI-assistant context file for maintaining the script |

## License

[MIT](LICENSE) — free to use, modify, and share.
