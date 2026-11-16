"""Transport-neutral input produced by every import adapter.

Project payloads may carry a path and empty data so readers can open only the
parts they need; byte payloads remain available for MIDI clipboard transports."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Payload:
    name: str
    data: bytes
    path: str | None = None
    app: str | None = None
    byte_size: int | None = None  # original size if transport data was unwrapped
