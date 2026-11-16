"""Read the MIDI arrangement of a Cubase 15/16 project (.cpr), read-only.

Decoding: cpr_format. Format findings, evidence and decisions:
docs/plans/cubase-import.md. Returns the same (Source, tracks) result as the
other readers. Material the reader cannot represent is reported in the
source warnings; malformed or unsupported projects fail before the workspace
changes.
"""
from __future__ import annotations

import os
import struct
from datetime import datetime
from fractions import Fraction as F

import mido

from . import cpr_format as cf
from .document import Clip, Source, Track, new_id, track_channels
from .events import Event
from .import_smf import ImportError_
from .timing import TempoChange, TempoMap, TimeSigChange

MAX_CPR_BYTES = 256 * 1024 * 1024
MAX_EVENTS = 1_000_000
SUPPORTED_MAJOR = (15, 16)
TICKS = 480                 # Cubase positions: ticks per quarter note
MAX_TIME = 1_000_000        # quarter notes; session/workspace bound
DEFAULT_RELEASE = 64
SKIPPED_OBJECTS = {'MScoreEvent': 'Score Editor symbols and text in parts are not imported'}


def _ticks(value: float) -> F:
    """Cubase stores f64 ticks, sometimes fractional (e.g. 102.953)."""
    if value != value or abs(value) > MAX_TIME * TICKS:
        raise ValueError('Position out of bounds')
    return F(value).limit_denominator(10**6) / TICKS


def _tempo_map(wk: cf.Walker, warn) -> TempoMap:
    """Tempo points, with ramps approximated by one step per beat at the
    tempo of each step's midpoint (as Cubase's own MIDI export does), and
    time-signature points. Ramps are linear in beats (tier 3 c20)."""
    tempos: list[TempoChange] = []
    ev = next((o for o in wk.objects.values() if o.cls.name == 'MTempoTrackEvent'), None)
    if ev is not None:
        points, _ = cf.tempo_points(wk, ev)
        prev = None
        for pt in points:
            if not 1 <= pt.bpm <= 1000 or pt.ticks < 0:
                raise ValueError('Invalid tempo point')
            beat = _ticks(pt.ticks)
            if pt.ramp and prev is not None and beat > prev[0]:
                warn('Tempo ramps are approximated with a tempo step every beat')
                b0, bpm0 = prev
                k = 0
                while b0 + k < beat:
                    a, b = b0 + k, min(b0 + k + 1, beat)
                    mid = (a + b) / 2
                    bpm = bpm0 + (pt.bpm - bpm0) * float((mid - b0) / (beat - b0))
                    tempos.append(TempoChange(a, round(60_000_000 / bpm)))
                    k += 1
            tempos.append(TempoChange(beat, round(60_000_000 / pt.bpm)))
            prev = (beat, pt.bpm)
    sigs: list[TimeSigChange] = []
    sig = next((o for o in wk.objects.values() if o.cls.name == 'MSignatureTrackEvent'), None)
    if sig is not None:
        for ticks, num, den in cf.signature_points(wk, sig):
            if not 1 <= num <= 255 or den not in (1, 2, 4, 8, 16, 32, 64, 128):
                raise ValueError('Invalid time signature')
            sigs.append(TimeSigChange(_ticks(ticks), num, den))
    return TempoMap(tempos, sigs)


def _message(e: cf.CprEvent, warn):
    """A non-note event as a mido message, or None if not representable."""
    ch = e.channel
    a, b = e.data[0], e.data[1]
    if e.status == 0xB0:
        if 'cuOb' in e.props:
            warn('Controller curve shapes are not rendered; only the stored points are imported')
        return mido.Message('control_change', channel=ch, control=a, value=b)
    if e.status == 0xE0:
        if 'cuOb' in e.props:
            warn('Controller curve shapes are not rendered; only the stored points are imported')
        return mido.Message('pitchwheel', channel=ch, pitch=(b << 7 | a) - 8192)
    if e.status == 0xC0:
        return mido.Message('program_change', channel=ch, program=a)
    if e.status == 0xA0:
        return mido.Message('polytouch', channel=ch, note=a, value=b)
    if e.status == 0xD0:
        return mido.Message('aftertouch', channel=ch, value=a)
    return None


def _clip_events(wk: cf.Walker, part: cf.Obj, label: str, warn, counter, transpose: int = 0) -> list[Event]:
    """Events in content time (quarter notes from the part's content zero).
    transpose: the track's MIDI Modifiers transpose, added to note numbers as
    Cubase's MIDI export does (GA's Prologue: +24)."""
    raw, problems, info = cf.decode_part_events(wk, part)
    for problem in problems:
        warn(f'{label}: {problem}; later events in this part are not imported')
    for cls in info.get('skipped', {}):
        warn(SKIPPED_OBJECTS.get(cls, f'Part objects of type {cls} are not imported'))
    out: list[tuple[F, mido.Message]] = []
    for e in raw:
        if e.muted:
            # Muted in Cubase's editors: silent, and left out of its MIDI export
            # (GA's kit: all 2,399 flagged notes absent from the export).
            warn('Muted notes are not imported')
            continue
        if e.channel > 15 or any(x > 127 for x in e.data[:1 if e.status in (0xC0, 0xD0) else 2]):
            # Cubase can store out-of-range values (orchestral verify file:
            # one aftertouch value of 201). Skip the event, keep the import.
            warn('Events with out-of-range MIDI values were skipped')
            continue
        at = _ticks(e.position)
        if transpose and e.status in (0x90, 0xA0):
            note = e.data[0] + transpose
            if not 0 <= note <= 127:
                warn('Notes transposed outside 0-127 by a track transpose were skipped')
                continue
            e = cf.CprEvent(e.status, e.position, e.channel, bytes([note]) + e.data[1:], e.props,
                            e.length, e.tail, e.framed, e.flags)
        if e.status == 0x90:
            if e.length is None or e.length < 0:
                raise ValueError(f'{label}: invalid note length')
            off = e.props.get('OffV')
            release = round(1 + 126 * off) if isinstance(off, float) and 0 <= off <= 1 else DEFAULT_RELEASE
            out.append((at, mido.Message('note_on', channel=e.channel, note=e.data[0], velocity=max(1, e.data[1]))))
            out.append((at + _ticks(e.length), mido.Message('note_off', channel=e.channel, note=e.data[0],
                                                            velocity=max(0, min(127, release)))))
        else:
            msg = _message(e, warn)
            if msg is None:
                warn(f'MIDI events of type 0x{e.status:02X} are not imported')
                continue
            out.append((at, msg))
    counter[0] += len(out)
    if counter[0] > MAX_EVENTS:
        raise ValueError('Project exceeds the MIDI event limit')
    ordered = sorted(enumerate(out), key=lambda x: (x[1][0], x[0]))
    return [Event(t, m, i) for i, (t, m) in ordered]


def _markers(wk: cf.Walker) -> list[Event]:
    """Plain markers at their positions; cycle markers as a marker at the
    start and a closing 'name |' marker at the end, unless another marker
    or range starts there (decision 4)."""
    ms = cf.markers(wk)
    starts = {_ticks(m.start) for m in ms}
    out: list[tuple[F, str]] = []
    for m in ms:
        if m.start < 0 or m.length < 0:
            raise ValueError('Invalid marker')
        start = _ticks(m.start)
        out.append((start, m.name))
        if m.is_range and m.length:
            end = _ticks(m.start + m.length)
            if end not in starts:
                out.append((end, f'{m.name} |'))
    out.sort(key=lambda x: x[0])
    return [Event(t, mido.MetaMessage('marker', text=name), i) for i, (t, name) in enumerate(out)]


def import_cubase(path: str | None, name: str, data: bytes = b'', *, byte_size=None):
    """Return the same (Source, tracks) result as the SMF reader."""
    try:
        if not data:
            size = os.path.getsize(path)
            if size > MAX_CPR_BYTES:
                raise ValueError('Project exceeds the 256 MB limit')
            with open(path, 'rb') as fh:
                data = fh.read(MAX_CPR_BYTES + 1)
        if not cf.is_cubase_project(data[:16]):
            raise ValueError('Not a Cubase project file')
        container = cf.read_container(path, data)
        app, version = cf.app_version(container)
        try:
            major = int(version.split('.')[0])
        except ValueError:
            major = None
        if app != 'Cubase' or major not in SUPPORTED_MAJOR:
            raise ValueError(f'{app or "Unknown application"} {version or "(unknown version)"} projects are '
                             f'not supported; supported: Cubase {", ".join(map(str, SUPPORTED_MAJOR))}')
        wk, _ = cf.walk_archive(container, 'Arrangement1', skip=cf.READER_SKIP)
        warnings: list[str] = []

        def warn(text):
            if text not in warnings:
                warnings.append(text)

        tempo_map = _tempo_map(wk, warn)
        sid = new_id()
        counter = [0]
        shared: dict[int, list[Event]] = {}
        track_events = sorted((o for o in wk.objects.values() if o.cls.name in cf.TRACK_EVENTS),
                              key=lambda o: o.tag_at)
        folders = [o for o in wk.objects.values() if o.cls.name == 'MFolderTrack']
        part_events = [o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent']
        tracks: list[Track] = []
        names: list[str] = []
        for index, te in enumerate(track_events):
            name_ = cf.track_name(wk, te)
            names.append(name_)
            if cf.track_time_base_linear(wk, te):
                warn(f'Track "{name_}" uses the linear (seconds) time base; it is not imported yet')
                continue
            flags = cf.track_state_flags(wk, te)
            if flags is None:
                raise ValueError(f'Track "{name_}": mute/solo state not found')
            muted, soloed = bool(flags & cf.TRACK_MUTE), bool(flags & cf.TRACK_SOLO)
            modifiers = cf.track_midi_modifiers(wk, te)
            transpose = sum(m.get('Transpose', 0) for m in modifiers)
            if not -127 <= transpose <= 127:
                raise ValueError(f'Track "{name_}": invalid transpose {transpose}')
            if any(m.get('Velocity Shift') or m.get('Delay') for m in modifiers):
                warn('MIDI Modifiers velocity shift and delay are not applied')
            for f in folders:
                if f.body_at <= te.tag_at < f.end:
                    warn('Folder tracks are flattened; folder mute/solo is applied to their tracks')
                    ff = cf.folder_state_flags(wk, f)
                    muted, soloed = muted or bool(ff & cf.TRACK_MUTE), soloed or bool(ff & cf.TRACK_SOLO)
            clips = []
            for o in sorted((o for o in part_events if te.body_at <= o.tag_at < te.end), key=lambda o: o.tag_at):
                pe = cf.part_event_info(wk, o)
                if pe.part is None:
                    raise ValueError(f'Track "{name_}": part contents not found')
                if pe.length < 0 or pe.start < 0:
                    raise ValueError(f'Track "{name_}": invalid part extent')
                key = (pe.part.tag_at, transpose)
                if key not in shared:
                    part_name = cf._pstring(wk.d, pe.part.body_at)[0]
                    shared[key] = _clip_events(wk, pe.part, f'Part "{part_name}" on "{name_}"', warn, counter, transpose)
                events = shared[key]
                # Clip zero is the content zero, or the visible start when the
                # part was extended before its content (negative offset; GA).
                content_zero, start = _ticks(pe.start - pe.offset), _ticks(pe.start)
                offset = min(content_zero, start)
                if content_zero > offset:
                    shift = content_zero - offset
                    events = [Event(e.time + shift, e.msg, e.seq) for e in events]
                trim_start, trim_end = start - offset, start + _ticks(pe.length) - offset
                length = max(trim_end, max((e.time for e in events), default=F(0)))
                if offset + length > MAX_TIME:
                    raise ValueError('Part time exceeds workspace bounds')
                clips.append(Clip(new_id(), events, length, offset=offset, source_track_index=index,
                                  name=cf._pstring(wk.d, pe.part.body_at)[0], source_id=sid,
                                  trim_start=trim_start, trim_end=trim_end, muted=pe.muted))
            if not clips:
                continue
            tracks.append(Track(new_id(), name_, sid, clips, original_name=name_, muted=muted, soloed=soloed,
                                channels=track_channels([e for c in clips for e in c.events]),
                                source_transpose=transpose))
        marker_events = _markers(wk)
        if marker_events:
            tracks.append(Track(new_id(), 'Markers', sid,
                                [Clip(new_id(), marker_events, max(e.time for e in marker_events), source_id=sid)],
                                auxiliary=True))
        present = {o.cls.name for o in wk.objects.values()}
        if present & {'MAudioTrackEvent', 'MAudioEvent'}:
            warn('Audio tracks and media are not imported')
        if 'MPatternEvent' in present:
            warn('Pattern Editor parts are not imported')
        if 'MChordEvent' in present:
            warn('Chord track events are not imported')
        if any(t.source_transpose for t in tracks):
            warn('Track transpose (MIDI Modifiers) is applied to the notes, as Cubase\'s MIDI export does')
        warn('Instruments, MIDI inserts and other MIDI modifiers are not applied; the stored MIDI is imported')
        if not any(not t.auxiliary for t in tracks) and not marker_events:
            raise ValueError('The project contains no supported MIDI parts or markers')
        source = Source(sid, name, TICKS, 1, datetime.now(), tempo_map=tempo_map, path=path,
                        app=f'Cubase {version}', track_names=tuple(names), warnings=tuple(warnings),
                        byte_size=byte_size if byte_size is not None else len(data),
                        input_format='cubase', format_version=version,
                        display_bar_offset=cf.display_bar_offset(wk))
        return source, tracks
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, struct.error,
            RecursionError, ZeroDivisionError, OverflowError) as exc:
        raise ImportError_(f'Could not read Cubase project: {exc}') from exc
