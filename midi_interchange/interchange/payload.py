"""Transport-neutral MIDI payload produced by every import adapter."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Payload:
    name: str
    data: bytes
    path: str | None = None
    app: str | None = None
