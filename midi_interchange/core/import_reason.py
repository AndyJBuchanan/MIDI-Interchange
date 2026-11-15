"""Read the MIDI arrangement of a Reason song (.reason saved by Reason 13 or
later), read-only.

Decoding and playback rules: reason_format. Format findings, evidence and
decisions: docs/plans/reason-import.md. Returns the same (Source, tracks)
result as the other readers.

Each note clip becomes one workspace clip per visible stretch (a clip
partly covered by a later one on its lane gives two), holding the notes and
controller values Reason's own MIDI export plays there: loops written out,
hidden and covered notes left out, Block content rendered at each placement.
Muted clips, muted lanes and muted Block placements are kept as muted clips.
Lanes are merged into their track. Material the reader cannot represent is
reported in the source warnings; unreadable or encrypted songs fail before
the workspace changes.
"""
from __future__ import annotations

import mmap
import os
import struct
from datetime import datetime
from fractions import Fraction as F

import mido

from . import reason_format as rf
from .document import Clip, Source, Track, new_id, track_channels
from .events import Event
from .import_smf import ImportError_
from .timing import TempoChange, TempoMap, TimeSigChange

PPQ = rf.PPQ
MAX_EVENTS = 1_000_000
MAX_TIME = 1_000_000 * PPQ          # ticks; session/workspace bound
CONTROLLERS = {0x01: 1, 0x0B: 11, 0x40: 64}     # controller lane id -> CC number
PITCH_BEND, AFTERTOUCH = 0xFF, 0xFD


def _q(ticks: int) -> F:
    if abs(ticks) > MAX_TIME:
        raise ValueError('Position out of bounds')
    return F(ticks, PPQ)


def _tempo_map(song: rf.Song, warn) -> TempoMap:
    """Tempo and signature as Reason's export writes them: clip ramps as
    1/32-beat steps, tempo truncated to whole microseconds per beat."""
    tempos, sigs, problems = rf.tempo_and_signatures(song)
    for p in problems:
        warn(p)
    out_t = []
    for tick, milli in tempos:
        if not 1000 <= milli <= 999999 or tick < 0:
            raise ValueError('Invalid tempo')
        out_t.append(TempoChange(_q(tick), 60_000_000_000 // milli))
    out_s = []
    for tick, num, den in sigs:
        if not 1 <= num <= 255 or den not in (1, 2, 4, 8, 16, 32, 64, 128) or tick < 0:
            raise ValueError('Invalid time signature')
        out_s.append(TimeSigChange(_q(tick), num, den))
    return TempoMap(out_t, out_s)


def _control_msg(lane_id: int, value: int, warn):
    if lane_id in CONTROLLERS:
        return mido.Message('control_change', control=CONTROLLERS[lane_id], value=max(0, min(127, value)))
    if lane_id == PITCH_BEND:
        return mido.Message('pitchwheel', pitch=max(-8192, min(8191, value)))
    if lane_id == AFTERTOUCH:
        return mido.Message('aftertouch', value=max(0, min(127, value)))
    warn(f'Controller lanes of type 0x{lane_id:02X} are not imported')
    return None


def _clip(piece: rf.Piece, index: int, sid: str, warn, counter) -> Clip:
    u = piece.start
    out: list[tuple[int, mido.Message]] = []
    for at, pitch, vel, length in piece.notes:
        if not 0 <= pitch <= 127 or length < 0:
            raise ValueError('Invalid note')
        out.append((at - u, mido.Message('note_on', note=pitch, velocity=max(1, min(127, vel)))))
        out.append((at - u + length, mido.Message('note_off', note=pitch, velocity=0)))
    for at, lane_id, value in piece.controls:
        msg = _control_msg(lane_id, value, warn)
        if msg is not None:
            out.append((at - u, msg))
    counter[0] += len(out)
    if counter[0] > MAX_EVENTS:
        raise ValueError('Song exceeds the MIDI event limit')
    ordered = sorted(enumerate(out), key=lambda x: (x[1][0], x[0]))
    events = [Event(_q(t), m, i) for i, (t, m) in ordered]
    length = max([piece.end - u] + [t for t, _ in out])
    c = piece.clip
    name = c.info.name or (f'Block {c.block}' if piece.placement is not None else '')
    return Clip(new_id(), events, _q(length), offset=_q(u), source_track_index=index, name=name,
                source_id=sid, muted=piece.muted)


def _report(song: rf.Song, ts: list[rf.Track], all_pieces, warn) -> None:
    kinds = {(c.kind, bool(c.block)) for t in ts for ln in t.lanes for c in ln.clips}
    if ('pattern', False) in kinds or ('pattern', True) in kinds:
        warn('Pattern clips are not imported (their notes are in the pattern device); '
             'convert them to notes in Reason to import them')
    if ('audio', False) in kinds or ('audio', True) in kinds:
        warn('Audio clips are not imported')
    if any(c.kind == 'automation' for t in ts[1:] for ln in t.lanes for c in ln.clips):
        warn('Device parameter automation is not imported')
    if any(c.kind == 'notes' and c.block for t in ts for ln in t.lanes for c in ln.clips):
        if rf.blocks_enabled(song):
            warn('Blocks are written out as clips at each placement on the Blocks track')
        else:
            warn('Blocks are switched off in this song; Block content is not imported')
    clips = [p.clip for _, ps in all_pieces for p in ps]
    if any(c.info.loop for c in clips):
        warn('Looping clips are imported with their loops written out')
    if any(pt.rest != bytes(10) for c in clips for cl in c.controllers if cl.lane_id in rf.RAMPED
           for pt in cl.points):
        warn('Controller curves are imported as straight lines')
    if any(t.folder for t in ts):
        warn('Track folders are flattened')
    warn('Instruments, Player devices and track parameters are not applied; the stored notes are imported')


def import_reason(path: str | None, name: str, data: bytes = b'', *, byte_size=None):
    """Return the same (Source, tracks) result as the SMF reader."""
    fh = mm = None
    try:
        if not data:
            fh = open(path, 'rb')
            if os.fstat(fh.fileno()).st_size == 0:
                raise ValueError('The file is empty')
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)    # self-contained songs can be large
            data = mm
        if data[:8] != rf.MAGIC:
            raise ValueError('Not a Reason song file')
        try:
            song, _notes = rf.open_song(data)
        except rf.ReasonFormatError:
            song = rf.unverified_song(data)
            if song is None or song.generation == rf.PLAIN_GENERATION.decode():
                raise
        version = song.metadata.get('PROGRAMVERSION', '')
        if song.generation != rf.PLAIN_GENERATION.decode():
            saved = version or rf.generation_version(song.generation)
            raise ValueError(f'This song was saved by Reason {saved}, which encrypts its song files. '
                             'Open it in Reason 13 or later and save it again to import it.')
        warnings: list[str] = []

        def warn(text):
            if text not in warnings:
                warnings.append(text)

        tempo_map = _tempo_map(song, warn)
        sid = new_id()
        counter = [0]
        all_pieces = rf.pieces(song)
        ts = [t for t, _ in all_pieces]
        names = tuple(t.name for t in ts)
        tracks: list[Track] = []
        for t, ps in all_pieces:
            if not ps:
                continue
            for p in ps:
                if p.start < 0 or p.end > MAX_TIME:
                    raise ValueError(f'Track "{t.name}": clip out of bounds')
            clips = [_clip(p, t.index, sid, warn, counter) for p in ps]
            tname = t.name or f'Track {t.index}'
            tracks.append(Track(new_id(), tname, sid, clips, original_name=tname, muted=t.info.muted,
                                channels=track_channels([e for c in clips for e in c.events])))
        _report(song, ts, all_pieces, warn)
        if not tracks:
            raise ValueError('The song contains no note clips')
        source = Source(sid, name, PPQ, 1, datetime.now(), tempo_map=tempo_map, path=path,
                        app=f'Reason {version}' if version else 'Reason', track_names=names,
                        warnings=tuple(warnings), byte_size=byte_size if byte_size is not None else len(data),
                        input_format='reason', format_version=version or None)
        return source, tracks
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, struct.error,
            RecursionError, ZeroDivisionError, OverflowError) as exc:
        raise ImportError_(f'Could not read Reason song: {exc}') from exc
    finally:
        if mm is not None:
            mm.close()
        if fh is not None:
            fh.close()
