"""Synthetic MIDI builders for tests."""
from __future__ import annotations

import io
from fractions import Fraction

import mido

from midi_interchange.core.document import Workspace
from midi_interchange.core.import_smf import import_smf_bytes


def track(events: list[tuple[int, mido.Message | mido.MetaMessage]], name: str | None = None) -> mido.MidiTrack:
    """events: (absolute tick, msg). Stable order for equal ticks."""
    trk = mido.MidiTrack()
    if name is not None:
        trk.append(mido.MetaMessage("track_name", name=name, time=0))
    prev = 0
    for tick, msg in sorted(events, key=lambda e: e[0]):
        trk.append(msg.copy(time=tick - prev))
        prev = tick
    trk.append(mido.MetaMessage("end_of_track", time=0))
    return trk


def conductor(ppq: int, tempos=((0, 120.0),), sigs=((0, 4, 4),), extra=()) -> mido.MidiTrack:
    ev = [(t, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))) for t, bpm in tempos]
    ev += [(t, mido.MetaMessage("time_signature", numerator=n, denominator=d)) for t, n, d in sigs]
    ev += list(extra)
    return track(ev)


def on(ch, note, vel=100):
    return mido.Message("note_on", channel=ch, note=note, velocity=vel)


def off(ch, note, vel=0):
    return mido.Message("note_off", channel=ch, note=note, velocity=vel)


def note(ch, pitch, start, dur, vel=100):
    return [(start, on(ch, pitch, vel)), (start + dur, off(ch, pitch))]


def cc(ch, control, value):
    return mido.Message("control_change", channel=ch, control=control, value=value)


def to_bytes(mf: mido.MidiFile) -> bytes:
    buf = io.BytesIO()
    mf.save(file=buf)
    return buf.getvalue()


def smf(tracks: list[mido.MidiTrack], ppq: int = 480, type_: int = 1) -> bytes:
    mf = mido.MidiFile(type=type_, ticks_per_beat=ppq)
    mf.tracks.extend(tracks)
    return to_bytes(mf)


def load(data: bytes, name: str = "test.mid", ws: Workspace | None = None) -> Workspace:
    ws = ws or Workspace()
    src, tracks = import_smf_bytes(data, name)
    ws.add_import(src, tracks)
    return ws


def reparse(mf: mido.MidiFile) -> mido.MidiFile:
    return mido.MidiFile(file=io.BytesIO(to_bytes(mf)))


def abs_events(mtrack: mido.MidiTrack, ppq: int) -> list[tuple[Fraction, mido.Message]]:
    out, tick = [], 0
    for m in mtrack:
        tick += m.time
        out.append((Fraction(tick, ppq), m))
    return out


def notes_of(mtrack: mido.MidiTrack, ppq: int) -> list[tuple[Fraction, Fraction, int, int]]:
    """(start, end, channel, pitch) from an exported track, FIFO paired; asserts no stuck notes."""
    open_: dict[tuple[int, int], list[Fraction]] = {}
    res = []
    for t, m in abs_events(mtrack, ppq):
        if m.type == "note_on" and m.velocity > 0:
            open_.setdefault((m.channel, m.note), []).append(t)
        elif m.type in ("note_off", "note_on"):
            starts = open_.get((m.channel, m.note))
            assert starts, f"orphan note-off {m} at {t}"
            res.append((starts.pop(0), t, m.channel, m.note))
    stuck = [k for k, v in open_.items() if v]
    assert not stuck, f"stuck notes: {stuck}"
    return sorted(res)


def track_by_name(mf: mido.MidiFile, name: str) -> mido.MidiTrack:
    for t in mf.tracks:
        if any(m.type == "track_name" and m.name == name for m in t):
            return t
    raise KeyError(name)
