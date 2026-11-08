#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3.12 -m venv .venv-build
.venv-build/bin/pip install -q -r requirements.txt -r requirements-dev.txt
.venv-build/bin/pyinstaller --noconfirm --clean midi_interchange.spec
echo "Built: dist/MIDI Interchange.app"
