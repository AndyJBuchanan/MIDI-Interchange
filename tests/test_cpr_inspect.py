"""Regression evidence for the Cubase .cpr research inspector (phases 1-2).

tools/cpr_inspect.py is a research tool, not app code. These tests pin the
format findings recorded in docs/plans/cubase-import.md against the committed
fixtures, so later phases build on verified decoding.
"""
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import cpr_inspect as ci  # noqa: E402

TIER1 = ROOT / 'samples/project-cubase-phases/Tier 1'
SETS = ROOT / 'samples/project-sets'
VERSIONS = ['Cubase15', 'Cubase16']

# Expected tier 1 content, written by hand from the catalogue steps:
# (part start ticks, [(position, pitch, velocity, length)]), 480 PPQ.
TIER1_EXPECTED = {
    'c02': (0, [(0, 60, 100, 480)]),
    'c02-1': (1920, [(0, 60, 100, 480)]),        # one-bar display offset
    'c03': (0, [(480, 60, 100, 480)]),
    'c04': (0, [(480, 60, 64, 480)]),
    'c05': (0, [(480, 62, 64, 480)]),
    'c06': (0, [(480, 62, 64, 960)]),
    'c07': (0, [(480, 62, 64, 960), (1920, 64, 90, 240)]),
    'c08': (0, [(480, 62, 64, 960), (1920, 64, 90, 240)]),
    'c09': (0, [(480, 62, 64, 960), (1920, 64, 90, 240)]),
}


def _parts(path):
    c = ci.read_container(str(path))
    wk, objs = ci.walk_archive(c, 'Arrangement1')
    out = []
    stack = list(objs)
    while stack:
        o = stack.pop(0)
        if o.cls.name == 'MMidiPartEvent':
            start, length = ci.part_event_window(wk, o)
            for part in (ch for ch in o.children if ch.cls.name == 'MMidiPart'):
                events, problems, info = ci.decode_part_events(wk, part)
                out.append((start, length, info, events, problems))
            continue
        stack[0:0] = o.children
    return c, out


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('step', sorted(TIER1_EXPECTED))
def test_tier1_notes(version, step):
    path = TIER1 / version / f'{step}.cpr'
    c, parts = _parts(path)
    assert c.magic == 'RIF2'
    assert len(parts) == 1
    start, length, info, events, problems = parts[0]
    want_start, want_notes = TIER1_EXPECTED[step]
    assert problems == []
    assert (start, length) == (want_start, 3840)
    got = [(e.position, e.data[0], e.data[1], e.length) for e in events if e.status == 0x90]
    assert got == want_notes
    assert all(e.channel == 0 for e in events)
    # OffV is release velocity as (v - 1) / 126; Cubase's default is 64.
    assert all(round(1 + 126 * e.props['OffV']) == 64 for e in events)
    assert info['name'] == ('Riff' if step in ('c08', 'c09') else 'Padshop 01')


@pytest.mark.parametrize('version', VERSIONS)
def test_tier1_empty_project_has_no_parts(version):
    _, parts = _parts(TIER1 / version / 'c01.cpr')
    assert parts == []


def test_class_refs_are_declaration_offsets():
    c = ci.read_container(str(TIER1 / 'Cubase16/c07.cpr'))
    wk, _ = ci.walk_archive(c, 'Arrangement1')
    refs = [o for o in wk.objects.values() if o.kind == 'REF' and o.cls.name == 'MMidiNote']
    assert refs and all(wk.d[o.tag_at + 7] == 0xda and o.cls.offset == 0x9da for o in refs)


# Realistic projects: part and stored-note counts equal the DAWproject
# exports (docs/plans/dawproject-import.md, Paired-export evidence).
@pytest.mark.parametrize('name, magic, parts, notes, controllers, bends', [
    ('Ditty-04-Macbook', 'RIFF', 176, 1501, 1161, 16),
    ('GA & Padshop 2-(alt instr 2)-01', 'RIFF', 182, 6435, 0, 0),
    ('indy-001x', 'RIF2', 104, 819, 0, 0),
])
def test_realistic_projects_decode_completely(name, magic, parts, notes, controllers, bends):
    c, got = _parts(SETS / f'{name}.cpr')
    assert c.magic == magic
    assert len(got) == parts
    assert [p for *_, p in got if p] == []
    for *_, info, events, _ in got:
        assert len(events) == info['count']
    kinds = [e.status for *_, events, _ in got for e in events]
    assert (kinds.count(0x90), kinds.count(0xB0), kinds.count(0xE0)) == (notes, controllers, bends)


# ---------------------------------------------------------------- phase 2

TIER2 = ROOT / 'samples/project-cubase-phases/Tier 2/Cubase16'
TIER3 = ROOT / 'samples/project-cubase-phases/Tier 3/Cubase16'


def _walk(path):
    c = ci.read_container(str(path))
    return ci.walk_archive(c, 'Arrangement1')


def _part_events(wk):
    pes = sorted((o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent'), key=lambda o: o.tag_at)
    return [ci.part_event_info(wk, o) for o in pes]


def _tracks(wk):
    tes = sorted((o for o in wk.objects.values() if o.cls.name in ci.TRACK_EVENTS), key=lambda o: o.tag_at)
    return {ci.track_name(wk, t): ci.track_state_flags(wk, t) for t in tes}


@pytest.mark.parametrize('step, start, length, offset, muted', [
    ('c10', 7680, 3840, 0, False),      # moved to bar 5
    ('c11', 8160, 3360, 480, False),    # start trimmed one beat: content offset
    ('c12', 8160, 3240, 480, False),    # end trimmed one sixteenth
    ('c13', 8160, 3240, 480, True),     # part muted: flags bit 1
    ('c14', 8160, 3240, 480, False),    # part unmuted, track muted
])
def test_tier2_part_window_and_mute(step, start, length, offset, muted):
    wk, _ = _walk(TIER2 / f'{step}.cpr')
    (pe,) = _part_events(wk)
    assert (pe.start, pe.length, pe.offset, pe.muted, pe.shared) == (start, length, offset, muted, False)
    events, problems, _ = ci.decode_part_events(wk, pe.part)
    assert problems == []
    # Absolute note time = start - offset + position; c10 export: beats 17, 20.
    assert [(pe.start - pe.offset + e.position) / 480 for e in events] == [17, 20]


@pytest.mark.parametrize('step, flags', [
    ('c13', {'Lead': 0}),
    ('c14', {'Lead': ci.TRACK_MUTE}),                     # instrument track muted
    ('c17', {'Lead': 0, 'MIDI 01': 0}),
    ('c17s', {'Lead': ci.TRACK_SOLO, 'MIDI 01': 0}),      # instrument track soloed
    ('c17m', {'Lead': 0, 'MIDI 01': ci.TRACK_MUTE}),      # MIDI track muted
])
def test_tier2_track_state_flags(step, flags):
    wk, _ = _walk(TIER2 / f'{step}.cpr')
    assert _tracks(wk) == flags


@pytest.mark.parametrize('step, solo_flag', [('c13', None), ('c14', 1)])
def test_tier2_mixer_solo_flag_record_follows_mute(step, solo_flag):
    wk, _ = _walk(TIER2 / f'{step}.cpr')
    te = next(o for o in wk.objects.values() if o.cls.name == 'MInstrumentTrackEvent')
    assert ci.track_solo_flag(wk, te) == solo_flag


@pytest.mark.parametrize('step, shared', [('c15', False), ('c16', True)])
def test_tier2_copies(step, shared):
    wk, _ = _walk(TIER2 / f'{step}.cpr')
    first, copy = _part_events(wk)
    assert (copy.start, copy.offset, copy.shared) == (15360, 480, shared)
    assert (copy.part is first.part) is shared


def test_tier2_midi_track_channel():
    wk, _ = _walk(TIER2 / 'c17.cpr')
    assert list(_tracks(wk)) == ['Lead', 'MIDI 01']
    pe = _part_events(wk)[-1]
    events, _, _ = ci.decode_part_events(wk, pe.part)
    assert [(e.channel, e.data[0]) for e in events] == [(1, 60)]   # channel 2


def test_tier3_controllers_bends_program():
    wk, _ = _walk(TIER3 / 'c25.cpr')
    pe = _part_events(wk)[-1]
    events, problems, _ = ci.decode_part_events(wk, pe.part)
    assert problems == []
    first = {e.kind: e for e in reversed(events)}
    assert first['controller'].data == bytes([1, 10])          # CC1 = 10 at 0
    lsb, msb = first['pitchbend'].data
    assert (msb << 7 | lsb) - 8192 == -6084                     # as exported
    assert first['program'].data[0] == 31
    assert {e.channel for e in events} == {1}


@pytest.mark.parametrize('step, points', [
    ('c19', [(0, 120, False), (3840, 90, False)]),
    ('c20', [(0, 120, False), (3840, 120, False), (7699.23, 90, True)]),
])
def test_tier3_tempo_points(step, points):
    wk, _ = _walk(TIER3 / f'{step}.cpr')
    ev = next(o for o in wk.objects.values() if o.cls.name == 'MTempoTrackEvent')
    pts, fixed = ci.tempo_points(wk, ev)
    assert [(round(p.ticks, 2), round(p.bpm, 3), p.ramp) for p in pts] == points
    assert fixed == 120


def test_tier3_tempo_ramp_is_linear_in_beats():
    wk, _ = _walk(TIER3 / 'c20.cpr')
    ev = next(o for o in wk.objects.values() if o.cls.name == 'MTempoTrackEvent')
    pts, _ = ci.tempo_points(wk, ev)
    a, b = pts[1], pts[2]
    beats = (b.ticks - a.ticks) / 480
    seconds = 60 * beats / (a.bpm - b.bpm) * math.log(a.bpm / b.bpm)
    assert seconds == pytest.approx(b.seconds - a.seconds, abs=1e-6)


def test_tier3_signature_points():
    wk, _ = _walk(TIER3 / 'c21.cpr')
    ev = next(o for o in wk.objects.values() if o.cls.name == 'MSignatureTrackEvent')
    assert ci.signature_points(wk, ev) == [(0, 4, 4), (7680, 3, 4)]


@pytest.mark.parametrize('name, muted_parts, muted_tracks', [
    ('Ditty-04-Macbook', 52, []),
    ('GA & Padshop 2-(alt instr 2)-01', 0, ['Engaging Peace', 'Where Are We']),
    ('indy-001x', 2, []),
])
def test_realistic_mute_states_match_dawproject(name, muted_parts, muted_tracks):
    wk, _ = _walk(SETS / f'{name}.cpr')
    assert sum(pe.muted for pe in _part_events(wk)) == muted_parts
    assert [n for n, f in _tracks(wk).items() if f & ci.TRACK_MUTE] == muted_tracks


def test_tier3_markers():
    wk, _ = _walk(TIER3 / 'c23.cpr')
    got = [(m.name, m.start / 480, m.length / 480, m.is_range) for m in ci.markers(wk)]
    assert got == [('Intro', 0, 12, True),       # cycle marker bars 1-3 inclusive
                   ('Verse', 4, 0, False),       # bar 2
                   ('Chorus', 19, 0, False)]     # bar 6, after the 3/4 bar


def test_indy_range_markers_are_contiguous_sections():
    wk, _ = _walk(SETS / 'indy-001x.cpr')
    ms = ci.markers(wk)
    assert [m.name for m in ms] == ['INTRO', 'SECTION A', 'SECTION B', 'SECTION C', "SECTION B'", 'SECTION C']
    assert all(m.is_range and m.length == 32 * 480 for m in ms)
    assert all(a.start + a.length == b.start for a, b in zip(ms, ms[1:]))   # length, not end
    assert ms[0].start == 4 * 480 and ms[-1].start + ms[-1].length == 196 * 480


@pytest.mark.parametrize('path, offset', [
    (TIER1 / 'Cubase16/c02.cpr', 0),
    (TIER1 / 'Cubase16/c02-1.cpr', -1),
    (TIER1 / 'Cubase15/c02-1.cpr', -1),
    (SETS / 'Ditty-04-Macbook.cpr', -3),
    (SETS / 'GA & Padshop 2-(alt instr 2)-01.cpr', 0),
    (SETS / 'indy-001x.cpr', -1),
])
def test_display_bar_offset(path, offset):
    wk, _ = _walk(path)
    assert ci.display_bar_offset(wk) == offset


def _track_paths(wk):
    tes = sorted((o for o in wk.objects.values() if o.cls.name in ci.TRACK_EVENTS), key=lambda o: o.tag_at)
    out = {}
    for t in tes:
        parts = [o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent' and t.body_at <= o.tag_at < t.end]
        out[' / '.join(ci.folder_path(wk, t) + [ci.track_name(wk, t)])] = len(parts)
    return out


def test_tier2_folder_and_instrument_stack():
    wk, _ = _walk(TIER2 / 'c18.cpr')
    assert _track_paths(wk) == {'Folder 01 / Lead': 2, 'Folder 01 / MIDI 01': 1}
    # Stacking moves the parts onto the stack's own MIDI track, named after
    # the stack, as Cubase's MIDI export shows; the member track is empty.
    wk, _ = _walk(TIER2 / 'c18is.cpr')
    assert _track_paths(wk) == {'Instrument Stack 01 / Instrument Stack 01': 2,
                                'Instrument Stack 01 / Lead': 0, 'MIDI 01': 1}


def test_indy_matches_cubase_midi_export_in_reference_window():
    """Phase 2 go/no-go: indy's arrangement vs Cubase's own MIDI export.

    Same rules as the DAWproject comparison: part and track mute applied,
    notes cut at the visible part edge, explicit [3, 196) beat window rebased
    to zero, one-tick tolerance (Cubase stores fractional ticks and rounds on
    export). Expected residue, as for DAWproject: the two Texture Bed tails
    (clip-edge policy) and the 644 Pattern Editor drum notes (MPatternEvent).
    """
    import mido
    w0, w1 = 3 * 480, 196 * 480
    wk, _ = _walk(SETS / 'indy-001x.cpr')
    cpr = {}
    for te in (o for o in wk.objects.values() if o.cls.name in ci.TRACK_EVENTS):
        if ci.track_state_flags(wk, te) & ci.TRACK_MUTE:
            continue
        notes = []
        for o in (o for o in wk.objects.values() if o.cls.name == 'MMidiPartEvent' and te.body_at <= o.tag_at < te.end):
            pe = ci.part_event_info(wk, o)
            if pe.muted:
                continue
            events, problems, _ = ci.decode_part_events(wk, pe.part)
            assert problems == []
            hi = pe.start + pe.length
            for e in events:
                on = pe.start - pe.offset + e.position
                if e.status == 0x90 and pe.start <= on < hi and w0 <= on < w1:
                    notes.append((on - w0, e.data[0], e.data[1], min(on + e.length, hi, w1) - on))
        if notes:
            cpr[ci.track_name(wk, te)] = notes
    ref = {}
    mid = mido.MidiFile(str(SETS / 'indy-001x.mid'))
    for t in mid.tracks:
        name = next((m.name for m in t if m.type == 'track_name'), '?')
        tick, held, out = 0, {}, []
        for m in t:
            tick += m.time
            if m.type == 'note_on' and m.velocity:
                held.setdefault(m.note, []).append((tick, m.velocity))
            elif m.type in ('note_on', 'note_off') and held.get(m.note):
                s, v = held[m.note].pop(0)
                out.append((s, m.note, v, tick - s))
        if out:
            ref[name] = out
    assert set(ref) - set(cpr) == {'Drum Core', 'Drum Core ='}
    assert sum(len(ref[n]) for n in ('Drum Core', 'Drum Core =')) == 644
    shortened = []
    for name, notes in cpr.items():
        pool = sorted(ref[name])
        assert len(notes) == len(pool)
        for n in sorted(notes):
            match = next((r for r in pool if abs(r[0] - n[0]) <= 1 and r[1:3] == n[1:3]), None)
            assert match is not None, (name, n)
            pool.remove(match)
            if abs(match[3] - n[3]) > 1:
                shortened.append((name, n[0] / 480, match[3] - n[3]))
    assert sum(len(v) for v in cpr.values()) == 663
    assert shortened == [('Texture Bed', 105, 480), ('Texture Bed', 121, 480)]
