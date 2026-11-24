"""Simplify controller data on export (docs/plans/0.5.0/simplify-controller-data.md)."""
import random
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from helpers import cc, conductor, note, smf, to_bytes, track
from test_ui_assembly import app, win  # noqa: F401
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.simplify import (CC_TOLERANCE, PITCH_BEND_TOLERANCE, SEQUENCE_CCS, simplify_midi,
                                            simplify_track, thin_points)


def trk(events):
    return track(events, 'T')


def msgs(t):
    return [(sum(m.time for m in list(t)[:i + 1]), m) for i, m in enumerate(t)]


def abs_events(t, typ):
    now, out = 0, []
    for m in t:
        now += m.time
        if m.type == typ:
            out.append((now, m))
    return out


def ccs(t, control=1, ch=0):
    return [(tick, m.value) for tick, m in abs_events(t, 'control_change') if m.control == control and m.channel == ch]


# ---------------------------------------------------------------- thinning

def interp_ok(points, kept, tol):
    kept_pts = [points[i] for i in kept]
    for (t0, v0), (t1, v1) in zip(kept_pts, kept_pts[1:]):
        for t, v in points:
            if t0 <= t <= t1:
                assert abs(v0 + (v1 - v0) * F(t - t0, t1 - t0) - v) <= tol


def test_ramp_collapses_to_ends():
    pts = [(i * 15, i) for i in range(100)]
    assert thin_points(pts, 1) == [0, 99]


def test_step_stays_a_step():
    pts = [(0, 0), (10, 0), (20, 0), (21, 100), (30, 100), (40, 100)]
    kept = thin_points(pts, 1)
    assert 2 in kept and 3 in kept and kept[0] == 0 and kept[-1] == 5


def test_short_streams_untouched():
    assert thin_points([], 1) == []
    assert thin_points([(0, 5)], 1) == [0]
    assert thin_points([(0, 5), (7, 90)], 1) == [0, 1]


@pytest.mark.parametrize('seed', range(40))
def test_tolerance_guarantee_on_random_curves(seed):
    rng = random.Random(seed)
    t, v, pts = 0, 64, []
    for _ in range(rng.randint(3, 300)):
        t += rng.randint(1, 30)
        v = max(0, min(127, v + rng.randint(-4, 4) * rng.choice([0, 1, 1, 8])))
        pts.append((t, v))
    clean = pts
    kept = thin_points(clean, 1)
    assert kept[0] == 0 and kept[-1] == len(clean) - 1 and kept == sorted(set(kept))
    interp_ok(clean, kept, 1)
    assert len(kept) <= len(clean)


# ---------------------------------------------------------------- track pass

def test_same_tick_later_wins_and_trailing_repeats_dropped():
    t = trk([(0, cc(0, 1, 10)), (10, cc(0, 1, 10)), (20, cc(0, 1, 90)), (20, cc(0, 1, 10)), (30, cc(0, 1, 10)),
             (40, cc(0, 1, 90)), (50, cc(0, 1, 90)), (60, cc(0, 1, 90))])
    out = simplify_track(t)
    # 10 holds to its last repeat (a corner), then the step; the trailing 90s collapse to the first
    assert ccs(out) == [(0, 10), (30, 10), (40, 90)]


def test_hold_then_ramp_is_not_turned_into_a_ramp():
    t = trk([(0, cc(0, 1, 0)), (10, cc(0, 1, 50)), (20, cc(0, 1, 50)), (30, cc(0, 1, 100))])
    assert ccs(simplify_track(t)) == [(0, 0), (10, 50), (20, 50), (30, 100)]


def test_flat_run_collapses_to_its_ends():
    t = trk([(i * 10, cc(0, 1, 64)) for i in range(20)] + [(200, cc(0, 1, 0)), (210, cc(0, 1, 127))])
    assert ccs(simplify_track(t)) == [(0, 64), (190, 64), (200, 0), (210, 127)]


def test_dense_curve_thinned_and_notes_untouched():
    events = [(i * 15, cc(0, 1, i // 4)) for i in range(0, 400)]
    events += note(0, 60, 0, 1000) + [(5, mido.Message('program_change', channel=0, program=3))]
    out = simplify_track(trk(events))
    assert len(ccs(out)) < 10
    assert [m for _t, m in abs_events(out, 'note_on')] and [m for _t, m in abs_events(out, 'note_off')]
    assert len(abs_events(out, 'program_change')) == 1
    # untouched events keep their absolute ticks
    assert [t for t, _ in abs_events(out, 'note_off')] == [1000]
    # end of track unchanged
    assert sum(m.time for m in out) == sum(m.time for m in trk(events))
    interp_ok_cc = [(i * 15, i // 4) for i in range(400)]
    kept_ticks = dict(ccs(out))
    ks = sorted(kept_ticks)
    for (t0, v0), (t1, v1) in zip([(k, kept_ticks[k]) for k in ks], [(k, kept_ticks[k]) for k in ks[1:]]):
        for t, v in interp_ok_cc:
            if t0 <= t <= t1:
                assert abs(v0 + (v1 - v0) * F(t - t0, t1 - t0) - v) <= CC_TOLERANCE


def test_idempotent():
    events = [(i * 7, cc(0, 1, (i * 3) % 50)) for i in range(300)]
    once = simplify_track(trk(events))
    assert [(m.time, m.dict()) for m in simplify_track(once)] == [(m.time, m.dict()) for m in once]


def test_streams_are_independent():
    events = []
    for i in range(50):
        events += [(i * 10, cc(0, 1, i)), (i * 10, cc(0, 2, 50 - i)), (i * 10, cc(1, 1, 5))]
    out = simplify_track(trk(events))
    assert ccs(out, 1, 0) == [(0, 0), (490, 49)]
    assert ccs(out, 2, 0) == [(0, 50), (490, 1)]
    assert ccs(out, 1, 1) == [(0, 5)]


def test_never_touched_controllers_keep_repeats_and_order():
    events = []
    for control in sorted(SEQUENCE_CCS) + [120, 123, 127]:
        events += [(i * 10, cc(0, control, 7)) for i in range(5)]
    out = simplify_track(trk(events))
    assert [m.dict() for _t, m in abs_events(out, 'control_change')] == \
           [m.dict() for _t, m in abs_events(trk(events), 'control_change')]


def test_non_continuous_messages_untouched():
    events = [(0, mido.Message('program_change', channel=0, program=5)),
              (0, mido.Message('program_change', channel=0, program=5)),
              (10, mido.Message('sysex', data=(1, 2, 3))),
              (10, mido.Message('sysex', data=(1, 2, 3))),
              (20, mido.MetaMessage('lyrics', text='a')), (20, mido.MetaMessage('lyrics', text='a'))]
    assert [(m.time, m.dict()) for m in simplify_track(trk(events))] == [(m.time, m.dict()) for m in trk(events)]


def test_pitch_bend_uses_its_own_tolerance_and_aftertouch_streams():
    bend = [(i * 10, mido.Message('pitchwheel', channel=0, pitch=i * 60)) for i in range(100)]
    bend_small = [(i * 10, mido.Message('pitchwheel', channel=1, pitch=i * 3)) for i in range(100)]
    chan = [(i * 10, mido.Message('aftertouch', channel=0, value=i)) for i in range(100)]
    poly = [(i * 10, mido.Message('polytouch', channel=0, note=n, value=i)) for i in range(100) for n in (60, 61)]
    out = simplify_track(trk(bend + bend_small + chan + poly))
    assert [m.pitch for _t, m in abs_events(out, 'pitchwheel') if m.channel == 0] == [0, 5940]
    # a pitch-bend ramp far inside 128 collapses; the same shape in CC would not need tolerance 128
    assert len([1 for _t, m in abs_events(out, 'pitchwheel') if m.channel == 1]) == 2
    assert len(abs_events(out, 'aftertouch')) == 2
    for n in (60, 61):
        assert len([1 for _t, m in abs_events(out, 'polytouch') if m.note == n]) == 2
    # a bend step bigger than the tolerance survives
    step = trk([(0, mido.Message('pitchwheel', pitch=0)), (10, mido.Message('pitchwheel', pitch=0)),
                (20, mido.Message('pitchwheel', pitch=PITCH_BEND_TOLERANCE * 4)),
                (30, mido.Message('pitchwheel', pitch=PITCH_BEND_TOLERANCE * 4))])
    assert [m.pitch for _t, m in abs_events(simplify_track(step), 'pitchwheel')] == [0, 0, 512]


# ---------------------------------------------------------------- export

def build_ws():
    from midi_interchange.ui.controller import Controller
    from midi_interchange.interchange.payload import Payload
    c = Controller()
    events = [(i * 15, cc(0, 1, min(127, i // 4))) for i in range(0, 600)]
    events += [(0, mido.Message('program_change', channel=0, program=4))] + note(0, 60, 0, 2 * 480)
    events += [(i * 15, mido.Message('pitchwheel', channel=0, pitch=i * 10)) for i in range(0, 300)]
    c.import_payloads([Payload('a.mid', smf([conductor(480), trk(events)]))])
    return c


@pytest.mark.parametrize('mode', list(ExportMode))
@pytest.mark.parametrize('with_range', [False, True])
def test_off_is_byte_identical_and_on_thins(app, mode, with_range):
    c = build_ws()
    if with_range:
        c.add_range(F(1), F(4))
    base = build_exports(c.ws, ExportOptions(mode=mode))
    off = build_exports(c.ws, ExportOptions(mode=mode, simplify_controllers=False))
    assert [to_bytes(r.midi) for r in base] == [to_bytes(r.midi) for r in off]
    on = build_exports(c.ws, ExportOptions(mode=mode, simplify_controllers=True))
    assert [r.label for r in on] == [r.label for r in base]

    def count(res, typ):
        return sum(1 for r in res for tr in r.midi.tracks for m in tr if m.type == typ)
    assert count(on, 'control_change') < count(base, 'control_change')
    assert count(on, 'pitchwheel') < count(base, 'pitchwheel')
    for typ in ('note_on', 'note_off', 'program_change', 'set_tempo', 'track_name', 'end_of_track'):
        assert count(on, typ) == count(base, typ)
    # notes keep their ticks
    def note_ticks(res):
        out = []
        for r in res:
            for tr in r.midi.tracks:
                now = 0
                for m in tr:
                    now += m.time
                    if m.type in ('note_on', 'note_off'):
                        out.append((now, m.type, m.note))
        return out
    assert note_ticks(on) == note_ticks(base)


def test_range_state_carry_survives(app):
    c = build_ws()
    c.add_range(F(2), F(4))
    on = build_exports(c.ws, ExportOptions(mode=ExportMode.REBASE, simplify_controllers=True))
    first = [m for tr in on[0].midi.tracks for m in tr if m.type == 'control_change'][0]
    assert first.control == 1 and first.value > 0          # the carried start value is the first point


def test_channel_override_merges_into_one_stream(app):
    from midi_interchange.ui.controller import Controller
    from midi_interchange.interchange.payload import Payload
    c = Controller()
    events = [(i * 10, cc(0, 1, i)) for i in range(60)] + [(i * 10, cc(3, 1, i)) for i in range(60)]
    c.import_payloads([Payload('a.mid', smf([conductor(480), trk(events)]))])
    t = c.ws.tracks[0]
    c.set_export_channel(t.id, 5)
    on = build_exports(c.ws, ExportOptions(simplify_controllers=True))[0].midi
    out = [(tick, m.value) for tr in on.tracks for tick, m in abs_events(tr, 'control_change')]
    # both channels now share one stream: the same-tick later event wins, and the ramp collapses
    assert [m.channel for tr in on.tracks for _t, m in abs_events(tr, 'control_change')] == [4, 4]
    assert out == [(0, 0), (590, 59)]


def test_simplify_midi_keeps_structure():
    mf = mido.MidiFile(type=1, ticks_per_beat=96)
    mf.tracks.append(trk([(i, cc(0, 1, i % 3)) for i in range(0, 50)]))
    mf.tracks.append(conductor(96))
    out = simplify_midi(mf)
    assert (out.type, out.ticks_per_beat, len(out.tracks)) == (1, 96, 2)
    assert [m.dict() for m in out.tracks[1]] == [m.dict() for m in mf.tracks[1]]
    assert len(mf.tracks[0]) == 52                      # input not modified


# ---------------------------------------------------------------- controller, panel, drag

def test_controller_and_panel(win):
    w = win
    c = w.ctl
    assert c.simplify_controllers is False and not w.export_panel.simplify_cb.isChecked()
    assert c.export_options().simplify_controllers is False
    w.export_panel.simplify_cb.setChecked(True)
    assert c.simplify_controllers is True and c.export_options().simplify_controllers is True
    c.set_simplify_controllers(False)
    assert not w.export_panel.simplify_cb.isChecked()
    assert 'Changes the data' in w.export_panel.simplify_cb.toolTip()


def test_save_and_drag_give_the_same_bytes(win, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QFileDialog
    from midi_interchange.interchange import drag_export
    from midi_interchange.interchange.payload import Payload
    from midi_interchange.ui.export_panel import start_file_drag
    w = win
    c = w.ctl
    c.new_document()
    events = [(i * 15, cc(0, 1, min(127, i // 4))) for i in range(0, 600)] + note(0, 60, 0, 960)
    c.import_payloads([Payload('a.mid', smf([conductor(480), trk(events)]))])
    c.set_simplify_controllers(True)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'saved.mid'), ''))
    w.save_midi()
    monkeypatch.setattr(drag_export, '_DIR', str(tmp_path / 'drag'))
    dragged = []
    monkeypatch.setattr(QDrag, 'exec',
                        lambda self, *a: dragged.extend(u.toLocalFile() for u in self.mimeData().urls()) or Qt.CopyAction)
    start_file_drag(w.export_panel, c, None, pytest.fail, lambda paths: None)
    saved = (tmp_path / 'saved.mid').read_bytes()
    assert dragged and all(Path(p).read_bytes() == saved for p in dragged)
    assert len(ccs(mido.MidiFile(str(tmp_path / 'saved.mid')).tracks[1])) < 10


# ---------------------------------------------------------------- real data

REASON = Path(__file__).resolve().parent.parent / 'samples' / 'reason-check'


def test_real_reason_export_thins_and_stays_within_tolerance():
    files = sorted(REASON.glob('*.mid'))
    if not files:
        pytest.skip('no Reason fixtures')
    best = None
    for f in files:
        mf = mido.MidiFile(str(f))
        n = sum(1 for tr in mf.tracks for m in tr if m.type in ('control_change', 'pitchwheel'))
        if best is None or n > best[0]:
            best = (n, mf)
    mf = best[1]
    out = simplify_midi(mf)

    def total(m):
        return sum(1 for tr in m.tracks for x in tr if x.type in ('control_change', 'pitchwheel'))
    assert total(out) < total(mf)
    for src, new in zip(mf.tracks, out.tracks):
        assert sum(m.time for m in src) == sum(m.time for m in new)
        assert note_ticks(src) == note_ticks(new)
        within_tolerance(src, new)


def note_ticks(t):
    return [(tick, m.dict() | {'time': 0}) for tick, m in msgs(t) if m.type in ('note_on', 'note_off')]


def within_tolerance(src, new):
    """Every original point is within tolerance of the line the new stream draws."""
    from midi_interchange.core.simplify import _stream

    def streams(t):
        out = {}
        for tick, m in msgs(t):
            if not m.is_meta and (s := _stream(m)) is not None:
                out.setdefault(s[0], {})[tick] = (s[1], s[2])      # last event on a tick wins
        return out
    before, after = streams(src), streams(new)
    for key, points in before.items():
        kept = sorted((t, v) for t, (v, _tol) in after[key].items())
        tol = next(iter(points.values()))[1]
        for t, (v, _tol) in points.items():
            lo = max((p for p in kept if p[0] <= t), default=None)
            hi = min((p for p in kept if p[0] >= t), default=None)
            if lo is None or hi is None:
                continue
            want = lo[1] if hi[0] == lo[0] else lo[1] + (hi[1] - lo[1]) * F(t - lo[0], hi[0] - lo[0])
            assert abs(want - v) <= tol
