"""DAWproject timing, arrangement semantics and shared import boundary."""
import io
import json
import zipfile
from collections import Counter
from fractions import Fraction as F
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QUrl

from midi_interchange.core.document import Workspace
from midi_interchange.core.events import pair_notes
from midi_interchange.core.export_smf import audible_events, build_exports, ExportOptions, ExportMode
from midi_interchange.core.import_dawproject import import_dawproject
from midi_interchange.core.import_smf import ImportError_, import_smf_file
from midi_interchange.core.session import Session, encode, decode
from midi_interchange.interchange.drag_import import extract_payloads
from midi_interchange.interchange.readers import read_payload, payload_from_path, FILE_FILTER
from midi_interchange.ui.controller import Controller
from test_ui_assembly import app

SETS = Path(__file__).resolve().parents[1] / 'samples/project-sets'


def project(content, *, unit='beats', extra='', transport='', structure='', version='1.0'):
    xml = f'''<Project version="{version}"><Application name="Test" version="1"/>
    <Transport><Tempo value="120"/><TimeSignature numerator="4" denominator="4"/>{transport}</Transport>
    <Structure><Track id="t" name="Lead"><Channel><Mute value="true"/></Channel></Track>{structure}</Structure>
    <Arrangement><Lanes timeUnit="{unit}"><Lanes track="t"><Clips>{content}</Clips></Lanes></Lanes>{extra}</Arrangement></Project>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('project.xml', xml)
        z.writestr('metadata.xml', '<MetaData><Title>A song</Title></MetaData>')
    return output.getvalue()


NOTE = '<Note time="0" duration="1" key="60" channel="2" vel="0.5" rel="0.25"/>'
CLIP = f'<Clip time="4" duration="2"><Notes>{NOTE}</Notes></Clip>'


def read(data):
    return import_dawproject(None, 'test.dawproject', data)


def test_seconds_clip_crosses_tempo_change_and_roundtrips():
    data = project(CLIP, unit='seconds', extra='''<TempoAutomation timeUnit="seconds">
      <RealPoint time="0" value="120" interpolation="hold"/>
      <RealPoint time="4.5" value="60" interpolation="hold"/></TempoAutomation>''')
    source, tracks = read(data)
    c = tracks[0].clips[0]
    assert c.start == 8 and c.end == F(21, 2)
    n = pair_notes(c.events, c.length)[0][0]
    assert n.start == 0 and n.end == F(3, 2)
    assert n.on.msg.velocity == 64 and n.off.msg.velocity == 32 and n.channel == 2
    assert source.raw == b'' and source.byte_size == len(data)
    assert source.input_format == 'dawproject' and source.app == 'Test 1'
    assert source.song == 'A song' and source.file_summary.startswith('DAWproject 1.0')
    ws = Workspace()
    ws.add_import(source, tracks, preserve_track_state=True)
    assert ws.tracks[0].muted
    ws.tracks[0].muted = False
    ctl = Controller()
    ctl.ws = ws
    restored = decode(json.loads(json.dumps(encode(Session(ws.snapshot(), {})))))
    assert restored.workspace['sources'][0] == source
    assert restored.workspace['tracks'][0].clips[0].events == c.events


def test_trim_loop_alias_and_disabled_clips():
    data = project(f'''<Clip time="0" duration="5" playStart="1" loopStart="0" loopEnd="2">
      <Notes id="notes"><Note time="0" duration="2" key="60" vel="1"/></Notes></Clip>
      <Clip time="8" duration="1" playStart="1" reference="notes" enable="false"/>''')
    s, tracks = read(data)
    a, b = tracks[0].clips
    notes = pair_notes(a.events, a.length)[0]
    assert [(n.start, n.end) for n in notes] == [(0, 1), (1, 3), (3, 5)]
    assert b.muted and b.start == 8 and b.end == 9
    assert audible_events(b) == []
    ctl = Controller()
    ctl.ws.add_import(s, tracks)
    ctl.toggle_clip_mute(b.id)
    assert not b.muted
    ctl.undo()
    assert ctl.ws.tracks[0].clips[1].muted
    assert decode(encode(Session(ctl.ws.snapshot(), {}))).workspace['tracks'][0].clips[1].muted


@pytest.mark.parametrize('mode', list(ExportMode))
def test_muted_clip_excluded_from_every_export(mode):
    enabled = '<Clip time="0" duration="1"><Notes>' + NOTE.replace('key="60"', 'key="61"') + '</Notes></Clip>'
    s, tracks = read(project(CLIP.replace('<Clip ', '<Clip enable="false" ') + enabled))
    ws = Workspace()
    ws.add_import(s, tracks)
    tracks[0].muted = False
    from midi_interchange.core.ranges import Range
    ws.ranges = [Range(F(0), F(8), 'Full', track_locked=True)]
    tracks[0].soloed = True
    results = build_exports(ws, ExportOptions(mode=mode))
    assert results
    for result in results:
        notes = [m.note for t in result.midi.tracks for m in t if m.type == 'note_on']
        assert notes == [61]


def test_registry_file_drop_uses_path_and_handles_large_media(tmp_path, app):
    path = tmp_path / 'large.dawproject'
    path.write_bytes(project(CLIP))
    with zipfile.ZipFile(path, 'a') as z:
        z.writestr('audio/large.wav', b'0' * (65 * 1024 * 1024), compress_type=zipfile.ZIP_STORED)
    assert path.stat().st_size > 64 * 1024 * 1024
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    ps, errors = extract_payloads(mime)
    assert not errors and ps[0].data == b'' and ps[0].byte_size == path.stat().st_size
    ctl = Controller()
    assert ctl.import_payloads(ps) == []
    assert ctl.ws.sources[0].path == str(path)
    assert '*.dawproject' in FILE_FILTER
    ctl.undo()
    assert not ctl.ws.tracks
    ctl.redo()
    assert ctl.ws.tracks[0].muted


@pytest.mark.parametrize('data,match', [
    (b'broken zip', 'DAWproject'),
    (project(CLIP, version='2.0'), 'version'),
    (project(CLIP.replace('key="60"', 'key="200"')), 'range'),
    (project(CLIP, extra='<TempoAutomation><RealPoint time="1" value="100" interpolation="linear"/></TempoAutomation>'), 'ramps'),
    (project('<Clip time="0" duration="1" reference="missing"/>'), 'reference'),
    (project(CLIP.replace('duration="2"', 'duration="-1"')), 'extent'),
])
def test_bad_projects_fail_without_changing_workspace(data, match):
    with pytest.raises(ImportError_, match=match):
        read(data)


@pytest.mark.parametrize('name,tracks,clips,notes,muted', [
    ('indy-001x', 5, 105, 819, 2),
    ('Ditty-04-Macbook', 11, 175, 1501, 52),
    ('GA & Padshop 2-(alt instr 2)-01', 8, 182, 6435, 0),
])
def test_supplied_cubase_projects(name, tracks, clips, notes, muted):
    source, imported = read_payload(payload_from_path(str(SETS / (name+'.dawproject'))))
    assert len(imported) == tracks
    assert sum(len(t.clips) for t in imported) == clips
    assert sum(e.msg.type == 'note_on' for t in imported for c in t.clips for e in c.events) == notes
    assert sum(c.muted for t in imported for c in t.clips) == muted
    # Every imported source must survive session validation without its input file.
    ctl = Controller()
    ctl.ws.add_import(source, imported)
    decode(encode(Session(ctl.ws.snapshot(), {})))


def test_cubase_15_choir_matches_paired_midi():
    _, tracks = read_payload(payload_from_path(str(SETS / 'Ditty-04-Macbook.dawproject')))
    _, midi = import_smf_file(str(SETS / 'Ditty-04-Macbook.mid'))
    actual = next(t for t in tracks if t.name == 'Epic Choir')
    expected = next(t for t in midi if t.name == 'Epic Choir')
    def signature(events):
        return Counter((round(e.time*480), e.msg.type, e.msg.note, e.msg.velocity if e.msg.type == 'note_on' else 0, e.msg.channel)
                       for e in events if e.msg.type in ('note_on', 'note_off') and not (e.msg.type == 'note_on' and e.msg.velocity == 0))
    assert signature([e for c in actual.clips for e in audible_events(c)]) == signature([e for c in expected.clips for e in c.events])


def test_schema_2_upgrades_defaults_and_preserves_exports():
    source, tracks = import_smf_file(str(SETS / 'indy-001x.mid'))
    ctl = Controller()
    ctl.ws.add_import(source, tracks, preserve_track_state=True)
    current = encode(Session(ctl.ws.snapshot(), {}))
    legacy = json.loads(json.dumps(current))
    legacy['schema_version'] = 2
    def remove_new_fields(obj):
        if isinstance(obj, dict):
            if obj.get('kind') == 'Source':
                del obj['data']['input_format']
                del obj['data']['format_version']
            if obj.get('kind') == 'Clip':
                del obj['data']['muted']
            for value in obj.values():
                remove_new_fields(value)
        elif isinstance(obj, list):
            for value in obj:
                remove_new_fields(value)
    remove_new_fields(legacy)
    assert encode(decode(legacy)) == current


def test_malformed_drop_is_atomic(app):
    from midi_interchange.interchange.payload import Payload
    ctl = Controller()
    ctl.import_payloads([Payload('valid.dawproject', project(CLIP))])
    before = encode(Session(ctl.ws.snapshot(), {}))
    assert ctl.import_payloads([Payload('broken.dawproject', b'invalid')])
    assert encode(Session(ctl.ws.snapshot(), {})) == before


def test_mixed_time_units_and_trim_restore():
    s, ts = read(project(f'<Clip time="4" duration="4" contentTimeUnit="seconds" playStart="1"><Notes>{NOTE}</Notes></Clip>'))
    c = ts[0].clips[0]
    assert c.offset == 2 and c.start == 4 and c.end == 8
    assert c.events[0].time == 0 and c.events[1].time == 2
    assert not any(e.msg.type == 'note_on' for e in audible_events(c))
    c.trim_start = 0
    assert any(e.msg.type == 'note_on' for e in audible_events(c))


@pytest.mark.parametrize('xml,match', [
    ('<Project>', 'DAWproject'),
    ('<!DOCTYPE Project [<!ENTITY x "hi">]><Project version="1.0"/>', 'Unsafe'),
    ('<Project version="1.0"><Arrangement/><Notes id="x"/><Notes id="x"/></Project>', 'Duplicate'),
])
def test_bad_xml(xml, match):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('project.xml', xml)
    with pytest.raises(ImportError_, match=match):
        read(output.getvalue())


def test_nested_clip_and_group_mute():
    data = project(f'<Clip time="4" duration="4"><Clips><Clip time="1" duration="2"><Notes>{NOTE}</Notes></Clip></Clips></Clip>')
    _, ts = read(data)
    c = ts[0].clips[0]
    assert c.start == 4
    assert [(e.time, e.msg.type) for e in audible_events(c)] == [(5, 'note_on'), (6, 'note_off')]


def test_time_signature_automation_and_markers():
    _, ts = read(project(CLIP, extra='<Markers timeUnit="seconds"><Marker time="2" name="Verse"/></Markers>'))
    assert ts[-1].auxiliary and ts[-1].clips[0].events[0].time == 4
    s, _ = read(project(CLIP, extra='<TimeSignatureAutomation timeUnit="seconds"><TimeSignaturePoint time="2" numerator="3" denominator="4"/></TimeSignatureAutomation>'))
    assert s.tempo_map.timesigs[-1].time == 4 and s.tempo_map.timesigs[-1].numerator == 3


def test_group_mute_and_solo_inherited():
    data = project(CLIP, structure='<Track id="group"><Channel solo="true"><Mute value="true"/></Channel><Track id="child" name="Child"/></Track>')
    # Move the existing MIDI lane to the nested child track.
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(buf, 'w') as rewritten:
        rewritten.writestr('project.xml', original.read('project.xml').replace(b'track="t"', b'track="child"'))
    _, ts = read(buf.getvalue())
    assert ts[0].name == 'Child' and ts[0].muted and ts[0].soloed


def test_nested_alias_and_disabled_nested_clip():
    xml = f'<Clip time="0" duration="1"><Notes id="n">{NOTE}</Notes></Clip><Clip time="4" duration="2"><Clips><Clip time="0" duration="1" reference="n"/></Clips></Clip>'
    _, ts = read(project(xml))
    assert len(ts[0].clips) == 2 and ts[0].clips[1].events[0].time == 0
    with pytest.raises(ImportError_, match='Nested disabled'):
        read(project(xml.replace('reference="n"', 'reference="n" enable="false"')))


def test_disabled_loop_retains_notes():
    _, ts = read(project('<Clip time="0" duration="4" loopEnd="2" enable="false"><Notes>' + NOTE + '</Notes></Clip>'))
    c = ts[0].clips[0]
    assert c.muted and len(pair_notes(c.events, c.length)[0]) == 2
    assert not audible_events(c)
    c.muted = False
    assert len(audible_events(c)) == 4
