"""Regression evidence for the Cubase .cpr research inspector (phase 1).

tools/cpr_inspect.py is a research tool, not app code. These tests pin the
format findings recorded in docs/plans/cubase-import.md against the committed
fixtures, so later phases build on verified decoding.
"""
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
