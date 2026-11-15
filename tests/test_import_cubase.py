"""Native Cubase project (.cpr) reader: tier fixtures, real projects, registry,
failure handling and sessions. Format evidence: test_cpr_inspect.py and
docs/plans/cubase-import.md."""
import json
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from midi_interchange.core.document import Workspace
from midi_interchange.core.events import pair_notes
from midi_interchange.core.export_smf import ExportMode, ExportOptions, audible_events, build_exports
from midi_interchange.core.import_cubase import import_cubase
from midi_interchange.core.import_smf import ImportError_
from midi_interchange.core.session import Session, decode, encode
from midi_interchange.interchange.readers import FILE_FILTER, payload_from_path, read_payload

ROOT = Path(__file__).resolve().parents[1]
PHASES = ROOT / 'samples/project-cubase-phases'
TIER1, TIER2, TIER3 = (PHASES / f'Tier {n}' / 'Cubase16' for n in (1, 2, 3))
SETS = ROOT / 'samples/project-sets'


def read(path):
    result = read_payload(payload_from_path(str(path)))
    return result.source, result.tracks, result


def notes(track):
    """(start, end, pitch, velocity, channel) in workspace beats, visible part only."""
    out = []
    for clip in track.clips:
        if clip.muted:
            continue
        for n in pair_notes(clip.events, clip.length)[0]:
            if clip.trim_start <= n.start < clip.trim_end:
                out.append((clip.offset + n.start, clip.offset + min(n.end, clip.trim_end), n.pitch, n.velocity, n.channel))
    return sorted(out)


def by_name(tracks):
    return {t.name: t for t in tracks}


# ---------------------------------------------------------------- tiers

def test_tier1_note_fields_and_source():
    source, tracks, result = read(TIER1 / 'c07.cpr')
    (track,) = tracks
    assert track.name == 'Padshop 01' and result.preserve_track_state
    assert notes(track) == [(1, 3, 62, 64, 0), (4, F(9, 2), 64, 90, 0)]
    assert source.input_format == 'cubase' and source.format_version == '16.0.5'
    assert source.app == 'Cubase 16.0.5' and source.ppq == 480
    assert source.file_summary.startswith('Cubase project 16.0.5')
    assert source.display_bar_offset == 0 and source.display_offset_note is None
    releases = [e.msg.velocity for e in track.clips[0].events if e.msg.type == 'note_off']
    assert releases == [64, 64]


def test_display_offset_recorded_not_applied():
    source, tracks, _ = read(PHASES / 'Tier 1/Cubase15/c02-1.cpr')
    assert source.display_bar_offset == -1
    assert 'bar 1 at bar 2' in source.display_offset_note
    assert 'Display:' in source.describe()
    assert notes(tracks[0])[0][0] == 4          # absolute timeline: the blank bar stays


@pytest.mark.parametrize('step, start, trim_start, end, muted', [
    ('c10', 16, 0, 24, False),
    ('c11', 17, 1, 24, False),       # start trim keeps content zero at beat 16
    ('c12', 17, 1, F(95, 4), False), # end trimmed one sixteenth
    ('c13', 17, 1, F(95, 4), True),  # part muted
])
def test_tier2_part_window_trim_and_mute(step, start, trim_start, end, muted):
    _, (track,), _ = read(TIER2 / f'{step}.cpr')
    (clip,) = track.clips
    assert (clip.start, clip.trim_start, clip.end, clip.muted, clip.name) == (start, trim_start, end, muted, 'Riff')
    assert audible_events(clip) == [] if muted else len(audible_events(clip)) == 4


def test_tier2_track_states_folder_and_channel():
    assert by_name(read(TIER2 / 'c14.cpr')[1])['Lead'].muted
    t = by_name(read(TIER2 / 'c17s.cpr')[1])
    assert t['Lead'].soloed and not t['Lead'].muted and not t['MIDI 01'].soloed
    t = by_name(read(TIER2 / 'c17m.cpr')[1])
    assert t['MIDI 01'].muted and not t['Lead'].muted
    assert notes(t['MIDI 01']) == [(0, 1, 60, 100, 1)]           # channel 2
    source, tracks, _ = read(TIER2 / 'c18fm.cpr')
    assert all(t.muted for t in tracks)
    assert any('Folder tracks are flattened' in w for w in source.warnings)


def test_tier2_shared_copy_shares_events():
    _, (track,), _ = read(TIER2 / 'c16.cpr')
    first, copy = track.clips
    assert copy.events is first.events and copy.start == 32
    _, (track,), _ = read(TIER2 / 'c15.cpr')
    assert track.clips[0].events is not track.clips[1].events


def test_tier2_instrument_stack_uses_stack_track_name():
    t = by_name(read(TIER2 / 'c18is.cpr')[1])
    assert set(t) == {'Instrument Stack 01', 'MIDI 01'}             # as Cubase's MIDI export


def test_tier3_tempo_ramp_signature_and_markers():
    source, tracks, _ = read(TIER3 / 'c23.cpr')
    tempos = [(t.time, round(t.bpm, 3)) for t in source.tempo_map.tempos]
    assert tempos[0] == (0, 120) and tempos[1][0] == 8 and tempos[-1][1] == 90
    assert [t for t, _ in tempos[1:-1]] == list(range(8, 17))       # a step every beat
    assert all(a[1] > b[1] for a, b in zip(tempos[1:], tempos[2:]))
    assert any('Tempo ramps are approximated' in w for w in source.warnings)
    assert [(s.time, s.numerator) for s in source.tempo_map.timesigs] == [(0, 4), (16, 3)]
    markers = by_name(tracks)['Markers']
    assert markers.auxiliary
    got = [(e.time, e.msg.text) for e in markers.clips[0].events]
    assert got == [(0, 'Intro'), (4, 'Verse'), (12, 'Intro |'), (19, 'Chorus')]


def test_tier3_controllers_pitch_bend_program():
    source, tracks, _ = read(TIER3 / 'c25.cpr')
    events = by_name(tracks)['MIDI 01'].clips[0].events
    kinds = [e.msg.type for e in events]
    assert kinds.count('control_change') == 7 and kinds.count('pitchwheel') == 12
    first = {e.msg.type: e.msg for e in reversed(events)}
    assert first['program_change'].program == 31 and first['program_change'].channel == 1
    assert first['pitchwheel'].pitch == -6084 and first['control_change'].value == 10
    assert any('curve shapes' in w for w in source.warnings)


def test_tier3_linear_time_base_track_reported_not_imported():
    source, tracks, _ = read(TIER3 / 'c26.cpr')
    assert 'Lead' not in by_name(tracks)
    assert any('"Lead" uses the linear' in w for w in source.warnings)


# --------------------------------------------------------- real projects

@pytest.mark.parametrize('name, version, offset, notes_, muted_clips, muted_tracks', [
    ('Ditty-04-Macbook', '15.0.21', -3, 1501, 52, set()),
    ('GA & Padshop 2-(alt instr 2)-01', '15.0.30', 0, 6435, 0, {'Engaging Peace', 'Where Are We'}),
    ('indy-001x', '15.0.30', -1, 819, 2, set()),
])
def test_real_projects_match_dawproject_counts(name, version, offset, notes_, muted_clips, muted_tracks):
    source, tracks, _ = read(SETS / f'{name}.cpr')
    assert source.format_version == version and source.display_bar_offset == offset
    music = [t for t in tracks if not t.auxiliary]
    assert sum(1 for t in music for c in t.clips for e in c.events if e.msg.type == 'note_on') == notes_
    assert sum(c.muted for t in music for c in t.clips) == muted_clips
    assert {t.name for t in music if t.muted} == muted_tracks


def test_indy_export_matches_cubase_midi_in_reference_window():
    """Phase 2 go/no-go, now through the reader and the real exporter."""
    from scripts.compare_project_exports import compare
    result = compare(SETS / 'indy-001x.cpr', SETS / 'indy-001x.mid', window=(3, 196))
    rows = {r['track']: r['notes'] for r in result['tracks']}
    assert {k: (v['exact'], v['changed_duration'], v['app_only'], v['cubase_only']) for k, v in rows.items()} == {
        'Bass Sequence': (390, 0, 0, 0), 'Industrial Stab': (225, 0, 0, 0),
        'Secondary Motif': (24, 0, 0, 0), 'Texture Bed': (22, 2, 0, 0)}    # two known clip-edge tails
    assert {t['track'] for t in result['unmatched_cubase_tracks']} == {'Drum Core', 'Drum Core ='}
    assert any('Pattern Editor' in w for w in result['warnings'])


def test_ga_matches_dawproject_before_tempo_ramp_and_stays_on_grid_after():
    """Native positions are beats. Cubase's DAWproject export stores seconds
    but reduces GA's tempo ramps (from beat 264) to steps, so DAWproject
    positions drift after the ramp (e.g. 271.83 for 272). Before it, the two
    readers agree within one tick."""
    cpr = by_name(read(SETS / 'GA & Padshop 2-(alt instr 2)-01.cpr')[1])
    daw = by_name(read(SETS / 'GA & Padshop 2-(alt instr 2)-01.dawproject')[1])
    for name in ('hbar Sample Pack 1 Kit', 'Piano Chords', 'Piano Chords (D)', 'Engaging Peace', 'Where Are We'):
        x, y = notes(cpr[name]), notes(daw[name])
        assert len(x) == len(y)
        early = [(p, q) for p, q in zip(x, y) if q[0] < 264]
        assert all(abs(p[0] - q[0]) <= F(1, 480) and p[2:4] == q[2:4] for p, q in early)
    # A part extended before its content (negative offset): content zero 392,
    # visible from 376; its notes sit on the beat grid.
    clip = next(c for c in cpr['Where Are We'].clips if c.start == 376)
    assert clip.trim_start == 0 and clip.offset == 376
    assert [n[0] for n in notes(cpr['Where Are We']) if n[0] >= 376][:3] == [384, 388, 392]


# ------------------------------------------------- registry and failures

def test_registry_detects_cpr_path_backed(tmp_path):
    assert '*.cpr' in FILE_FILTER
    p = payload_from_path(str(TIER1 / 'c02.cpr'))
    assert p.data == b'' and p.path.endswith('c02.cpr') and p.byte_size == (TIER1 / 'c02.cpr').stat().st_size
    # Detection by content too (e.g. a renamed file supplied as bytes).
    source, _ = import_cubase(None, 'renamed.bin', (TIER1 / 'c02.cpr').read_bytes())
    assert source.byte_size == (TIER1 / 'c02.cpr').stat().st_size


def test_unsupported_version_fails_cleanly():
    data = (TIER1 / 'c02.cpr').read_bytes().replace(b'Version 16.0.5', b'Version 14.0.5', 1)
    with pytest.raises(ImportError_, match='Cubase 14.0.5 projects are not supported'):
        import_cubase(None, 'old.cpr', data)


@pytest.mark.parametrize('damage', [
    lambda d: d[:len(d) // 2],                      # truncated
    lambda d: b'RIFX' + d[4:],                      # wrong magic
    lambda d: d[:40] + b'\xff' * 64 + d[104:],      # corrupt archive header
])
def test_damaged_projects_fail_without_workspace_change(damage):
    data = damage((TIER1 / 'c07.cpr').read_bytes())
    ws = Workspace()
    with pytest.raises(ImportError_):
        ws.add_import(*import_cubase(None, 'broken.cpr', data))
    assert ws.tracks == []


def test_input_file_is_never_modified(tmp_path):
    path = tmp_path / 'c25.cpr'
    path.write_bytes((TIER3 / 'c25.cpr').read_bytes())
    before = path.read_bytes(), path.stat().st_mtime_ns
    read(path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


# --------------------------------------------------------------- sessions

def test_session_roundtrip_keeps_cubase_source_and_exports():
    source, tracks, result = read(SETS / 'indy-001x.cpr')
    ws = Workspace()
    ws.add_import(source, tracks, preserve_track_state=result.preserve_track_state)
    restored = Workspace()
    restored.restore(decode(json.loads(json.dumps(encode(Session(ws.snapshot(), {}))))).workspace)
    s = restored.sources[0]
    assert (s.input_format, s.format_version, s.display_bar_offset) == ('cubase', '15.0.30', -1)
    for mode in ExportMode:
        a = [(r.label, r.midi.tracks) for r in build_exports(ws, ExportOptions(mode=mode))]
        b = [(r.label, r.midi.tracks) for r in build_exports(restored, ExportOptions(mode=mode))]
        assert [(label, [list(map(str, t)) for t in trks]) for label, trks in a] == \
               [(label, [list(map(str, t)) for t in trks]) for label, trks in b]
