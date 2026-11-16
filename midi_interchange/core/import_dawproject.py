"""Read the MIDI arrangement of DAWproject 1.0 without extracting media.

Spec: https://github.com/bitwig/dawproject/blob/main/Reference.html
Unsupported musical transformations fail explicitly; non-MIDI content is reported.
"""
from __future__ import annotations

import io
import os
import zipfile
import zlib
import xml.etree.ElementTree as ET
from datetime import datetime
from fractions import Fraction as F

import mido

from .document import Clip, Source, Track, new_id, track_channels
from .events import Event
from .import_smf import ImportError_
from .timing import TempoMap, TempoChange, TimeSigChange

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 1_000_000


def _num(node, key, default='0'):
    value = F(node.get(key, default))
    if abs(value) > 1_000_000:
        raise ValueError(f'{key} is out of bounds')
    return value


def _unit(node, inherited='beats'):
    unit = node.get('timeUnit', inherited)
    if unit not in ('beats', 'seconds'):
        raise ValueError(f'Unsupported time unit: {unit}')
    return unit


def _xml(archive, name):
    info = archive.getinfo(name)
    if info.flag_bits & 1:
        raise ValueError('Encrypted DAWproject XML is not supported')
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f'{name} exceeds the 16 MB XML limit')
    with archive.open(info) as fh:
        data = fh.read(MAX_XML_BYTES + 1)
    text = data.decode('utf-8-sig')
    if len(data) > MAX_XML_BYTES or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError(f'Unsafe or oversized XML: {name}')
    return ET.fromstring(text)


class _Clock:
    """Exact piecewise-constant tempo conversion in both directions."""
    def __init__(self, root, arrangement):
        tempo = root.find('Transport/Tempo')
        bpm = _num(tempo, 'value', '120') if tempo is not None else F(120)
        if not F(60_000_000, 0xffffff) <= bpm <= 1000:
            raise ValueError('Invalid transport tempo')
        self.points = [(F(0), F(0), bpm)]  # beat, second, BPM (unrounded)
        automation = arrangement.find('TempoAutomation')
        if automation is not None:
            unit = automation.get('timeUnit', automation.get('unit', 'beats'))
            if unit not in ('beats', 'seconds'):
                raise ValueError('Unsupported tempo automation unit')
            for point in sorted(automation.findall('RealPoint'), key=lambda p: _num(p, 'time')):
                if point.get('interpolation', 'hold') != 'hold':
                    raise ValueError('Tempo ramps are not supported; use stepped tempo changes')
                pos, bpm = _num(point, 'time'), _num(point, 'value')
                if pos < 0 or bpm <= 0:
                    raise ValueError('Invalid tempo point')
                beat = pos if unit == 'beats' else self.beats(pos)
                second = pos if unit == 'seconds' else self.seconds(pos)
                self.points.append((beat, second, bpm))
        if any(not F(60_000_000, 0xffffff) <= bpm <= 1000 for _, _, bpm in self.points):
            raise ValueError('Tempo is outside the MIDI-supported range')
        self.map = TempoMap([TempoChange(b.limit_denominator(10**9), round(60_000_000 / bpm)) for b, _, bpm in self.points], [])
        sig = root.find('Transport/TimeSignature')
        if sig is not None:
            self.map.timesigs.append(self.signature(sig, F(0)))
        auto = arrangement.find('TimeSignatureAutomation')
        if auto is not None:
            unit = _unit(auto)
            for p in auto.findall('TimeSignaturePoint'):
                self.map.timesigs.append(self.signature(p, self.convert(_num(p, 'time'), unit)))
        self.map.__post_init__()

    @staticmethod
    def signature(node, time):
        n, d = int(node.get('numerator', '4')), int(node.get('denominator', '4'))
        if time < 0 or not 1 <= n <= 255 or d not in (1, 2, 4, 8, 16, 32, 64, 128):
            raise ValueError('Invalid time signature')
        return TimeSigChange(time.limit_denominator(10**9), n, d)

    def beats(self, seconds):
        b, s, bpm = next((p for p in reversed(self.points) if p[1] <= seconds), self.points[0])
        return b + (seconds - s) * bpm / 60

    def seconds(self, beats):
        b, s, bpm = next((p for p in reversed(self.points) if p[0] <= beats), self.points[0])
        return s + (beats - b) * 60 / bpm

    def convert(self, pos, unit):
        return self.beats(pos) if unit == 'seconds' else pos

    def local(self, origin, pos, unit):
        return self.beats(self.seconds(origin) + pos) if unit == 'seconds' else origin + pos


def import_dawproject(path: str | None, name: str, data: bytes = b'', *, byte_size=None):
    """Return the same (Source, tracks) result as the SMF reader."""
    try:
        with zipfile.ZipFile(io.BytesIO(data) if data else path) as archive:
            root = _xml(archive, 'project.xml')
            title = ''
            if 'metadata.xml' in archive.namelist():
                title = _xml(archive, 'metadata.xml').findtext('Title', '')
        if root.tag != 'Project' or root.get('version') != '1.0':
            raise ValueError('Only DAWproject version 1.0 is supported')
        arrangement = root.find('Arrangement')
        if arrangement is None:
            raise ValueError('The project has no arrangement')
        clock = _Clock(root, arrangement)
        ids = {}
        for e in root.iter():
            if e.get('id'):
                if e.get('id') in ids:
                    raise ValueError('Duplicate project ID')
                ids[e.get('id')] = e
        sid = new_id()
        tracks, warnings = [], []
        count = 0

        def warn(text):
            if text not in warnings:
                warnings.append(text)

        def render(node, unit, origin, depth=0):
            """Produce absolute beat events for nested timelines."""
            nonlocal count
            if depth > 32:
                raise ValueError('Timeline nesting exceeds 32 levels')
            unit = _unit(node, unit)
            out = []
            if node.tag in ('Points', 'Audio', 'Video', 'Warps'):
                warn(f'{node.tag} content is not imported')
                return out
            if node.tag == 'Notes':
                for n in node.findall('Note'):
                    pos, duration = _num(n, 'time'), _num(n, 'duration')
                    if duration < 0:
                        raise ValueError('Negative note duration')
                    key, channel = int(n.get('key')), int(n.get('channel', '0'))
                    vel, rel = _num(n, 'vel', '1'), _num(n, 'rel', '0')
                    if not 0 <= vel <= 1 or not 0 <= rel <= 1:
                        raise ValueError('Note velocity out of bounds')
                    if n.get('transpose', '0') != '0' or len(n):
                        warn('Per-note expression is not imported')
                    count += 2
                    if count > MAX_EVENTS:
                        raise ValueError('Project exceeds the MIDI event limit')
                    a, b = clock.local(origin, pos, unit), clock.local(origin, pos + duration, unit)
                    out.extend([(a, mido.Message('note_on', note=key, channel=channel, velocity=max(1, round(vel*127)))),
                                (b, mido.Message('note_off', note=key, channel=channel, velocity=round(rel*127)))])
                return out
            for child in node:
                if child.tag in ('Notes', 'Lanes', 'Clips'):
                    out.extend(render(child, unit, origin, depth+1))
                elif child.tag == 'Clip':
                    c, _ = read_clip(child, unit, origin, depth+1)
                    if c is not None and c.muted:
                        raise ValueError('Nested disabled MIDI clips are not supported')
                    if c is not None:
                        from .export_smf import audible_events
                        for item in audible_events(c):
                            out.append((item.time, item.msg))
                elif child.tag in ('Points', 'Audio', 'Video', 'Warps'):
                    warn(f'{child.tag} content is not imported')
            return out

        def read_clip(node, unit, origin, depth=0):
            if depth > 32:
                raise ValueError('Timeline nesting exceeds 32 levels')
            if not any(e.get('reference') for e in node.iter('Clip')) and node.find('.//Note') is None:
                if node.find('.//Audio') is not None:
                    warn('Audio, media and plug-in states are not imported')
                if node.find('.//Points') is not None:
                    warn('Automation is not imported (including MIDI CCs and expression)')
                return None, []
            start = clock.local(origin, _num(node, 'time'), unit)
            content_unit = node.get('contentTimeUnit', unit)
            if content_unit not in ('beats', 'seconds'):
                raise ValueError('Unsupported clip content time unit')
            play_start = _num(node, 'playStart')
            base = clock.local(start, -play_start, content_unit)
            if node.get('reference'):
                content = ids.get(node.get('reference'))
                if content is None:
                    raise ValueError('Missing clip reference')
                if content.tag not in ('Notes', 'Clips', 'Lanes'):
                    raise ValueError('Unsupported clip reference target')
                children = [content]
            else:
                children = [c for c in node if c.tag in ('Notes', 'Clips', 'Lanes', 'Audio', 'Warps', 'Points')]
            if node.get('duration') is not None:
                end = clock.local(origin, _num(node, 'time') + _num(node, 'duration'), unit)
            elif node.get('playStop') is not None:
                end = clock.local(base, _num(node, 'playStop'), content_unit)
            else:
                raise ValueError('Clip needs duration or playStop')
            if start < 0 or end < start:
                raise ValueError('Invalid clip extent')
            loop_end = _num(node, 'loopEnd')
            loop_start = _num(node, 'loopStart')
            events = []
            if loop_end:
                if loop_end <= loop_start or loop_start < 0 or play_start >= loop_end:
                    raise ValueError('Invalid clip loop')
                cursor, left = start, play_start
                iterations = 0
                while cursor < end:
                    iterations += 1
                    if iterations > 100_000:
                        raise ValueError('Clip exceeds the loop repetition limit')
                    stop = min(end, clock.local(cursor, loop_end-left, content_unit))
                    cycle_base = clock.local(cursor, -left, content_unit)
                    raw = [e for child in children for e in render(child, content_unit, cycle_base, depth+1)]
                    # Reuse the exporter's note pairing/cutting rules for loop edges.
                    temp = make_clip(raw, cycle_base, cursor, stop, node)
                    temp.muted = False  # render stored loop content even if its outer clip is disabled
                    from .export_smf import audible_events
                    events.extend((i.time, i.msg) for i in audible_events(temp))
                    cursor, left = stop, loop_start
                base = start
            else:
                events = [e for child in children for e in render(child, content_unit, base, depth+1)]
            if not events:
                return None, []
            return make_clip(events, base, start, end, node), events

        def make_clip(events, base, start, end, node):
            base = min(base, start, min((t for t, _ in events), default=start)).limit_denominator(10**9)
            start, end = start.limit_denominator(10**9), end.limit_denominator(10**9)
            ordered = sorted(enumerate(events), key=lambda e: (e[1][0], e[0]))
            if max(abs(base), abs(start), abs(end)) > 1_000_000:
                raise ValueError('Clip time exceeds workspace bounds')
            evs = [Event((t-base).limit_denominator(10**9), m, i) for i, (t, m) in ordered]
            length = max((end-base).limit_denominator(10**9), max((e.time for e in evs), default=F(0)))
            return Clip(new_id(), evs, length, offset=base, source_id=sid,
                        name=node.get('name', ''), trim_start=(start-base).limit_denominator(10**9), trim_end=(end-base).limit_denominator(10**9),
                        muted=node.get('enable', 'true') in ('false', '0'))

        definitions = list(root.findall('.//Structure//Track'))
        parents = {child: parent for parent in root.iter() for child in parent}
        track_ids = {t.get('id'): (i, t) for i, t in enumerate(definitions)}
        by_track = {}

        def lanes(node, unit='beats', track_id=None, depth=0):
            if depth > 32:
                raise ValueError('Lane nesting exceeds 32 levels')
            unit = _unit(node, unit)
            track_id = node.get('track', track_id)
            for child in node:
                if child.tag == 'Lanes':
                    lanes(child, unit, track_id, depth+1)
                elif child.tag == 'Clips':
                    if track_id not in track_ids:
                        if child.find('.//Note') is not None or any(e.get('reference') for e in child.iter('Clip')):
                            raise ValueError('Arrangement lane references a missing track')
                        continue
                    index, _ = track_ids[track_id]
                    clips = by_track.setdefault(track_id, [])
                    for clip in child.findall('Clip'):
                        c, _ = read_clip(clip, _unit(child, unit), F(0))
                        if c is not None:
                            c.source_track_index = index
                            clips.append(c)
                elif child.tag == 'Points':
                    warn('Automation is not imported (including MIDI CCs and expression)')
        for lane in arrangement.findall('Lanes'):
            lanes(lane)
        for i, definition in enumerate(definitions):
            clips = by_track.get(definition.get('id'), [])
            if not clips:
                continue
            def state(track):
                ch = track.find('Channel')
                mute = ch.find('Mute') if ch is not None else None
                return (mute is not None and mute.get('value') in ('true', '1'),
                        ch is not None and ch.get('solo') in ('true', '1'))
            muted, soloed = state(definition)
            ancestor = parents.get(definition)
            while ancestor is not None:
                if ancestor.tag == 'Track':
                    a_mute, a_solo = state(ancestor)
                    muted, soloed = muted or a_mute, soloed or a_solo
                    warn('Track groups are flattened; inherited mute/solo is applied to their tracks')
                ancestor = parents.get(ancestor)
            name_ = definition.get('name', f'Track {i+1}')
            tracks.append(Track(new_id(), name_, sid, clips, original_name=name_, muted=muted,
                                soloed=soloed, channels=track_channels([e for c in clips for e in c.events])))
        markers = []
        for group in arrangement.findall('Markers'):
            for marker in group.findall('Marker'):
                markers.append(Event(clock.convert(_num(marker, 'time'), _unit(group)).limit_denominator(10**9),
                                     mido.MetaMessage('marker', text=marker.get('name', '')), len(markers)))
        if markers:
            markers.sort(key=lambda e: (e.time, e.seq))
            if markers[0].time < 0 or markers[-1].time > 1_000_000:
                raise ValueError('Marker time exceeds workspace bounds')
            tracks.append(Track(new_id(), 'Markers', sid,
                                [Clip(new_id(), markers, max(e.time for e in markers), source_id=sid)], auxiliary=True))
        if list(root.iter('Audio')):
            warn('Audio, media and plug-in states are not imported')
        if list(root.iter('Devices')):
            warn('Instruments, effects and plug-in states are not imported')
        if list(root.iter('Scenes')):
            warn('Clip-launcher scenes are not imported; only the arrangement is used')
        if not tracks:
            raise ValueError('The arrangement contains no supported MIDI notes or markers')
        app = root.find('Application')
        application = ' '.join(filter(None, (app.get('name'), app.get('version')))) if app is not None else None
        return Source(sid, name, 960, 1, datetime.now(), tempo_map=clock.map,
                      path=path, app=application, track_names=tuple(t.get('name', '') for t in definitions),
                      warnings=tuple(warnings), song=title,
                      byte_size=byte_size if byte_size is not None else (len(data) if data else os.path.getsize(path)),
                      input_format='dawproject', format_version=root.get('version')), tracks
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, zipfile.BadZipFile, ET.ParseError, RecursionError, ZeroDivisionError,
            RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ImportError_(f'Could not read DAWproject: {exc}') from exc
