"""Canonical model -> Standard MIDI File (format 1). Never mutates the workspace.

Range boundary policy (half-open ranges [s, e)):

* Notes are paired FIFO per (channel, pitch). A note is exported if it sounds
  within [s, e). Notes starting before s are clipped to start at s (unless
  ``partial_notes`` is False, in which case they are omitted). Notes running
  past e are released at e with a synthesized note-off. Every exported
  note-on therefore has a matching note-off: no stuck notes.
* Channel state is carried to s: the latest program change, controller values
  (except channel-mode CCs 120-127), pitch bend and channel pressure that
  occurred before s are emitted at s, in their original relative order (so
  bank select precedes program change and RPN/NRPN sequences stay intact).
  The latest key signature is carried too. Polyphonic aftertouch and SysEx
  are not carried (their state is note- or device-specific).
* Tempo and time signature in effect at s are written at the segment start;
  changes inside the range follow at their relative positions.
* Lyrics, text, markers and other meta/SysEx events are exported when their
  time is in [s, e).
* Preserve mode keeps absolute positions (overlapping/adjacent ranges are
  merged first). Rebase mode concatenates ranges in user order, end to end.
  Separate mode produces one rebased file per range.
* The output end-of-track is placed at the end of the range (or of the last
  concatenated range) so loop lengths survive, unless trimming is enabled.

Trim: content is defined as notes and lyrics. "Trim" removes leading and
trailing time without content from the assembled output as a whole: all tracks
shift by the same amount, so relative alignment is never changed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Iterable

import mido

from .document import Track, Workspace
from .events import MODE_CCS, Event, Msg, display_text, is_note_off, is_note_on, pair_notes
from .ranges import Range, merge_ranges
from .timing import TempoMap, ZERO

MAX_PPQ = 32767


class ExportMode(Enum):
    WHOLE = "whole"
    PRESERVE = "preserve"
    REBASE = "rebase"
    SEPARATE = "separate"


@dataclass
class ExportOptions:
    mode: ExportMode = ExportMode.WHOLE
    track_ids: list[str] | None = None      # None -> all enabled tracks
    ranges: list[Range] | None = None       # None -> workspace ranges
    trim: bool = False
    partial_notes: bool = True


@dataclass
class ExportResult:
    label: str
    midi: mido.MidiFile


@dataclass(order=True)
class _Item:
    time: Fraction
    key: tuple
    msg: Msg = field(compare=False)


@dataclass
class _Segment:
    start: Fraction        # source (workspace) time
    end: Fraction | None   # None = unbounded (whole export)
    dst: Fraction          # output time of `start`


# ---------------------------------------------------------------------------
# public API

def build_exports(ws: Workspace, opts: ExportOptions | None = None) -> list[ExportResult]:
    opts = opts or ExportOptions()
    tracks = _select_tracks(ws, opts.track_ids)
    ranges = [r for r in (ws.ranges if opts.ranges is None else opts.ranges) if not r.is_empty]
    mode = opts.mode if ranges else ExportMode.WHOLE

    if mode is ExportMode.WHOLE:
        if opts.trim:
            bounds = content_bounds(tracks, ZERO, None)
            if bounds is None:
                return [ExportResult("", _whole(ws, tracks))]
            return [ExportResult("", _segmented(ws, tracks, [_Segment(bounds[0], bounds[1], ZERO)],
                                                opts, preserve=False, end=bounds[1] - bounds[0]))]
        return [ExportResult("", _whole(ws, tracks))]

    if mode is ExportMode.PRESERVE:
        spans = merge_ranges(ranges)
        segs = [_Segment(s, e, s) for s, e in spans]
        end = spans[-1][1]
        if opts.trim:
            bounds = content_bounds(tracks, spans[0][0], end)
            if bounds is not None:
                end = bounds[1]
        return [ExportResult("", _segmented(ws, tracks, segs, opts, preserve=True, end=end))]

    if mode is ExportMode.REBASE:
        segs, end = _concat_segments([(r.start, r.end) for r in ranges], tracks, opts.trim)
        return [ExportResult("", _segmented(ws, tracks, segs, opts, preserve=False, end=end))]

    results = []
    for i, r in enumerate(ranges):
        segs, end = _concat_segments([(r.start, r.end)], tracks, opts.trim)
        label = r.name or f"Range {i + 1}"
        results.append(ExportResult(label, _segmented(ws, tracks, segs, opts, preserve=False, end=end)))
    return results


def save_exports(results: list[ExportResult], path: str) -> list[str]:
    """Write results; multiple results get the range label appended."""
    import os

    paths = []
    stem, ext = os.path.splitext(path)
    ext = ext or ".mid"
    for res in results:
        p = f"{stem}{ext}" if len(results) == 1 else f"{stem} - {_safe(res.label)}{ext}"
        res.midi.save(p)
        paths.append(p)
    return paths


def content_bounds(tracks: Iterable[Track], s: Fraction, e: Fraction | None) -> tuple[Fraction, Fraction] | None:
    """First/last instant of notes or lyrics within [s, e) across tracks."""
    lo: Fraction | None = None
    hi: Fraction | None = None
    for track in tracks:
        for clip in track.clips:
            notes, _ = pair_notes(clip.events, clip.length)
            for n in notes:
                ns, ne = n.start + clip.offset, n.end + clip.offset
                if e is not None and ns >= e or ne <= s and not (ns == ne == s):
                    continue
                a = max(ns, s)
                b = ne if e is None else min(ne, e)
                lo = a if lo is None else min(lo, a)
                hi = b if hi is None else max(hi, b)
            for ev in clip.events:
                if ev.msg.type == "lyrics":
                    t = ev.time + clip.offset
                    if t >= s and (e is None or t < e):
                        lo = t if lo is None else min(lo, t)
                        hi = t if hi is None else max(hi, t)
    if lo is None or hi is None:
        return None
    return lo, hi


def choose_ppq(source_ppqs: Iterable[int], times: Iterable[Fraction]) -> int:
    """Smallest PPQ that represents every source resolution and every output
    time exactly; falls back to the largest source PPQ (min 480) if that
    would exceed the 15-bit SMF limit."""
    ppqs = list(source_ppqs) or [480]
    exact = 1
    for p in ppqs:
        exact = math.lcm(exact, p)
    for t in times:
        exact = math.lcm(exact, t.denominator)
        if exact > MAX_PPQ:
            break
    if exact <= MAX_PPQ:
        return exact
    return max(max(ppqs), 480)


# ---------------------------------------------------------------------------
# internals

def _select_tracks(ws: Workspace, ids: list[str] | None) -> list[Track]:
    if ids is None:
        return ws.enabled_tracks()
    wanted = set(ids)
    return [t for t in ws.tracks if t.id in wanted]


def _concat_segments(spans: list[tuple[Fraction, Fraction]], tracks: list[Track],
                     trim: bool) -> tuple[list[_Segment], Fraction]:
    segs: list[_Segment] = []
    cursor = ZERO
    for s, e in spans:
        if trim:
            b = content_bounds(tracks, s, e)
            if b is None:
                continue
            s, e = b
        segs.append(_Segment(s, e, cursor))
        cursor += e - s
    return segs, cursor


def _whole(ws: Workspace, tracks: list[Track]) -> mido.MidiFile:
    """Lossless export: every event at its workspace position, unmodified."""
    out_tracks = []
    for track in tracks:
        items = []
        for ci, clip in enumerate(track.clips):
            for ev in clip.events:
                items.append(_Item(clip.offset + ev.time, (0, ci, ev.seq), ev.msg))
        out_tracks.append((track, items, track.end))
    conductor = _tempo_items(ws.tempo_map, [_Segment(ZERO, None, ZERO)], preserve=True)
    end = max((t.end for t in tracks), default=ZERO)
    return _serialize(ws, tracks, conductor, out_tracks, end)


def _segmented(ws: Workspace, tracks: list[Track], segs: list[_Segment], opts: ExportOptions,
               preserve: bool, end: Fraction) -> mido.MidiFile:
    out_tracks = []
    for track in tracks:
        items: list[_Item] = []
        for si, seg in enumerate(segs):
            items.extend(_extract(track, seg, si, opts.partial_notes))
        out_tracks.append((track, items, end))
    conductor = _tempo_items(ws.tempo_map, segs, preserve=preserve, until=end if preserve else None)
    return _serialize(ws, tracks, conductor, out_tracks, end)


def _state_key(msg: Msg) -> tuple | None:
    t = msg.type
    if t == "control_change":
        return None if msg.control in MODE_CCS else (msg.channel, "cc", msg.control)
    if t == "program_change":
        return (msg.channel, "pc")
    if t == "pitchwheel":
        return (msg.channel, "pw")
    if t == "aftertouch":
        return (msg.channel, "at")
    if t == "key_signature":
        return ("ks",)
    return None


def _extract(track: Track, seg: _Segment, si: int, partial_notes: bool) -> list[_Item]:
    s, e, dst = seg.start, seg.end, seg.dst
    assert e is not None

    def out_time(t: Fraction) -> Fraction:
        return dst + (t - s)

    items: list[_Item] = []
    state: dict[tuple, tuple[Fraction, int, Event]] = {}
    for clip in track.clips:
        off = clip.offset
        if off >= e:
            continue
        notes, orphans = pair_notes(clip.events, clip.length)
        orphan_ids = {id(o) for o in orphans}
        for n in notes:
            ns, ne = n.start + off, n.end + off
            sounding = (ns < e and ne > s) or (ns == ne and s <= ns < e)
            if not sounding or (ns < s and not partial_notes):
                continue
            if ns >= s:
                items.append(_Item(out_time(ns), (si, 1, n.on.seq), n.on.msg))
            else:
                items.append(_Item(out_time(s), (si, 1, n.on.seq), n.on.msg))
            if n.off is not None and ne <= e:
                items.append(_Item(out_time(ne), (si, 1, n.off.seq), n.off.msg))
            else:
                items.append(_Item(out_time(min(ne, e)), (si, 2, n.on.seq),
                                   mido.Message("note_off", channel=n.channel, note=n.pitch, velocity=0)))
        for ev in clip.events:
            m = ev.msg
            if (is_note_on(m) or is_note_off(m)) and id(ev) not in orphan_ids:
                continue
            t = ev.time + off
            if s <= t < e:
                items.append(_Item(out_time(t), (si, 1, ev.seq), m))
            elif t < s:
                k = _state_key(m)
                if k is not None:
                    cur = state.get(k)
                    if cur is None or (t, ev.seq) >= (cur[0], cur[1]):
                        state[k] = (t, ev.seq, ev)
    for _t, seq, ev in sorted(state.values(), key=lambda v: (v[0], v[1])):
        items.append(_Item(dst, (si, 0, seq), ev.msg))
    return items


def _tempo_items(tmap: TempoMap, segs: list[_Segment], preserve: bool,
                 until: Fraction | None = None) -> list[_Item]:
    items: list[_Item] = []
    if preserve:
        for i, c in enumerate(tmap.effective_tempos()):
            if until is None or c.time < until or c.time == 0:
                items.append(_Item(c.time, (0, 1, i), mido.MetaMessage("set_tempo", tempo=c.us_per_beat)))
        for i, c in enumerate(tmap.effective_timesigs()):
            if until is None or c.time < until or c.time == 0:
                items.append(_Item(c.time, (0, 0, i), _ts_msg(c)))
        return items
    last_tempo = last_ts = None
    for si, seg in enumerate(segs):
        assert seg.end is not None
        tempos = [tmap.tempo_at(seg.start)] + [c for c in tmap.tempos if seg.start < c.time < seg.end]
        sigs = [tmap.timesig_at(seg.start)] + [c for c in tmap.timesigs if seg.start < c.time < seg.end]
        for i, c in enumerate(tempos):
            if c.us_per_beat != last_tempo:
                t = seg.dst + max(c.time - seg.start, ZERO)
                items.append(_Item(t, (si, 1, i), mido.MetaMessage("set_tempo", tempo=c.us_per_beat)))
                last_tempo = c.us_per_beat
        for i, c in enumerate(sigs):
            sig = (c.numerator, c.denominator)
            if sig != last_ts or (i == 0 and si > 0):
                t = seg.dst + max(c.time - seg.start, ZERO)
                items.append(_Item(t, (si, 0, i), _ts_msg(c)))
                last_ts = sig
    return items


def _ts_msg(c) -> mido.MetaMessage:
    return mido.MetaMessage("time_signature", numerator=c.numerator, denominator=c.denominator,
                            clocks_per_click=c.clocks_per_click,
                            notated_32nd_notes_per_beat=c.notated_32nd)


def encode_meta_text(display: str, original_raw: str) -> str:
    """Return the latin-1 'raw' string mido should write for a display name.

    Unchanged names are written with their original bytes; edited names are
    written as UTF-8 (the de-facto standard in current DAWs).
    """
    if original_raw and display == display_text(mido.MetaMessage("track_name", name=original_raw)):
        return original_raw
    return display.encode("utf-8").decode("latin-1")


def _serialize(ws: Workspace, tracks: list[Track], conductor: list[_Item],
               out_tracks: list[tuple[Track, list[_Item], Fraction]], end: Fraction) -> mido.MidiFile:
    src_ppqs = {ws.source(t.source_id).ppq for t in tracks if ws.source(t.source_id)}
    all_times = [i.time for i in conductor] + [end]
    for _t, items, tend in out_tracks:
        all_times.extend(i.time for i in items)
        all_times.append(tend)
    ppq = choose_ppq(src_ppqs, all_times)

    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    mf.tracks.append(_to_mido_track(conductor, end, ppq, name=None))
    for track, items, tend in out_tracks:
        name = encode_meta_text(track.name, track.original_name)
        mf.tracks.append(_to_mido_track(items, tend, ppq, name=name))
    return mf


def _tick(t: Fraction, ppq: int) -> int:
    return math.floor(t * ppq + Fraction(1, 2))


def _to_mido_track(items: list[_Item], end: Fraction, ppq: int, name: str | None) -> mido.MidiTrack:
    trk = mido.MidiTrack()
    prev = 0
    if name is not None:
        trk.append(mido.MetaMessage("track_name", name=name, time=0))
    for it in sorted(items):
        tick = max(_tick(it.time, ppq), prev)
        trk.append(it.msg.copy(time=tick - prev))
        prev = tick
    trk.append(mido.MetaMessage("end_of_track", time=max(_tick(end, ppq), prev) - prev))
    return trk


def _safe(label: str) -> str:
    return "".join(c if c.isalnum() or c in " -_()" else "_" for c in label).strip() or "range"
