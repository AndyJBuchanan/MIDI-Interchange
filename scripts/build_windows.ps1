# Builds dist\MIDI Interchange\MIDI Interchange.exe (one-folder app), a portable zip
# (dist\MIDI-Interchange-<version>-Windows-<arch>.zip) and, if Inno Setup 6 is installed,
# an installer (dist\MIDI-Interchange-<version>-Windows-<arch>-Setup.exe, from scripts\installer.iss).
#
# Usage (from any directory):
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# Environment overrides:
#   PY_VERSION=3.13    Python version passed to the py launcher (default 3.12)
#   ISCC=<path>        Inno Setup compiler, if not in a standard location
#   SKIP_INSTALLER=1   build the app and zip only
#
# The build is NOT code-signed (no Windows certificate yet): SmartScreen will warn on
# machines that download it. See docs/DEVELOPMENT.md, "Windows build".
#
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Windows PowerShell 5.1 does not stop on a failing native command, so check each one.
function Invoke-Checked {
    param([string]$What, [scriptblock]$Cmd)
    & $Cmd
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

# Endpoint security agents (CrowdStrike Falcon, Defender, etc.) briefly lock a file right
# after PyInstaller writes it while they scan it, which fails Compress-Archive/ISCC/Get-FileHash
# with "being used by another process". Retry with backoff instead of failing the build.
function Invoke-WithRetry {
    param([string]$What, [scriptblock]$Cmd, [int]$Attempts = 6, [int]$DelayMs = 1500)
    for ($i = 1; $i -le $Attempts; $i++) {
        try { & $Cmd; return } catch {
            if ($i -eq $Attempts) { throw }
            Write-Warning "$What locked (attempt $i/$Attempts): $($_.Exception.Message). Retrying in $($DelayMs)ms..."
            Start-Sleep -Milliseconds $DelayMs
        }
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "The Python launcher 'py' was not found. Install Python 3.12 from python.org (winget install Python.Python.3.12) and open a new terminal."
}
$pyVersion = if ($env:PY_VERSION) { $env:PY_VERSION } else { "3.12" }

# --- build the app folder ---------------------------------------------------------
Invoke-Checked "Creating .venv-build" { py "-$pyVersion" -m venv .venv-build }
$py = ".\.venv-build\Scripts\python.exe"
Invoke-Checked "Upgrading pip" { & $py -m pip install -q -U pip }
Invoke-Checked "Installing requirements" { & $py -m pip install -q -r requirements.txt -r requirements-dev.txt }
Invoke-Checked "PyInstaller" { & $py -m PyInstaller --noconfirm --clean midi_interchange.spec }

$appDir = "dist\MIDI Interchange"
$exe = Join-Path $appDir "MIDI Interchange.exe"
if (-not (Test-Path $exe)) { throw "Build finished but $exe is missing" }
Write-Host "Built: $exe"

# --- package the zip -------------------------------------------------------------
$specText = Get-Content -Raw midi_interchange.spec
if ($specText -notmatch '(?m)^VERSION\s*=\s*"([^"]+)"') { throw "VERSION not found in midi_interchange.spec" }
$version = $Matches[1]
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$zip = "dist\MIDI-Interchange-$version-Windows-$arch.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
# Zip the folder itself so users extract a single "MIDI Interchange" directory.
Invoke-WithRetry "Compress-Archive" { Compress-Archive -Path $appDir -DestinationPath $zip -CompressionLevel Optimal }

$exeVersion = (Get-Item $exe).VersionInfo.ProductVersion
$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
$sha = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
Write-Host "Packaged: $zip ($sizeMB MB, exe version $exeVersion)"
Write-Host "SHA-256: $sha"

# --- build the installer (Inno Setup) ---------------------------------------------
if ($env:SKIP_INSTALLER -eq "1") { Write-Host "SKIP_INSTALLER=1: installer not built."; exit 0 }
$iscc = $null
$candidates = @($env:ISCC,
                (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
                (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"))
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $iscc = $c; break } }
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    Write-Warning "Inno Setup 6 not found, so no installer was built (the zip is still usable). Install it with: winget install JRSoftware.InnoSetup --scope user"
    exit 0
}
$root = (Get-Location).Path
Invoke-WithRetry "Inno Setup" { Invoke-Checked "Inno Setup" { & $iscc /Q "/DAppVersion=$version" "/DAppSourceDir=$root\$appDir" "/DOutputDir=$root\dist" scripts\installer.iss } }
$setup = "dist\MIDI-Interchange-$version-Windows-$arch-Setup.exe"
if (-not (Test-Path $setup)) { throw "Inno Setup finished but $setup is missing" }
$setupMB = [math]::Round((Get-Item $setup).Length / 1MB, 1)
$setupSha = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
Write-Host "Installer: $setup ($setupMB MB)"
Write-Host "SHA-256: $setupSha"
