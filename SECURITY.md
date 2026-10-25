# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**
   (<https://github.com/atikansari-ghr/MediaCleanup/security/advisories/new>).

Include what you found, the version (`python MediaCleanup.py --version`), and the steps to reproduce it. You will get a reply as soon as the maintainer can, and a fix is released with credit to you unless you prefer otherwise.

## Supported versions

Only the **latest release** receives fixes. `python MediaCleanup.py --check-update` tells you whether you are current, and `--update` installs the newest release with every file verified.

## What this tool touches

MediaCleanup runs on your own machine and handles:

- **Your media files**: it reads them, rewrites their metadata, and writes new MKVs. Sources are only read unless you pass `--inplace`.
- **Your API keys and passwords**, in `MediaCleanup.toml` (TMDB, fanart.tv, OMDb, OpenSubtitles). That file is git-ignored and is never uploaded anywhere except, as the credential itself, to the service it belongs to.
- **Downloads** from a short list of named hosts: GitHub (the tool itself), `mkvtoolnix.download`, `www.gyan.dev`, `pypi.org`, and the metadata, poster and subtitle services you configure.

## How it is built to be safe

- **No shell, no `eval`/`exec`, no unpickling.** External programs are run with argument lists, never through a shell, and configuration is plain TOML.
- **Self-update verifies every file.** `--update` and `--repair` check each downloaded file against the git hash GitHub publishes for that release, write only files the release itself contains, never touch `MediaCleanup.toml`, `logs\`, `backup\` or your tools, back up what they replace, and roll back on any failure. Archive paths that try to leave their folder are refused.
- **Tool downloads are checksum-verified.** MKVToolNix and ffmpeg are fetched over HTTPS from their official hosts only and checked against a SHA-256 published beside them; the previous version is kept and restored if the new one does not run. Archives that contain links are refused.
- **Third-party links are not trusted blindly.** Image and subtitle links that come back from an API are only fetched over HTTPS from public addresses (never `localhost`, private or link-local ranges, including via redirects), and a subtitle link must be on OpenSubtitles' own domain.
- **Secrets stay out of logs.** API keys travel in URL query strings for TMDB, OMDb and fanart.tv, and `--log-file` records debug output, so every log line is passed through a redactor that masks configured keys, passwords, tokens and any `key=`, `token=` or `password=` value, in messages and in tracebacks.
- **GitHub tokens are scoped narrowly.** The optional `MEDIACLEANUP_GITHUB_TOKEN` is only sent to `api.github.com` and is dropped if a download is redirected to another host.
- **Repository protections:** secret scanning with push protection, Dependabot alerts, code scanning (CodeQL), private vulnerability reporting, and rules that stop `master` and the `v*` release tags from being deleted or rewritten.

## If you shared a secret by accident

Revoke it at the service that issued it (TMDB, fanart.tv, OMDb, OpenSubtitles, GitHub) and create a new one; deleting a message does not un-share it. Logs written by the tool have keys masked, but check anything you paste into an issue.

## Out of scope

Vulnerabilities in the third-party tools and services this project drives (MKVToolNix, FileBot, ffmpeg, the metadata and subtitle APIs) should be reported to their own maintainers. MediaCleanup contains no media and downloads none; questions about the content of anyone's library are not security issues.
