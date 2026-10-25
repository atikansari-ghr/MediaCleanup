# Contributing

Thanks for taking an interest. MediaCleanup is a small, careful tool, and its guiding rule is **constrain, verify, fail loudly: never guess**. Contributions that follow it are very welcome.

## What fits

- Fixes for incorrect names, tags, languages, posters or subtitles, with a way to reproduce them.
- Support for another source of metadata or subtitles, held to the same standard as the existing ones (identify exactly one title first, verify what comes back, refuse rather than guess).
- Documentation, diagrams and examples.

## What does not

- Anything that downloads, indexes or links to media itself, or to sources of unauthorised copies. MediaCleanup organises files you already own and contains no media.
- Behaviour that renames, tags or embeds on a best guess.
- Features that send your data anywhere other than the service you configured.

## Before you open an issue

- Run `python MediaCleanup.py --version` and include its output.
- Add `--dry-run` where you can: it shows what would happen and writes nothing.
- **Remove secrets.** Logs written by the tool mask API keys, passwords and tokens, but check what you paste. Never include `MediaCleanup.toml`.
- Please use placeholder titles in examples, or a public-domain film, rather than naming real releases or sites.

## Changing the code

```bat
git clone https://github.com/atikansari-ghr/MediaCleanup.git
cd MediaCleanup
python -m unittest discover -s tests -v
```

- The tool is a single file, `MediaCleanup.py`, on the Python standard library only (`rich` and `Pillow` are optional). Keep it that way.
- Match the surrounding code: its comment density, naming and idiom. Comments explain *why*, not what.
- Add or update a test in `tests/` for behaviour you change, and a line in `CHANGELOG.md` under `[Unreleased]`.
- Update `docs/USAGE.md` or `docs/CONFIGURATION.md` when behaviour or settings change, and keep screenshots current.
- Keep user-facing messages plain ASCII (the Windows console mangles typographic punctuation).
- Be careful with regular expressions and escape sequences in anything you paste through an editor or tool: a literal backspace once replaced a word boundary in three patterns. The test suite now fails if any control character appears in the source.
- Security-relevant changes (downloads, archives, logging, credentials) should say in the pull request what they protect against.

## Commits and pull requests

Small, focused commits with a clear message. Describe what changed and why; note anything you could not test (for example a real download against a live service).

By contributing you agree that your work is released under the project's [MIT licence](LICENSE).
