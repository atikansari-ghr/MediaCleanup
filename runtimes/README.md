# runtimes\ — portable tools live here

This folder holds the external tools MediaCleanup drives. Only this README and
the folder skeleton are in git — **all binaries are ignored**, so nothing you
put here can ever be committed (important for FileBot, which is licensed).

```
runtimes\
├── mkvtoolnix\     ← REQUIRED — extract the MKVToolNix portable build here
│   ├── mkvmerge.exe
│   ├── mkvpropedit.exe
│   ├── mkvinfo.exe
│   └── mkvextract.exe
└── FileBot\        ← OPTIONAL — portable FileBot for canonical renaming
    ├── filebot.exe
    ├── jre\ ...
    └── (your license file)
```

## Setup

1. **MKVToolNix** (required): download the *portable* 7z from
   <https://mkvtoolnix.download/downloads.html#windows> and extract its
   contents into `runtimes\mkvtoolnix\` so that `mkvmerge.exe` sits directly
   in that folder.
2. **FileBot** (optional): copy a portable FileBot installation into
   `runtimes\FileBot\` so that `filebot.exe` sits directly in that folder.
   Without it, MediaCleanup falls back to built-in renaming heuristics.

The default `MediaCleanup.example.toml` already points at these locations
using relative paths, so once the tools are in place no path editing is
needed:

```toml
[tools]
mkvtoolnix_dir = 'runtimes\mkvtoolnix'

[filebot]
exe = 'runtimes\FileBot\filebot.exe'
```

Prefer system-wide installs instead? Point the TOML at any absolute path
(e.g. `'C:\Program Files\MKVToolNix'`) — relative paths resolve against the
script folder, absolute paths are used as-is.
