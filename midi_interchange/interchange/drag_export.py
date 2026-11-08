"""Export boundary: write processed MIDI to temp files for drag-out.

Destination apps often read dropped files lazily (after the drag completes),
so files persist for the app session and are pruned on the next launch once
older than a day.
"""
from __future__ import annotations

import os
import tempfile
import time

from ..core.export_smf import ExportResult, save_exports

_DIR = os.path.join(tempfile.gettempdir(), "MIDI Interchange Drag")
MAX_AGE_S = 24 * 3600


def temp_dir() -> str:
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def prune_old(max_age: float = MAX_AGE_S) -> None:
    if not os.path.isdir(_DIR):
        return
    now = time.time()
    for root, dirs, files in os.walk(_DIR, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                if now - os.path.getmtime(p) > max_age:
                    os.remove(p)
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass


def write_temp(results: list[ExportResult], base_name: str) -> list[str]:
    # Each drag gets its own folder so the visible filename stays clean
    # (destination apps typically name the new track/clip after it).
    folder = tempfile.mkdtemp(prefix=time.strftime("%H%M%S-"), dir=temp_dir())
    safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in base_name).strip() or "MIDI"
    return save_exports(results, os.path.join(folder, safe + ".mid"))
