"""End-to-end comparison evidence for the supplied Cubase Ditty exports."""
import io
import math
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from midi_interchange.core.document import Workspace
from midi_interchange.core.events import Event, pair_notes
from midi_interchange.core.export_smf import build_exports
from midi_interchange.interchange.readers import payload_from_path, read_payload
from scripts.compare_project_exports import compare, match_notes, midi_tracks

SETS = Path(__file__).resolve().parents[1] / 'samples/project-sets'
DITTY = SETS / 'Ditty-04-Macbook.dawproject'


def test_ditty_export_matches_independent_xml_note_events():
    """No importer timing, note pairing or export-cutting helper in the oracle.

    This fixture has flat note clips, seconds throughout, constant 80 BPM,
    no track mute/solo and no playStart/loops. Independent per-note clipping
    proves our actual output follows those XML notes; it does not claim that
    Cubase's separate MIDI export represents the same performed material.
    """
    result = read_payload(payload_from_path(str(DITTY)))
    ws = Workspace()
    ws.add_import(result.source, result.tracks, preserve_track_state=result.preserve_track_state)
    buffer = io.BytesIO()
    build_exports(ws)[0].midi.save(file=buffer)
    buffer.seek(0)
    exported = mido.MidiFile(file=buffer)
    with zipfile.ZipFile(DITTY) as archive:
        root = ET.fromstring(archive.read('project.xml'))
    assert root.find('Transport/Tempo').get('value') == '80'
    assert root.find('Arrangement/Lanes').get('timeUnit') == 'seconds'
    definitions = {t.get('id'): t for t in root.findall('.//Structure//Track')}
    expected = {}
    for lane in root.findall('.//Arrangement//Lanes'):
        definition = definitions.get(lane.get('track'))
        if definition is None:
            continue
        channel = definition.find('Channel')
        if channel is not None:
            assert channel.get('solo', 'false') == 'false'
            assert channel.find('Mute').get('value') == 'false'
        events = expected.setdefault(definition.get('name'), Counter())
        for clip in lane.findall('./Clips/Clip'):
            if clip.get('enable') == 'false':
                continue
            assert 'playStart' not in clip.attrib and 'loopEnd' not in clip.attrib
            start = F(clip.get('time')) * F(4, 3)
            end = start + F(clip.get('duration')) * F(4, 3)
            for note in clip.findall('./Notes/Note'):
                on = start + F(note.get('time')) * F(4, 3)
                off = on + F(note.get('duration')) * F(4, 3)
                if on >= end or off <= start:
                    continue
                for kind, time, velocity in (
                    ('note_on', max(on, start), round(F(note.get('vel')) * 127)),
                    ('note_off', min(off, end), round(F(note.get('rel')) * 127)),
                ):
                    tick = math.floor(time * exported.ticks_per_beat + F(1, 2))
                    events[tick, kind, int(note.get('key')), velocity, int(note.get('channel'))] += 1
    total = 0
    for track in exported.tracks:
        events = Counter()
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type in ('note_on', 'note_off'):
                events[tick, msg.type, msg.note, msg.velocity, msg.channel] += 1
        assert events == expected.pop(track.name, Counter()), track.name
        total += sum(events.values())
    assert total == 1292
    assert not any(expected.values())


def test_ditty_serialized_midi_comparison_classifies_differences():
    report = compare(DITTY, DITTY.with_suffix('.mid'))
    assert report['app_ppq'] == 960 and report['cubase_ppq'] == 480
    assert report['app_timing'] == report['cubase_timing']
    tracks = {row['track']: row for row in report['tracks']}
    assert sum(t['app_notes'] for t in tracks.values()) == 646
    assert sum(t['cubase_notes'] for t in tracks.values()) == 647
    assert tracks['Epic Choir']['notes']['exact'] == 36
    assert tracks['Soft Nylon Gtr']['app_notes'] == 18
    assert tracks['Soft Nylon Gtr']['cubase_notes'] == 27
    assert tracks['Soft Nylon Gtr']['notes']['app_only'] == 18
    assert tracks['Soft Steel Gtr']['notes']['changed_duration'] == 10
    assert tracks['Soft Steel Gtr']['notes']['app_only'] == 7
    assert tracks['Groove Agent SE 01']['notes']['app_only'] == 6
    for name in ('Epic Choir', 'Epic Brass and Woods', 'Rare Flutes (D)', 'Soft Steel Gtr 2'):
        diff = tracks[name]['notes']
        assert diff['exact'] + diff['within_one_tick'] == tracks[name]['cubase_notes']
    assert sum(sum(t['cubase_events']['controllers'].values()) for t in tracks.values()) == 1224
    assert sum(t['cubase_events']['pitch_bends'] for t in tracks.values()) == 207
    assert all(not t['app_events']['controllers'] and t['app_events']['pitch_bends'] == 0 for t in tracks.values())
    assert all(t['app_events']['unreleased_notes'] == t['app_events']['orphan_releases'] == 0 for t in tracks.values())


def test_comparison_keeps_half_ticks_and_normalizes_zero_velocity_note_off():
    midi = mido.MidiFile(ticks_per_beat=960)
    midi.tracks.append(mido.MidiTrack([
        mido.Message('note_on', note=60, velocity=80, time=1),
        mido.Message('note_on', note=60, velocity=0, time=959),
    ]))
    notes = midi_tracks(midi)[0]['notes']
    expected, _ = pair_notes([Event(F(0), mido.Message('note_on', note=60, velocity=80), 0),
                              Event(F(1), mido.Message('note_off', note=60, velocity=64), 1)], F(1))
    diff = match_notes(notes, expected, 480)
    assert diff['exact'] == 0 and diff['within_one_tick'] == 1
    assert diff['changed_duration'] == diff['app_only'] == diff['cubase_only'] == 0


def test_indy_reference_window_explains_offset_but_not_missing_drums():
    path = SETS / 'indy-001x.dawproject'
    report = compare(path, path.with_suffix('.mid'), window=(F(3), F(196)))
    assert report['source_window_beats'] == [3, 196]
    rows = {t['track']: t for t in report['tracks']}
    for name, count in [('Bass Sequence', 390), ('Industrial Stab', 225), ('Secondary Motif', 24)]:
        assert rows[name]['app_notes'] == rows[name]['cubase_notes'] == rows[name]['notes']['exact'] == count
    assert rows['Texture Bed']['notes']['exact'] == 22
    assert rows['Texture Bed']['notes']['changed_duration'] == 2
    assert [(t['track'], t['notes']) for t in report['unmatched_cubase_tracks']] == [('Drum Core', 596), ('Drum Core =', 48)]
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('project.xml'))
    for name in ('Drum Core', 'Drum Core ='):
        track = next(t for t in root.findall('.//Structure//Track') if t.get('name') == name)
        lane = root.find('.//Arrangement//Lanes[@track="' + track.get('id') + '"]')
        assert lane is not None and len(lane) == 0  # no saved drum notes to read


def test_ga_reference_window_and_prologue_pitch_difference():
    from dataclasses import replace
    path = SETS / 'GA & Padshop 2-(alt instr 2)-01.dawproject'
    reference = Path(str(path) + '.midi')
    report = compare(path, reference, window=(F(0), F(192)))
    assert report['app_timing'] == report['cubase_timing']
    rows = {t['track']: t for t in report['tracks']}
    assert rows['hbar Sample Pack 1 Kit']['app_notes'] == 1854
    assert rows['hbar Sample Pack 1 Kit']['notes']['exact'] == 1008
    assert rows['hbar Sample Pack 1 Kit']['notes']['app_only'] == 846
    assert rows['Piano Chords']['notes']['exact'] == 194
    assert rows['Piano Chords (D)']['notes']['exact'] == 265
    assert rows['HALion Sonic SE 01']['notes']['exact'] + rows['HALion Sonic SE 01']['notes']['within_one_tick'] == 80
    assert rows['Retrologue 01']['notes']['exact'] == 14
    assert not report['unmatched_cubase_tracks']
    # Diagnose the exact pitch difference without changing production imports.
    result = read_payload(payload_from_path(str(path)))
    ws = Workspace()
    ws.add_import(result.source, result.tracks, preserve_track_state=True)
    output = midi_tracks(build_exports(ws)[0].midi)
    actual = next(t for t in output if t['name'] == 'Prologue 01')['notes']
    expected = next(t for t in midi_tracks(mido.MidiFile(reference)) if t['name'] == 'Prologue 01')['notes']
    shifted = [replace(n, pitch=n.pitch+24) for n in actual]
    diff = match_notes(shifted, expected, 480)
    assert diff['exact'] + diff['within_one_tick'] == 20


@pytest.mark.parametrize('stem,event_count', [('indy-001x', 1606), ('GA & Padshop 2-(alt instr 2)-01', 12616)])
def test_other_projects_match_independent_seconds_xml_events(stem, event_count):
    """Raw XML oracle for flat seconds clips, including trims and tempo changes.

    Deliberately does not call the importer clock, note pairing or export cutting.
    Checks fidelity to input under our clip-window policy, separately from the
    paired Cubase MIDI ground-truth comparisons above.
    """
    path = SETS / (stem + '.dawproject')
    result = read_payload(payload_from_path(str(path)))
    ws = Workspace()
    ws.add_import(result.source, result.tracks, preserve_track_state=True)
    buffer = io.BytesIO()
    build_exports(ws)[0].midi.save(file=buffer)
    buffer.seek(0)
    output = mido.MidiFile(file=buffer)
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('project.xml'))
    assert root.find('Arrangement/Lanes').get('timeUnit') == 'seconds'
    initial_bpm = F(root.find('Transport/Tempo').get('value'))
    points = {F(0): initial_bpm}
    auto = root.find('Arrangement/TempoAutomation')
    if auto is not None:
        assert auto.get('unit', auto.get('timeUnit')) == 'seconds'
        for point in auto.findall('RealPoint'):
            assert point.get('interpolation') == 'hold'
            points[F(point.get('time'))] = F(point.get('value'))
    ordered = sorted(points.items())

    def beats(second):
        total, cursor, bpm = F(0), F(0), initial_bpm
        for time, change in ordered:
            if time > second:
                break
            total += (time-cursor)*bpm/60
            cursor, bpm = time, change
        return total + (second-cursor)*bpm/60

    definitions = {t.get('id'): t for t in root.findall('.//Structure//Track')}
    expected = {}
    for lane in root.findall('.//Arrangement//Lanes'):
        definition = definitions.get(lane.get('track'))
        if definition is None:
            continue
        ch = definition.find('Channel')
        if ch is None:
            assert lane.find('.//Note') is None
            continue
        assert ch.get('solo', 'false') == 'false'
        if ch.find('Mute').get('value') == 'true':
            continue
        events = expected.setdefault(definition.get('name'), Counter())
        for clip in lane.findall('./Clips/Clip'):
            if clip.get('enable') == 'false':
                continue
            assert not any(k in clip.attrib for k in ('contentTimeUnit', 'reference', 'loopEnd')) or clip.find('Notes') is None
            start = F(clip.get('time'))
            end = start + F(clip.get('duration'))
            content_zero = start - F(clip.get('playStart', '0'))
            for note in clip.findall('./Notes/Note'):
                on = content_zero + F(note.get('time'))
                off = on + F(note.get('duration'))
                if on >= end or off <= start:
                    continue
                for kind, time, velocity in (
                    ('note_on', max(on, start), round(F(note.get('vel')) * 127)),
                    ('note_off', min(off, end), round(F(note.get('rel')) * 127)),
                ):
                    tick = math.floor(beats(time)*output.ticks_per_beat + F(1, 2))
                    events[tick, kind, int(note.get('key')), velocity, int(note.get('channel'))] += 1
    total = 0
    for track in output.tracks:
        actual = Counter()
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type in ('note_on', 'note_off'):
                actual[tick, msg.type, msg.note, msg.velocity, msg.channel] += 1
        exp = expected.pop(track.name, Counter())
        # Fraction limiting in the importer can change a rounding tie by one
        # output tick. Match identity/multiplicity first, then allow that tick.
        common = actual & exp
        actual -= common
        exp -= common
        for key in list(actual.elements()):
            candidate = next((k for k in exp if exp[k] and k[1:] == key[1:] and abs(k[0]-key[0]) <= 1), None)
            assert candidate is not None, (track.name, key)
            exp[candidate] -= 1
        assert not +exp, track.name
        total += sum(common.values()) + sum(actual.values())
    assert not any(expected.values())
    assert total == event_count
