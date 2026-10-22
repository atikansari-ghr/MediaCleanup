<#
.SYNOPSIS
    Installs MediaCleanup: Python (if missing), the tool, MKVToolNix, a first config, a launcher.

.DESCRIPTION
    Run it from a release (public repository):

        irm https://github.com/atikansari-ghr/MediaCleanup/releases/latest/download/install.ps1 | iex

    or download it, read it, and run it with options:

        powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallDir D:\Tools\MediaCleanup

    The script is deliberately thin. It gets Python, unpacks the release, and writes a
    first MediaCleanup.toml; everything else is done by the tool itself, which is already
    tested: `--repair` checks every file against the hashes GitHub publishes for the release,
    and `--install` downloads MKVToolNix (checksum-verified). Running it again on an existing
    install updates that install with `--update` and never touches MediaCleanup.toml.

    Nothing here needs administrator rights. FileBot is licensed software and is never
    downloaded: the script only tells you where to get it.

.PARAMETER InstallDir    Where to install. Default: %USERPROFILE%\MediaCleanup
.PARAMETER Tag           Install a specific release (for example v1.12.0). Default: the latest.
.PARAMETER FromDir       Install from a local checkout instead of GitHub (developers, offline use).
.PARAMETER MoviesRoot    Folder scanned for movies.   (asked for when omitted)
.PARAMETER TvRoot        Folder scanned for TV.       (asked for when omitted)
.PARAMETER OutputRoot    Folder remuxed files go to.  (asked for when omitted)
.PARAMETER TmdbKey       TMDB API key (optional).
.PARAMETER OmdbKey       OMDb API key (optional; a second source for identifying films).
.PARAMETER FanartKey     fanart.tv API key (optional).
.PARAMETER MkvToolNixDir Use an existing MKVToolNix folder instead of downloading one.
.PARAMETER FileBotExe    Path to an existing filebot.exe (optional; FileBot is never downloaded).
.PARAMETER WithFfmpeg    Also install ffmpeg (optional; nothing uses it yet).
.PARAMETER WithPillow    Also install Pillow (downscales oversized local posters).
.PARAMETER NoRich        Skip the `rich` package (coloured output and summary tables).
.PARAMETER SkipRuntimes  Do not install MKVToolNix or any package.
.PARAMETER AddToPath     Add the install folder to your user PATH so `mediacleanup` works anywhere.
.PARAMETER Yes           Never ask: use the defaults and the values given as parameters.

.NOTES
    A private repository needs a read-only token in the MEDIACLEANUP_GITHUB_TOKEN environment
    variable. It is sent to api.github.com only.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE 'MediaCleanup'),
    [string]$Tag,
    [string]$FromDir,
    [string]$MoviesRoot,
    [string]$TvRoot,
    [string]$OutputRoot,
    [string]$TmdbKey,
    [string]$OmdbKey,
    [string]$FanartKey,
    [string]$MkvToolNixDir,
    [string]$FileBotExe,
    [switch]$WithFfmpeg,
    [switch]$WithPillow,
    [switch]$NoRich,
    [switch]$SkipRuntimes,
    [switch]$AddToPath,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
$ProgressPreference = 'SilentlyContinue'     # Invoke-WebRequest is far faster without its progress bar

$Repo = 'atikansari-ghr/MediaCleanup'
$script:PyExe = $null
$script:PyPre = @()
$script:ExitCode = 0

# ---- output ----------------------------------------------------------------------------

function Say    { param([string]$Text, [string]$Color = 'White') Write-Host $Text -ForegroundColor $Color }
function Step   { param([string]$Text) Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Ok     { param([string]$Text) Write-Host "   [ok]   $Text" -ForegroundColor Green }
function Note   { param([string]$Text) Write-Host "   [--]   $Text" -ForegroundColor DarkGray }
function Warn   { param([string]$Text) Write-Host "   [!!]   $Text" -ForegroundColor Yellow }
function Fail   { param([string]$Text) Write-Host "   [FAIL] $Text" -ForegroundColor Red }

function Test-Interactive {
    try { return ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) } catch { return $false }
}

# Ask for a value. -Yes, or no terminal, takes the default.
function Ask {
    param([string]$Prompt, [string]$Default = '')
    if ($Yes -or -not (Test-Interactive)) { return $Default }
    $suffix = if ($Default) { " [$Default]" } else { '' }
    $answer = Read-Host "   $Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Confirm-Step {
    param([string]$Prompt, [bool]$Default = $true)
    if ($Yes -or -not (Test-Interactive)) { return $Default }
    $hint = if ($Default) { 'Y/n' } else { 'y/N' }
    $answer = Read-Host "   $Prompt [$hint]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim().ToLower().StartsWith('y')
}

# ---- Python ----------------------------------------------------------------------------

function Find-Python {
    $candidates = @(
        @{ Exe = 'py';      Pre = @('-3') },
        @{ Exe = 'python';  Pre = @() },
        @{ Exe = 'python3'; Pre = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $out = & $c.Exe @($c.Pre) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $out) { continue }     # e.g. the Microsoft Store stub
            if ([version]([string]$out).Trim() -ge [version]'3.11') { return $c }
        } catch { continue }
    }
    return $null
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Ensure-Python {
    Step 'Python 3.11 or newer'
    $found = Find-Python
    if (-not $found) {
        Warn 'Python 3.11+ was not found.'
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            if (Confirm-Step 'Install Python 3.13 with winget now?') {
                & winget install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
                if ($LASTEXITCODE -ne 0) {
                    & winget install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements
                }
                Update-SessionPath
                $found = Find-Python
            }
        }
        if (-not $found) {
            Fail 'Install Python 3.11+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.'
            throw 'Python is required.'
        }
    }
    $script:PyExe = $found.Exe
    $script:PyPre = $found.Pre
    $ver = & $script:PyExe @script:PyPre -c "import sys; print(sys.version.split()[0])"
    Ok "Python $ver ($($found.Exe))"
}

# Runs the tool, shows its output, and returns ONLY the exit code. (A PowerShell function returns
# everything it prints, so without Out-Host the caller would receive the output lines too.)
function Invoke-Py {
    param([string[]]$PyArgs)
    & $script:PyExe @script:PyPre @PyArgs | Out-Host
    return [int]$LASTEXITCODE
}

# ---- GitHub ----------------------------------------------------------------------------

function Get-GitHubHeaders {
    $h = @{ 'User-Agent' = 'MediaCleanup-installer'; 'Accept' = 'application/vnd.github+json' }
    if ($env:MEDIACLEANUP_GITHUB_TOKEN) { $h['Authorization'] = "Bearer $($env:MEDIACLEANUP_GITHUB_TOKEN)" }
    return $h
}

function Resolve-Tag {
    if ($Tag) { return $Tag }
    try {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers (Get-GitHubHeaders)
        return [string]$rel.tag_name
    } catch {
        $code = $null
        try { $code = [int]$_.Exception.Response.StatusCode } catch { }
        if ($code -eq 404) {
            Fail 'GitHub shows no release here: the repository may be private (set MEDIACLEANUP_GITHUB_TOKEN to a read-only token) or none is published yet.'
        } else {
            Fail "Could not look up the latest release: $($_.Exception.Message)"
        }
        throw 'Cannot find a release to install.'
    }
}

function Install-Files {
    # Returns the folder the files were put in.
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    if ($FromDir) {
        Step "Copying files from $FromDir"
        $from = (Resolve-Path $FromDir).Path
        $files = @()
        if (Get-Command git -ErrorAction SilentlyContinue) {
            $files = @(& git -C $from ls-files)
        }
        if (-not $files) {
            $skip = '^(\.git|logs|backup|runtimes|__pycache__)(\\|/|$)'
            $files = @(Get-ChildItem -Path $from -Recurse -File |
                ForEach-Object { $_.FullName.Substring($from.Length + 1) } |
                Where-Object { $_ -notmatch $skip -and $_ -ne 'MediaCleanup.toml' })
        }
        foreach ($rel in $files) {
            $rel = $rel.Replace('/', '\')
            if ($rel -ieq 'MediaCleanup.toml') { continue }          # never copy someone's private config
            $dest = Join-Path $InstallDir $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
            Copy-Item -LiteralPath (Join-Path $from $rel) -Destination $dest -Force
        }
        Ok "$($files.Count) file(s) copied"
        return
    }

    $tag = Resolve-Tag
    Step "Downloading MediaCleanup $tag"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("mediacleanup-install-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'release.zip'
        Invoke-WebRequest -Uri "https://api.github.com/repos/$Repo/zipball/$tag" -Headers (Get-GitHubHeaders) -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp 'x') -Force
        $top = @(Get-ChildItem -LiteralPath (Join-Path $tmp 'x') -Directory)
        if ($top.Count -ne 1) { throw 'The download has an unexpected layout.' }
        Copy-Item -Path (Join-Path $top[0].FullName '*') -Destination $InstallDir -Recurse -Force
        Ok "unpacked $tag into $InstallDir"
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    return
}

# ---- config ----------------------------------------------------------------------------

function Set-TomlValue {
    param([string]$Text, [string]$Key, [string]$Value)
    # Literal strings ('...') need no escaping for Windows paths, but cannot hold a quote.
    if ($Value.Contains("'")) { throw "The value for $Key contains a single quote, which a TOML literal string cannot hold." }
    $pattern = "(?m)^(\s*$([regex]::Escape($Key))\s*=\s*).*$"
    if ($Text -notmatch $pattern) { return $Text }
    return [regex]::Replace($Text, $pattern, { param($m) $m.Groups[1].Value + "'" + $Value + "'" })
}

function Set-TomlKey {
    param([string]$Text, [string]$Key, [string]$Value)
    if ($Value.Contains('"')) { throw "The value for $Key contains a double quote." }
    $pattern = "(?m)^(\s*$([regex]::Escape($Key))\s*=\s*).*$"
    if ($Text -notmatch $pattern) { return $Text }
    return [regex]::Replace($Text, $pattern, { param($m) $m.Groups[1].Value + '"' + $Value + '"' })
}

function Write-FirstConfig {
    Step 'Configuration'
    $cfg = Join-Path $InstallDir 'MediaCleanup.toml'
    if (Test-Path $cfg) {
        Ok 'MediaCleanup.toml already exists - left exactly as it is'
        return
    }
    $example = Join-Path $InstallDir 'MediaCleanup.example.toml'
    if (-not (Test-Path $example)) { throw 'MediaCleanup.example.toml is missing from the install.' }
    $text = [IO.File]::ReadAllText($example)

    $movies = if ($MoviesRoot) { $MoviesRoot } else { Ask 'Folder with your movies' 'D:\Media\Movies' }
    $tv     = if ($TvRoot)     { $TvRoot }     else { Ask 'Folder with your TV shows' 'D:\Media\TV' }
    $out    = if ($OutputRoot) { $OutputRoot } else { Ask 'Folder for remuxed output' 'D:\Media\Fixed' }
    $text = Set-TomlValue $text 'movies_root' $movies
    $text = Set-TomlValue $text 'tv_root' $tv
    $text = Set-TomlValue $text 'output_root' $out

    if ($MkvToolNixDir) { $text = Set-TomlValue $text 'mkvtoolnix_dir' $MkvToolNixDir }
    if ($FileBotExe)    { $text = Set-TomlValue $text 'exe' $FileBotExe }

    $tmdb   = if ($TmdbKey)   { $TmdbKey }   else { Ask 'TMDB API key (Enter to skip)' '' }
    $omdb   = if ($OmdbKey)   { $OmdbKey }   else { Ask 'OMDb API key (Enter to skip)' '' }
    $fanart = if ($FanartKey) { $FanartKey } else { Ask 'fanart.tv API key (Enter to skip)' '' }
    if ($tmdb)   { $text = Set-TomlKey $text 'tmdb_api_key' $tmdb }
    if ($omdb)   { $text = Set-TomlKey $text 'omdb_api_key' $omdb }
    if ($fanart) { $text = Set-TomlKey $text 'fanarttv_api_key' $fanart }

    [IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding($false)))
    Ok "wrote $cfg (it is git-ignored: your paths and keys stay on this machine)"
    if (-not ($tmdb -or $omdb -or $fanart)) {
        Note 'No API keys given. The tool works without them, but titles are identified and tagged far better with a free TMDB key.'
    }
}

# ---- runtimes, launcher ----------------------------------------------------------------

function Install-Runtimes {
    Step 'Tools'
    $tool = Join-Path $InstallDir 'MediaCleanup.py'
    $mkvPresent = (Test-Path (Join-Path $InstallDir 'runtimes\mkvtoolnix\mkvmerge.exe')) -or
                  ($MkvToolNixDir -and (Test-Path (Join-Path $MkvToolNixDir 'mkvmerge.exe')))
    if ($SkipRuntimes) { Note 'Skipped (-SkipRuntimes).'; return }
    if ($mkvPresent) {
        Ok 'MKVToolNix already present'
    } else {
        Say '   Installing MKVToolNix (official portable build, SHA-256 verified)...'
        if ((Invoke-Py @($tool, '--install', 'mkvtoolnix', '--yes')) -ne 0) { throw 'MKVToolNix could not be installed.' }
    }
    if (-not $NoRich)   { if ((Invoke-Py @($tool, '--install', 'rich', '--yes')) -ne 0) { Warn 'rich was not installed (optional).' } }
    if ($WithPillow)    { if ((Invoke-Py @($tool, '--install', 'pillow', '--yes')) -ne 0) { Warn 'Pillow was not installed (optional).' } }
    if ($WithFfmpeg)    { if ((Invoke-Py @($tool, '--install', 'ffmpeg', '--yes')) -ne 0) { Warn 'ffmpeg was not installed (optional).' } }
    $fb = Join-Path $InstallDir 'runtimes\FileBot\filebot.exe'
    if ((Test-Path $fb) -or ($FileBotExe -and (Test-Path $FileBotExe))) {
        Ok 'FileBot found'
    } else {
        Note 'FileBot (optional, licensed) is not installed: get it from https://www.filebot.net/ and put the portable copy in runtimes\FileBot\.'
    }
}

function Write-Launcher {
    $cmd = Join-Path $InstallDir 'mediacleanup.cmd'
    $line = if ($script:PyExe -eq 'py') { '@py -3 "%~dp0MediaCleanup.py" %*' } else { "@$($script:PyExe) `"%~dp0MediaCleanup.py`" %*" }
    [IO.File]::WriteAllText($cmd, "@echo off`r`n$line`r`n", (New-Object Text.ASCIIEncoding))
    Ok "launcher: $cmd"
    $wantPath = $AddToPath
    if (-not $AddToPath -and -not $Yes -and (Test-Interactive)) {
        $wantPath = Confirm-Step 'Add the install folder to your user PATH, so you can type "mediacleanup" anywhere?' $false
    }
    if ($wantPath) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $parts = @($userPath -split ';' | Where-Object { $_ })
        if ($parts -notcontains $InstallDir) {
            [Environment]::SetEnvironmentVariable('Path', (($parts + $InstallDir) -join ';'), 'User')
            Ok 'added to your user PATH (open a new terminal to use it)'
        } else {
            Note 'already on your PATH'
        }
    }
}

# ---- main ------------------------------------------------------------------------------

try {
    Say ''
    Say 'MediaCleanup installer' 'Cyan'
    Say "  install folder: $InstallDir"

    Ensure-Python

    $existing = Test-Path (Join-Path $InstallDir 'MediaCleanup.py')
    if ($existing -and -not $FromDir) {
        Step 'An install already exists here - updating it'
        $rc = Invoke-Py @((Join-Path $InstallDir 'MediaCleanup.py'), '--update', '--yes')
        if ($rc -ne 0 -and $rc -ne 5) { throw 'The update did not complete.' }
    } else {
        Install-Files
        if (-not $FromDir) {
            Step 'Verifying every file against the hashes GitHub published for this release'
            $rc = Invoke-Py @((Join-Path $InstallDir 'MediaCleanup.py'), '--repair', '--files-only', '--yes')
            if ($rc -ne 0) { Warn 'The check reported something - read the lines above.' }
        }
    }

    Write-FirstConfig
    Install-Runtimes
    Write-Launcher

    Step 'Checking the installation'
    $tool = Join-Path $InstallDir 'MediaCleanup.py'
    [void](Invoke-Py @($tool, '--version'))
    if (-not $SkipRuntimes) {
        Say ''
        $rc = Invoke-Py @($tool, '--self-check')
        if ($rc -ne 0) { Warn "The self-check reported a problem (exit $rc) - usually a folder or API key in MediaCleanup.toml." }
    }

    Say ''
    Say 'Done.' 'Green'
    Say "  Preview first:   cd `"$InstallDir`"; python MediaCleanup.py --dry-run --verbose"
    Say '  Update later:    python MediaCleanup.py --update'
    Say '  Guides:          docs\USAGE.md and docs\CONFIGURATION.md'
    $script:ExitCode = 0
} catch {
    Say ''
    Fail $_.Exception.Message
    Say '  Nothing was changed outside the install folder.' 'DarkGray'
    $script:ExitCode = 1
}

# `exit` would close the whole window when this runs through `irm | iex`, so it is used only
# when the script was started as a file (where the exit code is useful to callers).
if ($PSCommandPath) { exit $script:ExitCode }
