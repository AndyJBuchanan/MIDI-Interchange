"""Canonical musical time and the tempo / time-signature map.

Canonical time is an exact ``Fraction`` of quarter notes. Any SMF tick value at
any PPQ converts losslessly (``Fraction(tick, ppq)``), so material imported at
different resolutions can be mixed without rounding. Conversion back to ticks
happens only at export, at a PPQ chosen to represent every source exactly
where possible (see ``export_smf.choose_ppq``).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterator

ZERO = Fraction(0)
DEFAULT_US_PER_BEAT = 500_000  # 120 BPM

# Snap settings: None = off, "bar", "beat", or a Fraction step in quarter notes.
SnapSetting = None | str | Fraction


def to_time(tick: int, ppq: int) -> Fraction:
    return Fraction(tick, ppq)


def quantize(t: Fraction | float, denom: int = 960) -> Fraction:
    """Round an arbitrary (e.g. mouse-derived) position to 1/denom quarter."""
    return Fraction(round(float(t) * denom), denom)


@dataclass(frozen=True, slots=True)
class TempoChange:
    time: Fraction
    us_per_beat: int

    @property
    def bpm(self) -> float:
        return 60_000_000 / self.us_per_beat


@dataclass(frozen=True, slots=True)
class TimeSigChange:
    time: Fraction
    numerator: int = 4
    denominator: int = 4
    clocks_per_click: int = 24
    notated_32nd: int = 8

    @property
    def bar_length(self) -> Fraction:
        return Fraction(4 * self.numerator, self.denominator)

    @property
    def beat_length(self) -> Fraction:
        return Fraction(4, self.denominator)


@dataclass
class TempoMap:
    tempos: list[TempoChange] = field(default_factory=list)
    timesigs: list[TimeSigChange] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tempos = _dedupe(sorted(self.tempos, key=lambda c: c.time))
        self.timesigs = _dedupe(sorted(self.timesigs, key=lambda c: c.time))

    # -- queries -----------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        return not self.tempos and not self.timesigs

    def effective_tempos(self) -> list[TempoChange]:
        if self.tempos and self.tempos[0].time == 0:
            return self.tempos
        return [TempoChange(ZERO, DEFAULT_US_PER_BEAT), *self.tempos]

    def effective_timesigs(self) -> list[TimeSigChange]:
        if self.timesigs and self.timesigs[0].time == 0:
            return self.timesigs
        return [TimeSigChange(ZERO), *self.timesigs]

    def tempo_at(self, t: Fraction) -> TempoChange:
        tempos = self.effective_tempos()
        i = bisect.bisect_right([c.time for c in tempos], t) - 1
        return tempos[max(i, 0)]

    def timesig_at(self, t: Fraction) -> TimeSigChange:
        sigs = self.effective_timesigs()
        i = bisect.bisect_right([c.time for c in sigs], t) - 1
        return sigs[max(i, 0)]

    def equivalent(self, other: TempoMap) -> bool:
        return (self.effective_tempos() == other.effective_tempos()
                and self.effective_timesigs() == other.effective_timesigs())

    def shifted(self, delta: Fraction) -> TempoMap:
        return TempoMap(
            [TempoChange(c.time + delta, c.us_per_beat) for c in self.tempos],
            [TimeSigChange(c.time + delta, c.numerator, c.denominator,
                           c.clocks_per_click, c.notated_32nd) for c in self.timesigs])

    # -- bar / beat structure ---------------------------------------------
    def _segments(self) -> list[tuple[TimeSigChange, Fraction | None, int]]:
        """(timesig, segment_end_or_None, first_bar_index) for each TS region.

        A time-signature change that does not land on a bar line starts a new
        bar at its own position (the preceding bar is short).
        """
        sigs = self.effective_timesigs()
        out = []
        bar_index = 0
        for i, ts in enumerate(sigs):
            end = sigs[i + 1].time if i + 1 < len(sigs) else None
            out.append((ts, end, bar_index))
            if end is not None:
                bar_index += math.ceil((end - ts.time) / ts.bar_length)
        return out

    def bars(self, t0: Fraction, t1: Fraction) -> Iterator[tuple[int, Fraction, Fraction, TimeSigChange]]:
        """Yield (bar_index0, bar_start, bar_end, timesig) for bars overlapping [t0, t1)."""
        t0 = max(t0, ZERO)
        for ts, seg_end, first_bar in self._segments():
            if seg_end is not None and seg_end <= t0:
                continue
            if ts.time >= t1:
                return
            k = max(0, math.floor((t0 - ts.time) / ts.bar_length))
            while True:
                start = ts.time + k * ts.bar_length
                if start >= t1 or (seg_end is not None and start >= seg_end):
                    break
                end = start + ts.bar_length
                if seg_end is not None:
                    end = min(end, seg_end)
                yield first_bar + k, start, end, ts
                k += 1

    def bar_containing(self, t: Fraction) -> tuple[int, Fraction, Fraction, TimeSigChange]:
        t = max(t, ZERO)
        for bar in self.bars(t, t + Fraction(1, 1_000_000)):
            return bar
        raise AssertionError("unreachable")

    def bar_start(self, bar_index0: int) -> Fraction:
        for ts, seg_end, first_bar in reversed(self._segments()):
            if bar_index0 >= first_bar:
                start = ts.time + (bar_index0 - first_bar) * ts.bar_length
                if seg_end is None or start <= seg_end:
                    return start
        return ZERO + bar_index0 * Fraction(4)

    # -- BBT conversion ---------------------------------------------------
    def to_bbt(self, t: Fraction, ticks_per_quarter: int = 480) -> tuple[int, int, Fraction]:
        """Return 1-based (bar, beat) and the tick remainder within the beat."""
        idx, start, _end, ts = self.bar_containing(t)
        offset = t - start
        beat = math.floor(offset / ts.beat_length)
        rem = (offset - beat * ts.beat_length) * ticks_per_quarter
        return idx + 1, beat + 1, rem

    def from_bbt(self, bar: int, beat: int = 1, tick: Fraction | int = 0,
                 ticks_per_quarter: int = 480) -> Fraction:
        bar = max(bar, 1)
        beat = max(beat, 1)
        start = self.bar_start(bar - 1)
        ts = self.timesig_at(start)
        return start + (beat - 1) * ts.beat_length + Fraction(tick) / ticks_per_quarter

    def format_bbt(self, t: Fraction) -> str:
        bar, beat, rem = self.to_bbt(t)
        return f"{bar}.{beat}.{int(round(rem)):03d}"

    def parse_bbt(self, text: str) -> Fraction:
        parts = [p for p in text.replace(":", ".").replace(" ", "").split(".") if p != ""]
        if not parts or len(parts) > 3:
            raise ValueError(f"Expected bar[.beat[.tick]], got {text!r}")
        nums = [int(p) for p in parts]
        return self.from_bbt(*nums)

    # -- snapping -----------------------------------------------------------
    def snap(self, t: Fraction, setting: SnapSetting) -> Fraction:
        if setting is None:
            return max(t, ZERO)
        t = max(t, ZERO)
        _idx, start, end, ts = self.bar_containing(t)
        if setting == "bar":
            return start if (t - start) <= (end - t) else end
        step = ts.beat_length if setting == "beat" else Fraction(setting)
        n = (t - start) / step
        snapped = start + math.floor(n + Fraction(1, 2)) * step
        return min(snapped, end)

    # -- seconds (for display only) ---------------------------------------------
    def seconds_at(self, t: Fraction) -> float:
        secs = 0.0
        tempos = self.effective_tempos()
        for i, c in enumerate(tempos):
            nxt = tempos[i + 1].time if i + 1 < len(tempos) else None
            seg_end = t if nxt is None else min(t, nxt)
            if seg_end <= c.time:
                break
            secs += float(seg_end - c.time) * c.us_per_beat / 1e6
        return secs


def _dedupe(changes: list) -> list:
    """Keep the last change at any given time (later events win, as in SMF)."""
    out: list = []
    for c in changes:
        if out and out[-1].time == c.time:
            out[-1] = c
        else:
            out.append(c)
    return out
