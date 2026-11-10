#!/usr/bin/env bash
#
# MediaCleanup installer for Debian and Ubuntu (a machine, a VM or an LXC container).
#
# Run it from a release (public repository), as root:
#
#     curl -fsSL https://github.com/atikansari-ghr/MediaCleanup/releases/latest/download/install.sh | sudo bash
#
# or download it, read it, and run it with options:
#
#     sudo bash install.sh --dir /opt/MediaCleanup --with-ffmpeg
#
# The script is deliberately thin. apt installs what MediaCleanup runs on (Python, MKVToolNix
# and the optional rich and Pillow packages); the release is unpacked; and the tool itself then
# checks every file against the hashes GitHub publishes for that release (`--repair --files-only`).
# Nothing is downloaded except from apt and from GitHub. MediaCleanup.toml is never overwritten.
#
# FileBot is licensed software and is never installed by this script.
#
# Options:
#   --dir DIR         Where to install. Default: /opt/MediaCleanup
#   --tag TAG         Install a specific release (for example v1.13.0). Default: the latest.
#   --from-dir DIR    Install from a local checkout instead of GitHub (developers, offline use).
#   --movies DIR      Folder scanned for movies.   (written to the first config)
#   --tv DIR          Folder scanned for TV.
#   --output DIR      Folder remuxed files go to.
#   --with-ffmpeg     Also install ffmpeg (optional).
#   --no-link         Do not create the `mediacleanup` command in /usr/local/bin.
#   --skip-packages   Do not run apt (Python, MKVToolNix and the packages must already be there).
#   -h, --help        Show this text.
#
set -euo pipefail

REPO="atikansari-ghr/MediaCleanup"
INSTALL_DIR="/opt/MediaCleanup"
TAG=""
FROM_DIR=""
MOVIES=""
TV=""
OUTPUT=""
WITH_FFMPEG=0
LINK=1
PACKAGES=1

if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_STEP=$'\033[36m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_ERR=""; C_STEP=""; C_OFF=""
fi
step() { printf '\n%s== %s%s\n' "$C_STEP" "$1" "$C_OFF"; }
ok()   { printf '   %s[ok]%s   %s\n' "$C_OK" "$C_OFF" "$1"; }
note() { printf '   [--]   %s\n' "$1"; }
warn() { printf '   %s[!!]%s   %s\n' "$C_WARN" "$C_OFF" "$1"; }
die()  { printf '   %s[FAIL]%s %s\n' "$C_ERR" "$C_OFF" "$1" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" 2>/dev/null | sed '$d' | sed 's/^# \{0,1\}//' || true; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)           INSTALL_DIR="${2:?--dir needs a folder}"; shift 2 ;;
        --tag)           TAG="${2:?--tag needs a release tag}"; shift 2 ;;
        --from-dir)      FROM_DIR="${2:?--from-dir needs a folder}"; shift 2 ;;
        --movies)        MOVIES="${2:?--movies needs a folder}"; shift 2 ;;
        --tv)            TV="${2:?--tv needs a folder}"; shift 2 ;;
        --output)        OUTPUT="${2:?--output needs a folder}"; shift 2 ;;
        --with-ffmpeg)   WITH_FFMPEG=1; shift ;;
        --no-link)       LINK=0; shift ;;
        --skip-packages) PACKAGES=0; shift ;;
        -h|--help)       usage; exit 0 ;;
        *)               die "unknown option: $1 (try --help)" ;;
    esac
done

# A path ends up inside a TOML string, so refuse anything that could break out of it.
for value in "$MOVIES" "$TV" "$OUTPUT" "$INSTALL_DIR"; do
    case "$value" in
        *\'*|*\"*|*$'\n'*) die "folder names may not contain quotes or line breaks: $value" ;;
    esac
done

step "Checking this machine"
[ "$(uname -s)" = "Linux" ] || die "this installer is for Linux; on Windows use install.ps1"
if [ "$PACKAGES" -eq 1 ]; then
    command -v apt-get >/dev/null 2>&1 || die "apt-get not found. This installer is for Debian and Ubuntu; with another system install Python 3.11+, MKVToolNix and rich yourself and re-run with --skip-packages"
    [ "$(id -u)" -eq 0 ] || die "apt needs root. Run: curl -fsSL https://github.com/$REPO/releases/latest/download/install.sh | sudo bash"
    ok "apt available, running as root"
fi

step "Installing what MediaCleanup runs on (apt)"
if [ "$PACKAGES" -eq 1 ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    pkgs="python3 ca-certificates curl mkvtoolnix python3-rich python3-pil"
    [ "$WITH_FFMPEG" -eq 1 ] && pkgs="$pkgs ffmpeg"
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends $pkgs >/dev/null
    ok "installed: $pkgs"
else
    note "skipped (--skip-packages)"
fi
command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "Python 3.11 or newer is needed (this is $(python3 --version 2>&1))"
command -v mkvmerge >/dev/null 2>&1 || warn "mkvmerge is not on the PATH; install the mkvtoolnix package"
ok "$(python3 --version 2>&1)"

step "Getting MediaCleanup"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
if [ -n "$FROM_DIR" ]; then
    [ -f "$FROM_DIR/MediaCleanup.py" ] || die "no MediaCleanup.py in $FROM_DIR"
    if [ -d "$FROM_DIR/.git" ] && command -v git >/dev/null 2>&1 && git -C "$FROM_DIR" rev-parse >/dev/null 2>&1; then
        # A git checkout: take what git tracks (and new files), never what it ignores.
        git -C "$FROM_DIR" ls-files -z --cached --others --exclude-standard \
            | tar -C "$FROM_DIR" --null -T - -cf - | tar -C "$STAGE" --no-same-owner -xf -
    else
        tar -C "$FROM_DIR" --exclude=.git --exclude=MediaCleanup.toml --exclude=logs --exclude=backup \
            --exclude=__pycache__ --exclude='runtimes/*' -cf - . | tar -C "$STAGE" --no-same-owner -xf -
    fi
    ok "using the local copy in $FROM_DIR"
else
    command -v curl >/dev/null 2>&1 || die "curl is not installed"
    if [ -z "$TAG" ]; then
        TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')" \
            || die "could not look up the latest release (offline, or GitHub is unreachable)"
    fi
    case "$TAG" in
        v[0-9]*.[0-9]*.[0-9]*) ;;
        *) die "not a release tag: $TAG" ;;
    esac
    curl -fsSL -o "$STAGE/release.zip" "https://github.com/$REPO/archive/refs/tags/$TAG.zip" \
        || die "could not download release $TAG"
    python3 -m zipfile -e "$STAGE/release.zip" "$STAGE/unpacked"
    inner="$(find "$STAGE/unpacked" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    [ -f "$inner/MediaCleanup.py" ] || die "the download does not look like MediaCleanup"
    mkdir "$STAGE/files"
    cp -a "$inner/." "$STAGE/files/"
    mv "$STAGE/files" "$STAGE/tree"
    rm -rf "$STAGE/unpacked" "$STAGE/release.zip"
    ok "downloaded release $TAG"
fi
SRC="$STAGE"
[ -d "$STAGE/tree" ] && SRC="$STAGE/tree"

step "Installing into $INSTALL_DIR"
if [ -f "$INSTALL_DIR/MediaCleanup.py" ]; then
    note "an install already exists here; updating it with its own --update (your config is not touched)"
    python3 "$INSTALL_DIR/MediaCleanup.py" --update --yes || warn "the update did not complete; see the messages above"
else
    mkdir -p "$INSTALL_DIR"
    cp -a "$SRC/." "$INSTALL_DIR/"
    mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/runtimes"
    ok "files copied"
    if [ -z "$FROM_DIR" ]; then
        (cd "$INSTALL_DIR" && python3 MediaCleanup.py --repair --files-only --yes) \
            || die "the installed files do not match release $TAG - nothing was changed beyond $INSTALL_DIR"
    else
        note "files not checked against a release (installed from a local copy)"
    fi
fi

step "Configuration"
CONFIG="$INSTALL_DIR/MediaCleanup.toml"
if [ -f "$CONFIG" ]; then
    ok "MediaCleanup.toml already exists - left as it is"
else
    [ -f "$INSTALL_DIR/MediaCleanup.linux.example.toml" ] || die "MediaCleanup.linux.example.toml is missing from the release"
    cp "$INSTALL_DIR/MediaCleanup.linux.example.toml" "$CONFIG"
    [ -z "$MOVIES" ] || sed -i "s#^movies_root = .*#movies_root = '$MOVIES'#" "$CONFIG"
    [ -z "$TV" ]     || sed -i "s#^tv_root     = .*#tv_root     = '$TV'#" "$CONFIG"
    [ -z "$OUTPUT" ] || sed -i "s#^output_root = .*#output_root = '$OUTPUT'#" "$CONFIG"
    chmod 600 "$CONFIG"
    ok "created MediaCleanup.toml (it will hold your API keys, so only its owner can read it)"
fi

# Whoever ran sudo owns the install, so --update and the logs work without root afterwards.
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && id "$SUDO_USER" >/dev/null 2>&1; then
    chown -R "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$INSTALL_DIR"
    ok "owned by $SUDO_USER"
fi

step "The mediacleanup command"
if [ "$LINK" -eq 1 ] && [ -w /usr/local/bin ]; then
    printf '#!/bin/sh\nexec python3 "%s/MediaCleanup.py" "$@"\n' "$INSTALL_DIR" > /usr/local/bin/mediacleanup
    chmod 755 /usr/local/bin/mediacleanup
    ok "/usr/local/bin/mediacleanup"
else
    note "not created; run: python3 $INSTALL_DIR/MediaCleanup.py"
fi

step "What was installed"
python3 "$INSTALL_DIR/MediaCleanup.py" --version || true

printf '\n%sDone.%s Next steps:\n' "$C_OK" "$C_OFF"
printf '  1. Edit %s  (your folders, and API keys under [coverart])\n' "$CONFIG"
printf '  2. Preview a run - nothing is changed:   mediacleanup --dry-run --verbose\n'
printf '  3. Keep it current:                      mediacleanup --check-update   /   mediacleanup --update\n'
printf '  FileBot (optional, licensed) is not installed by this script; see https://www.filebot.net/\n'
