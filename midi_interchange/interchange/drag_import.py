"""Import boundary: turn whatever a drop/paste offers into registered file or MIDI byte payloads.

Handled here (via Qt, both platforms):
* File URLs (Finder/Explorer, and DAWs that drag a rendered temp .mid, which
  covers Cubase and most clip-exporting tools on both platforms).
* Any MIME format whose bytes are a Standard MIDI File (``MThd``) — e.g.
  ``audio/midi``, ``audio/x-midi``, macOS UTI-derived formats
  (``application/x-qt-mime-type-name...public.midi-audio``) and Windows
  registered clipboard formats exposed by Qt.

Not handled by Qt and deferred to the platform adapters (Milestone 2):
* macOS file promises (NSFilePromiseReceiver) — Qt does not receive them.
* Windows virtual files (CFSTR_FILEDESCRIPTOR / CFSTR_FILECONTENTS).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData

from .payload import Payload

from .readers import EXTENSIONS, payload_from_path
from ..core.import_smf import ImportError_

def _read_file_payload(path: str) -> Payload | None:
    try:
        return payload_from_path(path)
    except (OSError, ImportError_):
        return None


def mime_may_contain_midi(mime: QMimeData) -> bool:
    if mime.hasUrls():
        return any(u.isLocalFile() for u in mime.urls())
    return any("midi" in f.lower() or "smf" in f.lower() for f in mime.formats()) or bool(mime.formats())


def extract_payloads(mime: QMimeData) -> tuple[list[Payload], list[str]]:
    """Return (payloads, diagnostics). Diagnostics explain what could not be used."""
    payloads: list[Payload] = []
    diagnostics: list[str] = []
    seen_paths: set[str] = set()

    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                diagnostics.append(f"Non-local URL ignored: {url.toString()}")
                continue
            path = url.toLocalFile()
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    if os.path.splitext(name)[1].lower() in EXTENSIONS:
                        full = os.path.join(path, name)
                        payload = _read_file_payload(full)
                        if payload:
                            payloads.append(payload)
                continue
            payload = _read_file_payload(path)
            if payload:
                payloads.append(payload)
            else:
                diagnostics.append(f"{os.path.basename(path)}: not a supported MIDI or project file")

    if not payloads:
        for fmt in mime.formats():
            raw = bytes(mime.data(fmt).data())
            idx = raw.find(b"MThd", 0, 64)
            if idx >= 0:
                payloads.append(Payload(f"Dropped clip ({_short_format(fmt)})", raw[idx:],
                                        byte_size=len(raw)))
                break

    if not payloads and not diagnostics:
        diagnostics.append("The drop contained no usable MIDI or project data. Formats offered: "
                           + (", ".join(mime.formats()) or "none"))
    return payloads, diagnostics


def _short_format(fmt: str) -> str:
    return fmt.rsplit("/", 1)[-1].replace('"', "")[:40]
