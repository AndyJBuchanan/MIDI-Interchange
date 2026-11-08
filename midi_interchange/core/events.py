"""Canonical event representation.

Each event wraps the original mido message (whose own ``time`` attribute is
ignored) with an exact absolute time and a stable sequence number. Keeping the
parsed message object preserves payloads verbatim: SysEx bytes, unknown meta
events (``UnknownMetaMessage``), sequencer-specific data and text events, which
mido decodes as latin-1 and therefore round-trips byte-exactly.

Events are treated as immutable once imported; clips share event lists freely.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import mido

Msg = mido.Message | mido.MetaMessage

# Meta types that live in the workspace tempo map rather than in tracks.
TIMING_META = {"set_tempo", "time_signature"}
# Meta types shown as indicators on the timeline.
TEXT_META = {"lyrics", "text", "marker", "cue_marker", "copyright",
             "instrument_name", "program_name", "device_name"}
# Channel-mode CCs (All Sound Off, Reset All, All Notes Off, ...) are not
# carried as state into an exported range.
MODE_CCS = range(120, 128)


@dataclass(slots=True)
class Event:
    time: Fraction  # quarter notes, relative to the owning clip's start
    msg: Msg
    seq: int        # original order within the source file; ties broken by this

    @property
    def type(self) -> str:
        return self.msg.type

    @property
    def channel(self) -> int | None:
        return getattr(self.msg, "channel", None)


def is_note_on(msg: Msg) -> bool:
    return msg.type == "note_on" and msg.velocity > 0


def is_note_off(msg: Msg) -> bool:
    return msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0)


def is_channel_msg(msg: Msg) -> bool:
    return not msg.is_meta and msg.type != "sysex"


def display_text(msg: Msg) -> str:
    """Best-effort human-readable text for a text meta event.

    mido decodes meta text as latin-1 (lossless). Most modern tools write UTF-8,
    so try re-decoding for display; the stored message is never altered.
    """
    text = getattr(msg, "text", None) or getattr(msg, "name", None) or ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


@dataclass(slots=True)
class Note:
    start: Fraction
    end: Fraction
    channel: int
    pitch: int
    velocity: int
    on: Event
    off: Event | None  # None when the note was never released in the source


def pair_notes(events: list[Event], end_time: Fraction) -> tuple[list[Note], list[Event]]:
    """Pair note-on/off events FIFO per (channel, pitch).

    FIFO matches how most synths and DAWs resolve overlapping notes of the same
    pitch. Unreleased notes are closed at ``end_time``. Returns (notes sorted by
    start, orphan note-off events).
    """
    open_notes: dict[tuple[int, int], list[Event]] = {}
    notes: list[Note] = []
    orphans: list[Event] = []
    for ev in events:
        m = ev.msg
        if is_note_on(m):
            open_notes.setdefault((m.channel, m.note), []).append(ev)
        elif is_note_off(m):
            stack = open_notes.get((m.channel, m.note))
            if stack:
                on = stack.pop(0)
                notes.append(Note(on.time, ev.time, m.channel, m.note, on.msg.velocity, on, ev))
            else:
                orphans.append(ev)
    for (ch, pitch), stack in open_notes.items():
        for on in stack:
            notes.append(Note(on.time, max(end_time, on.time), ch, pitch, on.msg.velocity, on, None))
    notes.sort(key=lambda n: (n.start, n.on.seq))
    return notes, orphans
