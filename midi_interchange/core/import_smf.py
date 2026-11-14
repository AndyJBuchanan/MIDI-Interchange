"""Standard MIDI File import -> canonical model.

Policy:
* Tempo and time-signature meta events are lifted out of tracks into the
  source's TempoMap (they are global in SMF format 0/1).
* The first track_name meta at tick 0 becomes the track name; it is
  regenerated on export from the (possibly renamed) workspace track.
* end_of_track is dropped; its position becomes the clip length.
* Format 0: split into one track per MIDI channel, plus an auxiliary track for
  remaining meta/SysEx events. Original channels and event order are kept.
* Format 1 (and 2, with a warning): one workspace track per SMF track. Tracks
  left empty after lifting timing events (a pure conductor track) are dropped;
  tracks holding only meta/SysEx (lyrics, markers) become auxiliary tracks.
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from fractions import Fraction

import mido

from .document import Clip, Source, Track, new_id, track_channels
from .events import Event, display_text, is_channel_msg
from .names import song_title
from .timing import TempoChange, TempoMap, TimeSigChange


class ImportError_(Exception):
    """Raised when a payload cannot be interpreted as a Standard MIDI File."""


def _parse(data: bytes) -> tuple[mido.MidiFile, list[str]]:
    if not data.startswith(b"MThd"):
        raise ImportError_("Not a Standard MIDI File (missing MThd header)")
    warnings: list[str] = []
    try:
        mf = mido.MidiFile(file=io.BytesIO(data))
    except (ValueError, OSError) as exc:
        # Some writers emit out-of-range data bytes; clip rather than reject.
        try:
            mf = mido.MidiFile(file=io.BytesIO(data), clip=True)
            warnings.append(f"Malformed data bytes were clipped to 0–127 ({exc})")
        except Exception as exc2:  # noqa: BLE001 - surface any parser failure
            raise ImportError_(f"Could not parse MIDI data: {exc2}") from exc2
    except Exception as exc:  # noqa: BLE001
        raise ImportError_(f"Could not parse MIDI data: {exc}") from exc
    if mf.ticks_per_beat & 0x8000 or mf.ticks_per_beat <= 0:
        raise ImportError_("SMPTE time division is not supported")
    return mf, warnings


def import_smf_bytes(data: bytes, name: str, path: str | None = None,
                     app: str | None = None, *, byte_size: int | None = None) -> tuple[Source, list[Track]]:
    """Keep derived source metadata and musical data, without retaining the input.

    Transports can supply the original size when they unwrap a MIDI payload.
    Otherwise the bytes supplied here are the original input.
    """
    mf, warnings = _parse(data)
    ppq = mf.ticks_per_beat
    if mf.type == 2:
        warnings.append("SMF format 2 (independent patterns) imported as parallel tracks")

    source_id = new_id()
    tempos: list[TempoChange] = []
    sigs: list[TimeSigChange] = []
    seq = 0

    # (original index, name, events, end_time)
    raw_tracks: list[tuple[int, str, list[Event], Fraction]] = []
    display_names: list[str] = []
    for ti, mtrack in enumerate(mf.tracks):
        tick = 0
        events: list[Event] = []
        end_time = Fraction(0)
        name_ev = None
        for msg in mtrack:
            tick += msg.time
            t = Fraction(tick, ppq)
            seq += 1
            if msg.type == "end_of_track":
                end_time = max(end_time, t)
                continue
            if msg.type == "set_tempo":
                tempos.append(TempoChange(t, msg.tempo))
                continue
            if msg.type == "time_signature":
                sigs.append(TimeSigChange(t, msg.numerator, msg.denominator,
                                          msg.clocks_per_click, msg.notated_32nd_notes_per_beat))
                continue
            if msg.type == "track_name" and tick == 0 and name_ev is None:
                name_ev = msg
                continue
            events.append(Event(t, msg, seq))
        if events:
            end_time = max(end_time, events[-1].time)
        raw_tracks.append((ti, name_ev.name if name_ev else "", events, end_time))
        display_names.append(display_text(name_ev) if name_ev else "")

    stem = os.path.splitext(name)[0]
    tracks: list[Track] = []

    def make_track(label: str, original: str, events: list[Event], end: Fraction, ti: int) -> Track:
        chans = track_channels(events)
        return Track(
            id=new_id(), name=label, source_id=source_id, original_name=original,
            clips=[Clip(id=new_id(), events=events, length=end, source_track_index=ti, name=label,
                         source_id=source_id)],
            auxiliary=not chans, channels=chans,
        )

    if mf.type == 0 and raw_tracks:
        ti, tname, events, end = raw_tracks[0]
        base = display_names[0] or stem
        by_channel: dict[int, list[Event]] = {}
        other: list[Event] = []
        for ev in events:
            if is_channel_msg(ev.msg):
                by_channel.setdefault(ev.msg.channel, []).append(ev)
            else:
                other.append(ev)
        for ch in sorted(by_channel):
            label = f"{base} · Ch {ch + 1}" if len(by_channel) > 1 else base
            tracks.append(make_track(label, tname, by_channel[ch], end, ti))
        if other:
            tracks.append(make_track(f"{base} · Meta", tname, other, end, ti))
    else:
        for ti, tname, events, end in raw_tracks:
            if not events:
                continue  # pure conductor / empty track
            fallback = f"{stem} · Meta" if not track_channels(events) else (
                stem if len(mf.tracks) <= 2 else f"{stem} {ti + 1}")
            label = display_names[ti] or fallback
            tracks.append(make_track(label, tname, events, end, ti))

    conductor = ""
    if mf.type == 1 and raw_tracks and not track_channels(raw_tracks[0][2]):
        conductor = display_names[0]
    source = Source(
        id=source_id, name=name, ppq=ppq, smf_format=mf.type,
        imported_at=datetime.now(), tempo_map=TempoMap(tempos, sigs),
        path=path, app=app, track_names=tuple(display_names),
        warnings=tuple(warnings),
        song=song_title(conductor, [t.name for t in tracks]),
        byte_size=len(data) if byte_size is None else byte_size,
    )
    return source, tracks


def import_smf_file(path: str, app: str | None = None) -> tuple[Source, list[Track]]:
    with open(path, "rb") as fh:
        data = fh.read()
    return import_smf_bytes(data, os.path.basename(path), path=path, app=app)
