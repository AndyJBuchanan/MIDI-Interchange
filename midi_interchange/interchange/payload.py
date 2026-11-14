"""Transport-neutral MIDI payload produced by every import adapter."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Payload:
    name: str
    data: bytes
    path: str | None = None
    app: str | None = None
    byte_size: int | None = None  # original size if transport data was unwrapped
