"""Export ranges: half-open intervals [start, end) in quarter notes."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from fractions import Fraction


@dataclass
class Range:
    start: Fraction
    end: Fraction
    name: str = ""
    id: str = ""

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
