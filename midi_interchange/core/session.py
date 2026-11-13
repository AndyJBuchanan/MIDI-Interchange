"""Versioned, self-contained workspace storage. No Qt or executable serialization.

Snapshots share immutable event lists/source records with the model. Encoding and
atomic writing belong on a worker, never in an edit notification handler.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import mido

from .. import __version__
from .document import Clip, Source, Track, Workspace
from .events import Event
from .ranges import Range
from .timing import TempoChange, TempoMap, TimeSigChange

# BUMP for incompatible model/field-meaning/invariant changes, not every release.
# Update the explicit records, validators and round-trip tests together. See
# docs/DEVELOPMENT.md. Unsupported versions are preserved, never migrated implicitly.
SCHEMA_VERSION = 1

# Explicit persisted fields: adding a model field requires a compatibility review.
RECORDS = {
    Source: 'id name ppq smf_format imported_at raw tempo_map path app track_names warnings song',
    Track: 'id name source_id clips original_name muted soloed color auxiliary channels auto_trim export_channel',
    Clip: 'id events length offset source_track_index name source_id trim_start trim_end',
    Range: 'start end name id excluded track_locked',
    TempoMap: 'tempos timesigs',
    TempoChange: 'time us_per_beat',
    TimeSigChange: 'time numerator denominator clocks_per_click notated_32nd',
    Event: 'time msg seq',
}


class SessionError(ValueError):
    pass


@dataclass
class Session:
    workspace: dict
    settings: dict


def require(condition, message='Invalid session data'):
    if not condition:
        raise SessionError(message)


def integer(value, low=0, high=None):
    require(type(value) is int and value >= low and (high is None or value <= high), 'Invalid integer')
    return value


def number(value, low, high):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, 'Invalid number')
    return value


def string(value, nonempty=False):
    require(type(value) is str and (not nonempty or bool(value)), 'Invalid text')
    return value


def boolean(value):
    require(type(value) is bool, 'Invalid boolean')
    return value


def sequence(value):
    require(type(value) is list, 'Invalid list')
    return value


def fraction(value, *, nonnegative=True):
    require(type(value) is Fraction, 'Invalid musical time')
    # Bound conversion to floats/Qt scrollbar coordinates; reject absurd corrupt data.
    require(abs(value) <= 1_000_000 and (not nonnegative or value >= 0), 'Musical time out of bounds')
    return value


def _record(obj):
    return {name: getattr(obj, name) for name in RECORDS[type(obj)].split()}


def encode(session: Session) -> dict:
    """Encode each shared event list once, including copied clips."""
    event_lists, indices = [], {}

    def pack(obj):
        if type(obj) in RECORDS:
            data = _record(obj)
            if isinstance(obj, Clip):
                key = id(obj.events)
                if key not in indices:
                    indices[key] = len(event_lists)
                    event_lists.append(pack(obj.events))
                data['events'] = indices[key]
            return {'kind': type(obj).__name__, 'data': pack(data)}
        if isinstance(obj, Fraction):
            return {'kind': 'fraction', 'data': [obj.numerator, obj.denominator]}
        if isinstance(obj, bytes):
            return {'kind': 'bytes', 'data': base64.b64encode(obj).decode('ascii')}
        if isinstance(obj, datetime):
            return {'kind': 'datetime', 'data': obj.isoformat()}
        if isinstance(obj, (mido.Message, mido.MetaMessage)):
            # Preserve unknown meta messages and latin-1 text byte-for-byte as well.
            return {'kind': 'midi', 'data': [obj.is_meta, obj.bytes(), obj.time]}
        if isinstance(obj, (list, tuple, set)):
            return [pack(v) for v in (sorted(obj) if isinstance(obj, set) else obj)]
        if isinstance(obj, dict):
            return {k: pack(v) for k, v in obj.items()}
        require(obj is None or type(obj) in (str, int, float, bool), 'Unsupported session value')
        return obj

    workspace = pack(session.workspace)
    return {'schema_version': SCHEMA_VERSION, 'app_version': __version__,
            'events': event_lists, 'workspace': workspace, 'settings': pack(session.settings)}


def decode(data: dict) -> Session:
    require(type(data) is dict, 'Invalid session document')
    require(type(data.get('schema_version')) is int and data['schema_version'] == SCHEMA_VERSION,
            'This session uses an unsupported schema version')
    string(data['app_version'], True)  # provenance only; schema decides compatibility
    classes = {cls.__name__: cls for cls in RECORDS}
    event_lists = []

    def unpack(obj):
        if type(obj) is list:
            return [unpack(v) for v in obj]
        if type(obj) is not dict:
            require(obj is None or type(obj) in (str, int, float, bool))
            return obj
        if 'kind' not in obj:
            return {k: unpack(v) for k, v in obj.items()}
        require(set(obj) == {'kind', 'data'})
        kind, value = obj['kind'], obj['data']
        string(kind)
        if kind == 'fraction':
            require(type(value) is list and len(value) == 2)
            integer(value[0], -10**18, 10**18)
            integer(value[1], 1, 10**18)
            return Fraction(*value)
        if kind == 'bytes':
            return base64.b64decode(string(value), validate=True)
        if kind == 'datetime':
            return datetime.fromisoformat(string(value))
        if kind == 'midi':
            require(type(value) is list and len(value) == 3)
            meta, raw, delta = value
            boolean(meta)
            sequence(raw)
            require(bool(raw))
            for b in raw:
                integer(b, 0, 255)
            integer(delta)
            msg = (mido.MetaMessage if meta else mido.Message).from_bytes(raw)
            require(msg.bytes() == raw, 'Invalid MIDI payload')
            msg.time = delta
            return msg
        require(kind in classes, 'Unknown session record')
        cls = classes[kind]
        require(type(value) is dict and set(value) == set(RECORDS[cls].split()), 'Invalid record fields')
        args = {k: unpack(v) for k, v in value.items()}
        if 'id' in args:
            string(args['id'], True)  # reject before Range can generate a replacement ID
        if cls is Clip:
            idx = integer(args['events'], 0, len(event_lists) - 1)
            args['events'] = event_lists[idx]
            require(args['trim_end'] is not None)
        if cls is Range:
            args['excluded'] = set(sequence(args['excluded']))
            require(fraction(args['end']) >= fraction(args['start']), 'Reversed range')
        if cls is Source:
            for key in ('track_names', 'warnings'):
                args[key] = tuple(sequence(args[key]))
        if cls is Track:
            args['channels'] = tuple(sequence(args['channels']))
        if cls is TempoMap:
            # Validate before __post_init__ sorts/deduplicates the lists.
            _validate_map(args['tempos'], args['timesigs'])
        return cls(**args)

    for raw in sequence(data['events']):
        events = unpack(raw)
        sequence(events)
        previous = None
        for e in events:
            require(type(e) is Event)
            fraction(e.time)
            integer(e.seq)
            require(isinstance(e.msg, (mido.Message, mido.MetaMessage)))
            order = e.time, e.seq
            require(previous is None or order >= previous, 'Unsorted MIDI events')
            previous = order
        event_lists.append(events)
    session = Session(unpack(data['workspace']), unpack(data['settings']))
    validate_workspace(session.workspace)
    require(type(session.settings) is dict, 'Invalid session settings')
    return session


def _validate_map(tempos, sigs):
    for changes, cls in ((tempos, TempoChange), (sigs, TimeSigChange)):
        sequence(changes)
        previous = None
        for c in changes:
            require(type(c) is cls)
            fraction(c.time)
            require(previous is None or c.time > previous, 'Unsorted tempo map')
            previous = c.time
            if cls is TempoChange:
                integer(c.us_per_beat, 1, 0xffffff)
            else:
                integer(c.numerator, 1, 255)
                integer(c.denominator, 1, 128)
                require(c.denominator & (c.denominator - 1) == 0)
                integer(c.clocks_per_click, 0, 255)
                integer(c.notated_32nd, 0, 255)


def validate_workspace(ws):
    require(type(ws) is dict and set(ws) == {'sources', 'tracks', 'ranges', 'tempo_map', 'tempo_source_id'})
    ids = set()

    def identify(obj, cls):
        require(type(obj) is cls)
        string(obj.id, True)
        require(obj.id not in ids, 'Duplicate session ID')
        ids.add(obj.id)

    def tempo(tm):
        require(type(tm) is TempoMap)
        _validate_map(tm.tempos, tm.timesigs)

    source_ids = set()
    for src in sequence(ws['sources']):
        identify(src, Source)
        source_ids.add(src.id)
        for key in ('name', 'song'):
            string(getattr(src, key))
        for key in ('path', 'app'):
            require(getattr(src, key) is None or type(getattr(src, key)) is str)
        for value in (*src.track_names, *src.warnings):
            string(value)
        integer(src.ppq, 1, 32767)
        integer(src.smf_format, 0, 2)
        require(type(src.raw) is bytes and type(src.imported_at) is datetime)
        tempo(src.tempo_map)
    tempo(ws['tempo_map'])
    require(ws['tempo_source_id'] is None or ws['tempo_source_id'] in source_ids, 'Missing tempo source')
    track_ids = set()
    for track in sequence(ws['tracks']):
        identify(track, Track)
        track_ids.add(track.id)
        for key in ('name', 'original_name', 'source_id', 'color'):
            string(getattr(track, key))
        # A track's original source can have been pruned after clips move; each
        # clip's effective source below is authoritative, as in Track.source_ids.
        require(re.fullmatch(r'#[0-9a-fA-F]{6}', track.color) is not None, 'Invalid track colour')
        for key in ('muted', 'soloed', 'auxiliary', 'auto_trim'):
            boolean(getattr(track, key))
        for ch in track.channels:
            integer(ch, 0, 15)
        if track.export_channel is not None:
            integer(track.export_channel, 1, 16)
        for clip in sequence(track.clips):
            identify(clip, Clip)
            string(clip.name)
            string(clip.source_id)
            require((clip.source_id or track.source_id) in source_ids, 'Missing clip source')
            integer(clip.source_track_index)
            fraction(clip.offset, nonnegative=False)
            fraction(clip.length)
            fraction(clip.trim_start)
            fraction(clip.trim_end)
            fraction(clip.end, nonnegative=False)
            require(clip.trim_start <= clip.trim_end <= clip.length, 'Invalid clip trims')
            # Restoring full extent after moving a trimmed clip can expose negative
            # workspace time. Preserve it: the current model permits this.
            require(not clip.events or clip.events[-1].time <= clip.length, 'Events beyond clip extent')
    for r in sequence(ws['ranges']):
        identify(r, Range)
        string(r.name)
        boolean(r.track_locked)
        fraction(r.start)
        fraction(r.end)
        # Existing locked ranges can retain IDs of removed tracks; these are inert.
        for tid in r.excluded:
            string(tid, True)
    # Use the model's own inclusion rule to validate live range selections.
    model = Workspace()
    model.restore(ws)
    included = {t.id for t in model.global_tracks()}
    for r in model.ranges:
        if not r.track_locked:
            require(r.excluded & track_ids == track_ids - included, 'Inconsistent unlocked range')


class SessionStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / 'session.json'
        self.marker = self.directory / 'session.running'
        self.rejected = False

    def load(self) -> Session | None:
        try:
            with self.path.open('r', encoding='utf-8') as f:
                return decode(json.load(f))
        except FileNotFoundError:
            return None

    def save(self, session: Session) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.rejected:
            self.preserve_rejected()
            self.rejected = False
        fd, name = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(encode(session), f, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def preserve_rejected(self) -> Path | None:
        if not self.path.exists():
            return None
        destination = self.directory / f'session-rejected-{uuid.uuid4().hex}.json'
        self.path.rename(destination)
        return destination

    def begin_run(self) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        unclean = self.marker.exists()
        self.marker.write_text('A clean shutdown removes this file.\n', encoding='utf-8')
        return unclean

    def end_run(self) -> None:
        self.marker.unlink(missing_ok=True)
