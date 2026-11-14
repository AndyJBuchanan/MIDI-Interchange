"""Import boundary: turn whatever a drop/paste offers into MIDI byte payloads.

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

MIDI_EXTENSIONS = {".mid", ".midi", ".smf", ".kar", ".rmi"}
MAX_FILE_BYTES = 64 * 1024 * 1024


def _read_midi_payload(path: str) -> Payload | None:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    byte_size = len(data)
    if data.startswith(b"RIFF") and data[8:12] == b"RMID":
        # RIFF-wrapped MIDI (.rmi): payload lives in the 'data' chunk.
        idx = data.find(b"MThd")
        if idx < 0:
            return None
        data = data[idx:]
    if not data.startswith(b"MThd"):
        return None
    return Payload(os.path.basename(path), data, path=path, byte_size=byte_size)


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
                    if os.path.splitext(name)[1].lower() in MIDI_EXTENSIONS:
                        full = os.path.join(path, name)
                        payload = _read_midi_payload(full)
                        if payload:
                            payloads.append(payload)
                continue
            payload = _read_midi_payload(path)
            if payload:
                payloads.append(payload)
            else:
                diagnostics.append(f"{os.path.basename(path)}: not a MIDI file")

    if not payloads:
        for fmt in mime.formats():
            raw = bytes(mime.data(fmt).data())
            idx = raw.find(b"MThd", 0, 64)
            if idx >= 0:
                payloads.append(Payload(f"Dropped clip ({_short_format(fmt)})", raw[idx:],
                                        byte_size=len(raw)))
                break

    if not payloads and not diagnostics:
        diagnostics.append("The drop contained no usable MIDI data. Formats offered: "
                           + (", ".join(mime.formats()) or "none"))
    return payloads, diagnostics


def _short_format(fmt: str) -> str:
    return fmt.rsplit("/", 1)[-1].replace('"', "")[:40]
