"""Simplify controller data on export (docs/plans/0.5.0/simplify-controller-data.md).

A pure post-pass over finished output tracks. Dense curves (a value every
1/32 beat) become the few points a DAW needs to draw the same line:

1. Of several events on one tick the last wins, and events at the very end
   of a stream that repeat the value before them are dropped (the value
   holds after the last point anyway).
2. Thin the rest so that straight lines joining the kept points stay within
   a fixed tolerance of every original point. The first and last points of
   a stream are always kept. A run of repeated values collapses to its two
   ends this way; a repeat is never dropped on its own mid-stream, because
   a DAW that draws straight lines would turn "hold, then ramp" into a ramp.

Streams are keyed on the final output channel. Program changes, notes, meta
and SysEx events, and the controllers that are not curves, are never touched.
"""
from __future__ import annotations

from fractions import Fraction

import mido

from .events import MODE_CCS

CC_TOLERANCE = 1
PITCH_BEND_TOLERANCE = 128      # one 7-bit step of the 14-bit value: the same relative size as a CC step
AFTERTOUCH_TOLERANCE = 1
POLY_PRESSURE_TOLERANCE = 1

# Controllers whose values are not a curve: bank select, data entry, RPN/NRPN.
SEQUENCE_CCS = frozenset({0, 32, 6, 38, 96, 97, 98, 99, 100, 101})


def _stream(msg) -> tuple[tuple, int, int] | None:
    """(stream key, value, tolerance) for a simplifiable message, else None."""
    t = msg.type
    if t == "control_change":
        if msg.control in SEQUENCE_CCS or msg.control in MODE_CCS:
            return None
        return (msg.channel, "cc", msg.control), msg.value, CC_TOLERANCE
    if t == "pitchwheel":
        return (msg.channel, "pw"), msg.pitch, PITCH_BEND_TOLERANCE
    if t == "aftertouch":
        return (msg.channel, "at"), msg.value, AFTERTOUCH_TOLERANCE
    if t == "polytouch":
        return (msg.channel, "pk", msg.note), msg.value, POLY_PRESSURE_TOLERANCE
    return None


def thin_points(points: list[tuple[int, int]], tol: int) -> list[int]:
    """Indices of the points to keep (always the first and last).

    From an anchor, a segment is extended while the line from the anchor to
    the candidate end stays within ``tol`` of every point between: kept as
    the range of slopes still allowed, so it's one pass. When a candidate
    fails, the point before it is kept and becomes the next anchor.
    """
    n = len(points)
    if n <= 2:
        return list(range(n))
    kept = [0]
    a = 0
    lo = hi = None          # allowed slope range from the anchor; None = unbounded
    j = 1
    while j < n:
        dt = points[j][0] - points[a][0]
        dv = points[j][1] - points[a][1]
        s = Fraction(dv, dt)
        if (lo is None or s >= lo) and (hi is None or s <= hi):
            new_lo, new_hi = Fraction(dv - tol, dt), Fraction(dv + tol, dt)
            lo = new_lo if lo is None else max(lo, new_lo)
            hi = new_hi if hi is None else min(hi, new_hi)
            j += 1
        else:
            a = j - 1
            kept.append(a)
            lo = hi = None
    kept.append(n - 1)
    return kept


def simplify_track(track: mido.MidiTrack) -> mido.MidiTrack:
    """A copy of ``track`` with its continuous controller streams simplified."""
    absolute: list[tuple[int, mido.Message | mido.MetaMessage]] = []
    now = 0
    for m in track:
        now += m.time
        absolute.append((now, m))

    streams: dict[tuple, list[int]] = {}        # key -> indices into `absolute`
    info: dict[tuple, int] = {}                 # key -> tolerance
    for i, (_tick, m) in enumerate(absolute):
        if m.is_meta:
            continue
        s = _stream(m)
        if s is not None:
            streams.setdefault(s[0], []).append(i)
            info[s[0]] = s[2]

    drop: set[int] = set()
    for key, idxs in streams.items():
        # 1. same tick: the later wins; repeats at the very end are redundant
        survivors: list[int] = []
        for i in idxs:
            if survivors and absolute[survivors[-1]][0] == absolute[i][0]:
                drop.add(survivors.pop())
            survivors.append(i)
        while len(survivors) >= 2 and (_stream(absolute[survivors[-1]][1])[1]
                                       == _stream(absolute[survivors[-2]][1])[1]):
            drop.add(survivors.pop())
        deduped = survivors
        # 2. thin
        pts = [(absolute[i][0], _stream(absolute[i][1])[1]) for i in deduped]
        keep = set(thin_points(pts, info[key]))
        drop.update(i for k, i in enumerate(deduped) if k not in keep)

    out = mido.MidiTrack()
    prev = 0
    for i, (tick, m) in enumerate(absolute):
        if i in drop:
            continue
        out.append(m.copy(time=tick - prev))
        prev = tick
    return out


def simplify_midi(mf: mido.MidiFile) -> mido.MidiFile:
    """``mf`` with every track simplified (same ticks per beat, type and track order)."""
    out = mido.MidiFile(type=mf.type, ticks_per_beat=mf.ticks_per_beat)
    out.tracks.extend(simplify_track(t) for t in mf.tracks)
    return out
