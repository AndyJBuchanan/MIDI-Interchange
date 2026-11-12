"""Export ranges: half-open intervals [start, end) in quarter notes.

Each range carries its own track selection (``excluded``: ids of tracks left
out of that range). Unlocked ranges follow the global mute/solo result. Locked
ranges preserve an independently editable selection. Range exports use this
stored selection directly.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from fractions import Fraction


@dataclass
class Range:
    start: Fraction
    end: Fraction
    name: str = ""
    id: str = ""
    excluded: set[str] = field(default_factory=set)
    track_locked: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if self.end < self.start:
            self.start, self.end = self.end, self.start

    @property
    def length(self) -> Fraction:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.end <= self.start

    def contains(self, t: Fraction) -> bool:
        return self.start <= t < self.end

    def includes(self, track_id: str) -> bool:
        return track_id not in self.excluded

    def set_included(self, track_id: str, included: bool) -> None:
        if included:
            self.excluded.discard(track_id)
        else:
            self.excluded.add(track_id)

    def copy(self) -> "Range":
        return replace(self, excluded=set(self.excluded))

    def overlaps(self, start: Fraction, end: Fraction) -> bool:
        return self.start < end and start < self.end


def merge_ranges(ranges: list[Range]) -> list[tuple[Fraction, Fraction]]:
    """Union of ranges as sorted, disjoint (start, end) pairs.

    Adjacent half-open ranges ([0,4) and [4,8)) merge into one span.
    """
    spans = sorted((r.start, r.end) for r in ranges if not r.is_empty)
    out: list[tuple[Fraction, Fraction]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out
