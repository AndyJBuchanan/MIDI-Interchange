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

Clip trims (edge trims) use these same rules, from the same code
(``clip_window`` and ``_extract``): a clip's window is the segment's span cut
to the clip's visible edges, where a trim is set. A note that started before
the trimmed start follows ``partial_notes``, a note running past the trimmed
end is released there, the settings in force are written at the window's
start, and lyrics, text and markers outside the trims are dropped. A whole
export writes untrimmed clips exactly as imported and sends only trimmed
clips through this code (over an open-ended segment).

Track selection: a whole export takes the enabled tracks (the track toggles).
A range export takes every track and asks each range which tracks it
includes (``Range.excluded``); the track toggles are not consulted. A track
is silent in a range that excludes it (the range still takes its time in the
output) and is left out of the file when no exported range includes it.
``track_ids`` narrows the candidates in both cases.

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

from .document import Clip, Track, Workspace
from .events import MODE_CCS, Event, Msg, display_text, is_note_off, is_note_on, pair_notes
from .names import range_label, safe_filename
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
    track_ids: list[str] | None = None      # None -> all tracks (whole: enabled tracks)
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
    ranges = [r for r in (ws.ranges if opts.ranges is None else opts.ranges) if not r.is_empty]
    mode = opts.mode if ranges else ExportMode.WHOLE
    tracks = export_tracks(ws, opts.track_ids, None if mode is ExportMode.WHOLE else ranges)

    if mode is ExportMode.WHOLE:
        if opts.trim:
            bounds = content_bounds(tracks, ZERO, None)
            if bounds is None:
                return [ExportResult("", _whole(ws, tracks, opts.partial_notes))]
            return [ExportResult("", _segmented(ws, tracks, [_Segment(bounds[0], bounds[1], ZERO)],
                                                opts, preserve=False, end=bounds[1] - bounds[0]))]
        return [ExportResult("", _whole(ws, tracks, opts.partial_notes))]

    if mode is ExportMode.PRESERVE:
        spans = merge_ranges(ranges)
        segs = [_Segment(s, e, s) for s, e in spans]
        end = spans[-1][1]
        # each track keeps the union of the ranges that include it
        own = {t.id: [_Segment(s, e, s) for s, e in merge_ranges([r for r in ranges if r.includes(t.id)])]
               for t in tracks}
        if opts.trim:
            his = [b[1] for t in tracks for sg in own[t.id]
                   if (b := content_bounds([t], sg.start, sg.end)) is not None]
            if his:
                end = max(his)
        return [ExportResult("", _segmented(ws, tracks, segs, opts, preserve=True, end=end, own=own))]

    if mode is ExportMode.REBASE:
        segs, end, own = _concat_segments(ranges, tracks, opts.trim)
        return [ExportResult("", _segmented(ws, tracks, segs, opts, preserve=False, end=end, own=own))]

    results = []
    for i, r in enumerate(ranges):
        in_range = [t for t in tracks if r.includes(t.id)]
        if not in_range:
            continue
        segs, end, _own = _concat_segments([r], in_range, opts.trim)
        label = range_label(r.name, i)
        results.append(ExportResult(label, _segmented(ws, in_range, segs, opts, preserve=False, end=end)))
    return results


def export_tracks(ws: Workspace, track_ids: list[str] | None = None,
                  ranges: list[Range] | None = None) -> list[Track]:
    """Tracks that go into an export. ``ranges`` None = whole export (track
    toggles); otherwise every track some range includes (range toggles)."""
    if ranges is None:
        pool = ws.global_tracks()
    else:
        pool = [t for t in ws.tracks if any(r.includes(t.id) for r in ranges if not r.is_empty)]
    if track_ids is None:
        return list(pool)
    wanted = set(track_ids)
    return [t for t in pool if t.id in wanted]


def export_name(tracks: list[Track], ranges: list[Range] | None) -> str:
    """Suggested name: range labels in export order, else a track or default.
    ``ranges`` None = whole export."""
    names: list[str] = []
    for i, r in enumerate(ranges or []):
        label = range_label(r.name, i)
        if not r.is_empty and label not in names:
            names.append(label)
    if names:
        return " + ".join(names)
    return tracks[0].name if len(tracks) == 1 else "MIDI Interchange Export"


def save_exports(results: list[ExportResult], path: str, label_only: bool = False) -> list[str]:
    """Write results; multiple results get the range label appended
    ("out - Verse.mid"), or with label_only are named by it alone
    ("Verse.mid", for drag-out). Clashing names get a number."""
    import os

    paths = []
    stem, ext = os.path.splitext(path)
    ext = ext or ".mid"
    for res in results:
        if len(results) == 1:
            base = stem
        elif label_only:
            base = os.path.join(os.path.dirname(stem), safe_filename(res.label))
        else:
            base = f"{stem} - {safe_filename(res.label, 'range')}"
        p, n = f"{base}{ext}", 2
        while p in paths:
            p, n = f"{base} ({n}){ext}", n + 1
        res.midi.save(p)
        paths.append(p)
    return paths


def clip_window(clip: Clip, s: Fraction, e: Fraction | None) -> tuple[Fraction, Fraction | None]:
    """The part of segment [s, e) (e None = unbounded) that a clip can show:
    the segment cut to the clip's trims. A side that isn't trimmed doesn't
    cut, so untrimmed clips keep the segment's own edges."""
    lo = max(s, clip.start) if clip.trim_start > ZERO else s
    hi = e
    if clip.trim_end < clip.length:
        hi = clip.end if e is None else min(e, clip.end)
    return lo, hi


def _sounding(clip: Clip, lo: Fraction, hi: Fraction | None, notes=None):
    """(note, start, end) in workspace time, for notes sounding in [lo, hi)."""
    for n in (pair_notes(clip.events, clip.length)[0] if notes is None else notes):
        ns, ne = n.start + clip.offset, n.end + clip.offset
        if hi is not None and ns >= hi:
            continue
        if ne <= lo and not (ns == ne == lo):
            continue
        yield n, ns, ne


def content_bounds(tracks: Iterable[Track], s: Fraction, e: Fraction | None) -> tuple[Fraction, Fraction] | None:
    """First/last instant of notes or lyrics within [s, e) across tracks,
    inside each clip's trims."""
    lo: Fraction | None = None
    hi: Fraction | None = None
    for track in tracks:
        for clip in track.clips:
            w0, w1 = clip_window(clip, s, e)
            for _n, ns, ne in _sounding(clip, w0, w1):
                a = max(ns, w0)
                b = ne if w1 is None else min(ne, w1)
                lo = a if lo is None else min(lo, a)
                hi = b if hi is None else max(hi, b)
            for ev in clip.events:
                if ev.msg.type == "lyrics":
                    t = ev.time + clip.offset
                    if t >= w0 and (w1 is None or t < w1):
                        lo = t if lo is None else min(lo, t)
                        hi = t if hi is None else max(hi, t)
    if lo is None or hi is None:
        return None
    return lo, hi


def visible_msgs(clip: Clip) -> list[Msg]:
    """The messages a clip contributes to an export of the whole timeline: all
    of an untrimmed clip's, or what its trims leave (the same cutting as an
    export). For counts and channel badges."""
    if not clip.is_trimmed:
        return [ev.msg for ev in clip.events]
    items = _extract_clips([clip], _Segment(ZERO, None, ZERO), 0, True)
    return [it.msg for it in items]


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

def _concat_segments(ranges: list[Range], tracks: list[Track],
                     trim: bool) -> tuple[list[_Segment], Fraction, dict[str, list[_Segment]]]:
    """Ranges end to end. Returns the segments, the output end, and per track
    the segments of the ranges that include it."""
    segs: list[_Segment] = []
    own: dict[str, list[_Segment]] = {t.id: [] for t in tracks}
    cursor = ZERO
    for r in ranges:
        members = [t for t in tracks if r.includes(t.id)]
        s, e = r.start, r.end
        if trim:
            b = content_bounds(members, s, e)
            if b is None:
                continue
            s, e = b
        seg = _Segment(s, e, cursor)
        segs.append(seg)
        for t in members:
            own[t.id].append(seg)
        cursor += e - s
    return segs, cursor, own


def _whole(ws: Workspace, tracks: list[Track], partial_notes: bool = True) -> mido.MidiFile:
    """Lossless export: every event of an untrimmed clip at its workspace
    position, unmodified. Trimmed clips go through the edge rules."""
    out_tracks = []
    whole = _Segment(ZERO, None, ZERO)
    for track in tracks:
        items = []
        for ci, clip in enumerate(track.clips):
            if clip.is_trimmed:
                continue
            for ev in clip.events:
                items.append(_Item(clip.offset + ev.time, (0, ci, ev.seq), ev.msg))
        items.extend(_extract_clips([c for c in track.clips if c.is_trimmed], whole, 0, partial_notes))
        out_tracks.append((track, items, track.end))
    conductor = _tempo_items(ws.tempo_map, [whole], preserve=True)
    end = max((t.end for t in tracks), default=ZERO)
    return _serialize(ws, tracks, conductor, out_tracks, end)


def _segmented(ws: Workspace, tracks: list[Track], segs: list[_Segment], opts: ExportOptions,
               preserve: bool, end: Fraction, own: dict[str, list[_Segment]] | None = None) -> mido.MidiFile:
    """``segs`` drive the conductor; ``own`` (default: all of segs) gives each
    track the segments it takes part in."""
    out_tracks = []
    for track in tracks:
        items: list[_Item] = []
        for si, seg in enumerate(segs if own is None else own[track.id]):
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
    return _extract_clips(track.clips, seg, si, partial_notes)


def _extract_clips(clips: list[Clip], seg: _Segment, si: int, partial_notes: bool) -> list[_Item]:
    """The edge rules (module docstring). Each clip is cut to its own window
    (the segment within the clip's trims); settings are carried to the start
    of that window, merged across clips that share it."""
    s, dst = seg.start, seg.dst

    def out_time(t: Fraction) -> Fraction:
        return dst + (t - s)

    items: list[_Item] = []
    state: dict[tuple, tuple[Fraction, int, Event]] = {}     # (window start, key) -> latest event before it
    for clip in clips:
        off = clip.offset
        lo, hi = clip_window(clip, s, seg.end)
        if seg.end is not None and lo >= seg.end:
            continue
        cut_end = clip.end if clip.trim_end < clip.length else None   # settings after a trimmed end are gone
        notes, orphans = pair_notes(clip.events, clip.length)
        orphan_ids = {id(o) for o in orphans}
        for n, ns, ne in _sounding(clip, lo, hi, notes):
            if ns < lo and not partial_notes:
                continue
            items.append(_Item(out_time(max(ns, lo)), (si, 1, n.on.seq), n.on.msg))
            if n.off is not None and (hi is None or ne <= hi):
                items.append(_Item(out_time(ne), (si, 1, n.off.seq), n.off.msg))
            else:
                end_t = ne if hi is None else min(ne, hi)
                items.append(_Item(out_time(end_t), (si, 2, n.on.seq),
                                   mido.Message("note_off", channel=n.channel, note=n.pitch, velocity=0)))
        for ev in clip.events:
            m = ev.msg
            if (is_note_on(m) or is_note_off(m)) and id(ev) not in orphan_ids:
                continue
            t = ev.time + off
            if t >= lo and (hi is None or t < hi):
                items.append(_Item(out_time(t), (si, 1, ev.seq), m))
            elif t < lo and (cut_end is None or t < cut_end):
                k = _state_key(m)
                if k is not None:
                    key = (lo, k)
                    cur = state.get(key)
                    if cur is None or (t, ev.seq) >= (cur[0], cur[1]):
                        state[key] = (t, ev.seq, ev)
    for (lo, _k), (_t, seq, ev) in sorted(state.items(), key=lambda kv: (kv[0][0], kv[1][0], kv[1][1])):
        items.append(_Item(out_time(lo), (si, 0, seq), ev.msg))
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
    src_ppqs = {ws.source(sid).ppq for t in tracks for sid in t.source_ids() if ws.source(sid)}
    all_times = [i.time for i in conductor] + [end]
    for _t, items, tend in out_tracks:
        all_times.extend(i.time for i in items)
        all_times.append(tend)
    ppq = choose_ppq(src_ppqs, all_times)

    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
    song = export_song(ws, tracks)
    mf.tracks.append(_to_mido_track(conductor, end, ppq, name=encode_meta_text(song, "") if song else None))
    for track, items, tend in out_tracks:
        name = encode_meta_text(track.name, track.original_name)
        mf.tracks.append(_to_mido_track(items, tend, ppq, name=name))
    return mf


def export_song(ws: Workspace, tracks: list[Track]) -> str:
    """The song title to write as the conductor track's name: the one song
    every exported clip's source shares, else none. Keeps the title through a
    round trip so name matching can remove it again (placement.py)."""
    songs = set()
    for t in tracks:
        for c in t.clips:
            src = ws.source(c.source_id)
            songs.add(src.song if src else "")
    return songs.pop() if len(songs) == 1 else ""


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

