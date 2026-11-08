$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\pip install -q -r requirements.txt -r requirements-dev.txt
.\.venv-build\Scripts\pyinstaller --noconfirm --clean midi_interchange.spec
Write-Host "Built: dist\MIDI Interchange\MIDI Interchange.exe"
