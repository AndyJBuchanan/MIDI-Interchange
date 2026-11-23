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


def read_disabled(path):
    result = read_payload(payload_from_path(str(path)), include_disabled=True)
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

def muted_note_count(path):
    from midi_interchange.core import cpr_format as cf
    wk, _ = cf.walk_archive(cf.read_container(None, path.read_bytes()), 'Arrangement1', skip=cf.READER_SKIP)
    parts = [o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent']
    return sum(1 for o in parts for e in cf.decode_part_events(wk, cf.part_event_info(wk, o).part)[0]
               if e.status == 0x90 and e.muted)


@pytest.mark.parametrize('name, version, offset, notes_, muted_notes, muted_clips, muted_tracks', [
    ('Ditty-04-Macbook', '15.0.21', -3, 1501, 19, 52, set()),
    ('GA & Padshop 2-(alt instr 2)-01', '15.0.30', 0, 6435, 2486, 0, {'Engaging Peace', 'Where Are We'}),
    ('indy-001x', '15.0.30', -1, 819, 2, 2, set()),
])
def test_real_projects_match_dawproject_counts(name, version, offset, notes_, muted_notes, muted_clips, muted_tracks):
    """Cubase's DAWproject export keeps muted notes (unmarked); its MIDI
    export and the native reader leave them out."""
    source, tracks, _ = read(SETS / f'{name}.cpr')
    assert source.format_version == version and source.display_bar_offset == offset
    music = [t for t in tracks if not t.auxiliary]
    assert muted_note_count(SETS / f'{name}.cpr') == muted_notes
    assert sum(1 for t in music for c in t.clips for e in c.events if e.msg.type == 'note_on') == notes_ - muted_notes
    assert ('Muted notes are not imported' in source.warnings) == bool(muted_notes)
    assert sum(c.muted for t in music for c in t.clips) == muted_clips
    assert {t.name for t in music if t.muted} == muted_tracks


def test_release_velocity_zero_is_kept():
    """OffV is (v - 1) / 126, which can't hold 0. Cubase stores OffV 0.0 with a 0 tail byte for a
    release of 0 and exports it as velocity 0 (docs/formats/CUBASE_FILE_FORMAT.md, 6.2). In Ditty the
    release values are 100, 64 and 0, matching the tail byte on every note."""
    from collections import Counter
    _, tracks, _ = read(SETS / 'Ditty-04-Macbook.cpr')
    releases = Counter(e.msg.velocity for t in tracks for c in t.clips for e in c.events if e.msg.type == 'note_off')
    assert releases[0] == 158 and releases[100] == 854 and releases[64] == 470
    assert sum(releases.values()) == 1501 - 19          # less the muted notes


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


def test_ga_whole_song_matches_cubase_midi_export():
    """GA's whole-song MIDI export (2026-11-15), through the reader and the
    real exporter: every note on every exported track, across the tempo
    ramp, with the kit's 2,399 muted notes left out and Prologue's +24 track
    transpose (MIDI Modifiers) applied, as Cubase does."""
    from scripts.compare_project_exports import compare
    stem = 'GA & Padshop 2-(alt instr 2)-01'
    if not (SETS / f'{stem}.mid').exists():
        pytest.skip('whole-song GA export not present')
    rows = {r['track']: r['notes'] for r in compare(SETS / f'{stem}.cpr', SETS / f'{stem}.mid')['tracks']}
    assert {k: (v['exact'], v['changed_duration'], v['app_only'], v['cubase_only']) for k, v in rows.items()} == {
        'hbar Sample Pack 1 Kit': (2548, 0, 0, 0), 'HALion Sonic SE 01': (80, 0, 0, 0),
        'Retrologue 01': (14, 0, 0, 0), 'Piano Chords': (499, 0, 0, 0), 'Piano Chords (D)': (748, 0, 0, 0),
        'Prologue 01': (20, 0, 0, 0)}
    tracks = by_name(read(SETS / f'{stem}.cpr')[1])
    assert {n: t.source_transpose for n, t in tracks.items() if t.source_transpose} == {'Prologue 01': 24}


def test_ga_matches_dawproject_before_tempo_ramp_and_stays_on_grid_after():
    """Native positions are beats. Cubase's DAWproject export stores seconds
    but reduces GA's tempo ramps (from beat 264) to steps, so DAWproject
    positions drift after the ramp (e.g. 271.83 for 272). Before it, the two
    readers agree within one tick."""
    cpr = by_name(read(SETS / 'GA & Padshop 2-(alt instr 2)-01.cpr')[1])
    daw = by_name(read(SETS / 'GA & Padshop 2-(alt instr 2)-01.dawproject')[1])
    # Muted notes are in the DAWproject (unmarked) but not imported: the kit's
    # 2,399 (see the whole-song test), 1 on Engaging Peace, 4 on Where Are We.
    for name, muted in (('Piano Chords', 0), ('Piano Chords (D)', 0), ('Engaging Peace', 1), ('Where Are We', 4)):
        x, y = notes(cpr[name]), notes(daw[name])
        assert len(x) == len(y) - muted
        for p in (n for n in x if n[0] < 264):
            assert any(abs(p[0] - q[0]) <= F(1, 480) and p[2:4] == q[2:4] for q in y)
    # A part extended before its content (negative offset): content zero 392,
    # visible from 376; its notes sit on the beat grid.
    clip = next(c for c in cpr['Where Are We'].clips if c.start == 376)
    assert clip.trim_start == 0 and clip.offset == 376
    assert [n[0] for n in notes(cpr['Where Are We']) if n[0] >= 376][:3] == [384, 392, 400]   # 388 is a muted note


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


# ------------------------------------------- verify files (user spot test)

VERIFY = PHASES / 'Verify'


def verify(name):
    path = VERIFY / name
    if not path.exists():
        pytest.skip(f'{name} is not in the repository (local verify file)')
    return path


def test_verify_bbcso_score_symbols_and_named_flags_tail():
    """15.0.10: parts start with MScoreEvent objects (Score Editor symbols),
    which are stepped over; the mixer tail after the flags has a u32 count
    and the track's own name."""
    source, tracks, _ = read(verify('BBCSO_Woodwinds101-App01-MacBook.cpr'))
    music = [t for t in tracks if not t.auxiliary]
    # 34 tracks have parts; the 18 disabled in Cubase are left out (16 imported), as in its export
    assert len(music) == 16 and not any(t.muted or t.soloed for t in music)
    assert sum(1 for t in music for c in t.clips for e in c.events if e.msg.type == 'note_on') == 1807
    assert any('Score Editor symbols' in w and 'articulation' in w for w in source.warnings)
    # Markers are declared past 16 MB, so their references start 0x81: all 8
    # must be found, as in Cubase's MIDI export (user, 2026-11-16).
    (markers,) = [t for t in tracks if t.auxiliary]
    assert [(e.time, e.msg.text) for c in markers.clips for e in c.events] == [
        (0, 'Pre Roll'), (8, 'Count'), (16, 'Cue Start'), (40, 'A'), (80, 'B'), (120, 'C'), (160, 'D'), (200, 'E')]
    mid = VERIFY / 'BBCSO_Woodwinds101-App01-MacBook.midi'
    if mid.exists():
        exported, t = [], 0
        for msg in mido.MidiFile(mid).tracks[0]:
            t += msg.time
            if msg.type == 'marker':
                exported.append((F(t, 480), msg.text))
        assert exported == [(e.time, e.msg.text) for c in markers.clips for e in c.events]


def test_verify_beat003_object_properties_and_flags_sentinel():
    """15.0.30: note properties of type 0x22 and 0x0408 hold objects
    (Omnivocal lyric attributes); a mixer tail ends FF FF FF FF 00 00 00 00."""
    source, tracks, _ = read(verify('Beat003vs.cpr'))
    t = by_name(tracks)
    counts = {n: sum(1 for c in t[n].clips for e in c.events if e.msg.type == 'note_on')
              for n in ('Melody', 'Omnivocal Chorus', 'Chord Bed', 'DUNE 3 01')}
    assert counts == {'Melody': 104, 'Omnivocal Chorus': 20, 'Chord Bed': 252, 'DUNE 3 01': 56}   # Chord Bed: 4 muted notes
    assert t['Omnivocal Chorus'].muted and source.display_bar_offset == -2
    assert not any('later events' in w for w in source.warnings)


def test_verify_out_of_range_value_skipped_not_fatal():
    """15.0.5, 173 MB (above GitHub's file limit, so usually absent): one
    aftertouch value of 201 is skipped with a warning; the mixer bodies'
    plug-in states are not walked, keeping the import fast."""
    import time
    path = verify('orchestral-import-test-01.cpr')
    t0 = time.time()
    source, tracks, _ = read(path)
    assert time.time() - t0 < 2
    # 170 tracks were imported before disabled tracks were left out (169 plus Markers); 25 are not disabled
    assert len(tracks) == 25 and sum(1 for t in tracks if t.auxiliary) == 1
    assert sum(1 for t in tracks for c in t.clips for e in c.events if e.msg.type == 'note_on') == 579
    assert any('out-of-range' in w for w in source.warnings)
    source, tracks, _ = read_disabled(path)
    assert len(tracks) == 170
    assert sum(1 for t in tracks for c in t.clips for e in c.events if e.msg.type == 'note_on') == 605


def test_verify_cubase14_rejected_until_validated():
    with pytest.raises(ImportError_, match='Cubase 14.0.20 projects are not supported'):
        read(verify('Scaler3Test-001(14).cpr'))


def test_skipping_mixer_bodies_does_not_change_imports():
    """The reader skips mixer-object bodies after registering every class
    declaration; the result must equal a full walk."""
    from midi_interchange.core import cpr_format as cf, import_cubase as ic
    paths = [TIER2 / 'c17m.cpr', TIER3 / 'c25.cpr', SETS / 'indy-001x.cpr', SETS / 'Ditty-04-Macbook.cpr']
    paths += [p for p in (VERIFY / 'Beat003vs.cpr', VERIFY / 'BBCSO_Woodwinds101-App01-MacBook.cpr') if p.exists()]

    def signature(path):
        s, tracks = ic.import_cubase(str(path), path.name)
        return ([(t.name, t.muted, t.soloed, [(c.offset, c.trim_start, c.trim_end, c.muted,
                 [(e.time, str(e.msg)) for e in c.events]) for c in t.clips]) for t in tracks], s.warnings)
    for path in paths:
        skipped = signature(path)
        original = cf.READER_SKIP
        try:
            cf.READER_SKIP = frozenset()
            full = signature(path)
        finally:
            cf.READER_SKIP = original
        assert skipped == full, path.name


def test_verify_drum_track_is_a_track_and_lyric_project_imports():
    """16.0.5: Cubase's Drum Track (MDrumTrackEvent) is recognised and its
    state read; this one holds only a pattern part (reported until pattern
    rendering exists). The project's Omnivocal parts import."""
    from midi_interchange.core import cpr_format as cf
    path = verify('vocalfun001(16).cpr')
    c = cf.read_container(str(path))
    wk, _ = cf.walk_archive(c, 'Arrangement1', skip=cf.READER_SKIP)
    drums = [o for o in wk.objects.values() if o.cls.name == 'MDrumTrackEvent']
    assert [cf.track_name(wk, o) for o in drums] == ['Drums']
    assert cf.track_state_flags(wk, drums[0]) == 0
    source, tracks, _ = read(path)
    assert by_name(tracks)['Omnivocal Reeve'].clips
    assert any('Pattern Editor parts are not imported' in w for w in source.warnings)


# ---------------------------------------------------------------- disabled and hidden tracks
# docs/plans/cubase-disabled-tracks.md; format: CUBASE_FILE_FORMAT.md section 4.3

DT = PHASES / 'DTracks'
DISABLED_B = 'Track "Pianoteq 9 B" is disabled in Cubase; not imported'


def music(tracks):
    return [t for t in tracks if not t.auxiliary]


def note_count(track):
    return sum(1 for c in track.clips for e in c.events if e.msg.type == 'note_on')


def exported(path):
    """(track name, note count) for each track of Cubase's own MIDI export that has notes."""
    out = []
    for t in mido.MidiFile(path).tracks:
        n = sum(1 for m in t if m.type == 'note_on' and m.velocity > 0)
        if n:
            out.append((t.name, n))
    return out


def cpr_flags(path):
    from midi_interchange.core import cpr_format as cf
    data = Path(path).read_bytes()
    wk, _ = cf.walk_archive(cf.read_container(str(path), data), 'Arrangement1', skip=cf.READER_SKIP)
    return {cf.track_name(wk, o): cf.track_disabled_hidden(wk, o)
            for o in sorted((o for o in wk.objects.values() if o.cls.name in (*cf.TRACK_EVENTS, 'MAudioTrackEvent')),
                            key=lambda o: o.tag_at)}


@pytest.mark.parametrize('name, expected', [
    ('d0', ['Pianoteq 9 A', 'Pianoteq 9 B', 'Pianoteq 9 C']), ('d5', ['Pianoteq 9 A', 'Pianoteq 9 B', 'Pianoteq 9 C']),
    ('d6 baseline', ['MIDI 01']), ('d10 baseline', ['Pianoteq 9 01'])])
def test_nothing_disabled_imports_as_before(name, expected):
    """Enabled twins and untoggled tracks: no disabled note, nothing left out ('equals 1', not 'present':
    d0's and d5's track B keep noit = 0)."""
    assert not any(disabled for disabled, _ in cpr_flags(DT / f'{name}.cpr').values())
    source, tracks, _ = read(DT / f'{name}.cpr')
    assert not any('disabled' in w for w in source.warnings)
    assert [t.name for t in music(tracks)] == expected


def test_d7_baseline_fails_as_before():
    """A drum track holding only Pattern Editor parts: the same error as before this feature."""
    with pytest.raises(ImportError_, match='^Could not read Cubase project: The project contains no supported MIDI parts or markers$'):
        read(DT / 'd7 baseline.cpr')


def test_disabled_marker_equals_one_not_present():
    assert cpr_flags(DT / 'd0.cpr')['Pianoteq 9 B'] == (False, False)      # noit = 0
    assert cpr_flags(DT / 'd5.cpr')['Pianoteq 9 B'] == (False, False)      # disabled then re-enabled: noit = 0
    assert cpr_flags(DT / 'd1.cpr')['Pianoteq 9 B'] == (True, False)
    assert cpr_flags(DT / 'd2.cpr')['Pianoteq 9 B'] == (True, False)       # also muted
    assert cpr_flags(DT / 'd4.cpr')['Pianoteq 9 B'] == (False, True)       # hidden: noit = 0, dihT = 1


@pytest.mark.parametrize('name', ['d1', 'd2'])
def test_disabled_track_left_out_matching_cubase_export(name):
    source, tracks, _ = read(DT / f'{name}.cpr')
    assert [t.name for t in music(tracks)] == ['Pianoteq 9 A', 'Pianoteq 9 C']
    assert DISABLED_B in source.warnings
    assert [(t.name, note_count(t)) for t in music(tracks)] == exported(DT / f'{name}.midi')


def test_disabled_and_muted_d2_is_still_disabled():
    flags = cpr_flags(DT / 'd2.cpr')
    assert flags['Pianoteq 9 B'][0] and not flags['Pianoteq 9 A'][0]


def test_hidden_track_still_imports_and_is_noted_matching_cubase_export():
    source, tracks, _ = read(DT / 'd4.cpr')
    assert [(t.name, note_count(t)) for t in music(tracks)] == exported(DT / 'd4.midi')
    assert 'Track "Pianoteq 9 B" is hidden in Cubase; imported' in source.warnings
    assert not any('disabled' in w for w in source.warnings)


def test_enabled_twin_d5_matches_its_export_and_has_no_notes():
    source, tracks, _ = read(DT / 'd5.cpr')
    assert [(t.name, note_count(t)) for t in music(tracks)] == exported(DT / 'd5.midi')
    assert not any('disabled' in w or 'hidden' in w for w in source.warnings)


@pytest.mark.parametrize('name,count', [('d6', 1), ('d7', 1), ('d8', 1), ('d9', 1), ('d10', 2), ('d11', 1)])
def test_all_importable_tracks_disabled_gives_a_clearer_error(name, count):
    with pytest.raises(ImportError_) as err:
        read(DT / f'{name}.cpr')
    text = str(err.value)
    verb = 'is' if count == 1 else 'are'
    assert (f'{count} track{"" if count == 1 else "s"} in the project {verb} disabled in Cubase, '
            'and no other track could be imported, so nothing was imported') in text
    assert 'no supported MIDI parts' not in text


def test_all_disabled_error_keeps_the_notes_collected():
    assert 'Pattern Editor parts are not imported' in _error(DT / 'd7.cpr')      # d7: drum track, Pattern Editor
    assert 'Audio tracks and media are not imported' in _error(DT / 'd10.cpr')   # d10: disabled audio track alongside


def test_all_disabled_d8_says_disabled_not_linear():
    text = _error(DT / 'd8.cpr')
    assert 'disabled in Cubase' in text and 'linear' not in text


def test_enabled_audio_only_project_keeps_the_existing_error():
    """d9 baseline holds only an enabled audio track; nothing is disabled, so the existing error stands."""
    assert 'no supported MIDI parts or markers' in _error(DT / 'd9 baseline.cpr')
    assert cpr_flags(DT / 'd9.cpr')['70sBandLoop'][0] and not cpr_flags(DT / 'd9 baseline.cpr')['70sBandLoop'][0]


def _error(path):
    with pytest.raises(ImportError_) as err:
        read(path)
    return str(err.value)


def test_d10_enabled_twin_imports_the_instrument_track():
    source, tracks, _ = read(DT / 'd10 baseline.cpr')
    assert [t.name for t in music(tracks)] == ['Pianoteq 9 01']
    assert 'Folder tracks are flattened; folder mute/solo is applied to their tracks' in source.warnings


def test_include_disabled_imports_the_tracks_muted():
    source, tracks, result = read_disabled(DT / 'd1.cpr')
    assert [(t.name, t.muted) for t in music(tracks)] == [
        ('Pianoteq 9 A', False), ('Pianoteq 9 B', True), ('Pianoteq 9 C', False)]
    assert 'Track "Pianoteq 9 B" is disabled in Cubase; imported muted' in source.warnings
    for name in ('d6', 'd10', 'd11'):
        _, tracks, _ = read_disabled(DT / f'{name}.cpr')
        assert music(tracks) and all(t.muted for t in music(tracks))
    # direct call
    _, tracks = import_cubase(str(DT / 'd1.cpr'), 'd1.cpr', include_disabled=True)
    assert [t.muted for t in music(tracks)] == [False, True, False]


def test_include_disabled_is_ignored_by_other_readers(tmp_path):
    from helpers import conductor, note, smf, track
    data = smf([conductor(480), track(note(0, 60, 0, 480), 'T')])
    from midi_interchange.interchange.payload import Payload
    result = read_payload(Payload('a.mid', data, byte_size=len(data)), include_disabled=True)
    assert [t.name for t in result.tracks] == ['T']


def test_disabled_does_not_change_the_other_cubase_fixtures():
    """Regression: every other fixture reads with nothing left out and the same tracks either way."""
    paths = sorted((TIER1.glob('*.cpr'))) + sorted(TIER2.glob('*.cpr')) + sorted(TIER3.glob('*.cpr')) + sorted(SETS.glob('*.cpr'))
    assert paths
    checked = 0
    for path in paths:
        try:
            a = read(path)
            b = read_disabled(path)
        except ImportError_:
            continue
        flags = cpr_flags(path)
        if any(disabled for disabled, _ in flags.values()):
            continue                       # covered by the disabled tests (GA, Beat003vs: audio only)
        checked += 1
        assert [(t.name, t.muted, t.soloed, len(t.clips)) for t in a[1]] == [(t.name, t.muted, t.soloed, len(t.clips)) for t in b[1]]
        assert not any('is disabled in Cubase' in w for w in a[0].warnings)
    assert checked > 20


def test_verify_bbcso_disabled_tracks_match_cubase_export():
    """The 18 of 34 tracks with noit = 1 are absent from Cubase's export; the other 16 match it."""
    path = verify('BBCSO_Woodwinds101-App01-MacBook.cpr')
    mid = VERIFY / 'BBCSO_Woodwinds101-App01-MacBook.midi'
    if not mid.exists():
        pytest.skip('BBCSO export is not in the repository')
    _, tracks, _ = read(path)
    _, everything, _ = read_disabled(path)
    assert len(music(everything)) == 34 and len(music(tracks)) == 16
    assert sum(1 for t in music(everything) if t.muted) == 18 + sum(1 for t in music(tracks) if t.muted)
    assert [(t.name, note_count(t)) for t in music(tracks)] == exported(mid)


def test_verify_orchestral_most_tracks_disabled():
    path = verify('orchestral-import-test-01.cpr')
    _, tracks, _ = read(path)
    assert len(tracks) == 25
