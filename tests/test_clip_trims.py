"""Clip edge trims: limits, the export edge rules, and what travels with a trimmed clip.

A clip keeps its full extent; trims only choose what shows and exports. The
cutting rules are the range edge rules (export_smf), so these tests check the
same behaviour through trims, and through ranges on trimmed clips.

Workspace: one track "Lead" (channel 0), 8 beats long:
  program 5 and CC7=90 at beat 0, pitch bend at beat 1, lyric "a" at beat 1 and "b" at beat 6,
  notes: 60 over beats 0-3, 62 over 3-4, 64 over 5-7, 65 over 7-8.
"""
from __future__ import annotations

from fractions import Fraction as F

import mido
import pytest

from helpers import conductor, load, note, notes_of, reparse, smf, track, track_by_name

from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports, visible_msgs
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.placement import Placement, place_imports

PPQ = 480


def b(x) -> int:
    return int(F(x) * PPQ)


def lead_bytes(name="Lead", ch=0, length=8) -> bytes:
    ev = [
        (0, mido.Message("program_change", channel=ch, program=5)),
        (0, mido.Message("control_change", channel=ch, control=7, value=90)),
        (b(1), mido.Message("pitchwheel", channel=ch, pitch=1000)),
        (b(1), mido.MetaMessage("lyrics", text="a")),
        (b(6), mido.MetaMessage("lyrics", text="b")),
    ]
    for start, dur, pitch in ((0, 3, 60), (3, 1, 62), (5, 2, 64), (7, 1, 65)):
        ev += note(ch, pitch, b(start), b(dur))
    return smf([conductor(PPQ), track(ev, name=name)])


@pytest.fixture
def ws():
    return load(lead_bytes())


def clip_of(ws):
    return ws.tracks[0].clips[0]


def export(ws, **kw):
    out = reparse(build_exports(ws, ExportOptions(**kw))[0].midi)
    return out, track_by_name(out, "Lead")


def played(ws, **kw):
    out, t = export(ws, **kw)
    return [(s, e, p) for s, e, _c, p in notes_of(t, out.ticks_per_beat)]


def msgs(trk, kind):
    return [m for m in trk if m.type == kind]


def abs_times(trk, ppq, kind):
    out, tick = [], 0
    for m in trk:
        tick += m.time
        if m.type == kind:
            out.append((F(tick, ppq), m))
    return out


# -- model: limits -----------------------------------------------------------------
def test_untrimmed_by_default(ws):
    c = clip_of(ws)
    assert not c.is_trimmed and (c.start, c.end) == (0, 8)


def test_trim_moves_visible_edges_only(ws):
    c = clip_of(ws)
    assert ws.trim_clip(c.id, "start", F(2)) and ws.trim_clip(c.id, "end", F(6))
    assert c.is_trimmed and (c.start, c.end) == (2, 6)
    assert (c.offset, c.length, c.trim_start, c.trim_end) == (0, 8, 2, 6)


def test_edges_stop_at_original_extent(ws):
    c = clip_of(ws)
    ws.trim_clip(c.id, "start", F(-5))
    ws.trim_clip(c.id, "end", F(99))
    assert (c.trim_start, c.trim_end) == (0, 8) and not c.is_trimmed
    ws.trim_clip(c.id, "start", F(99))
    assert c.trim_start == c.trim_end - F(1, PPQ)          # also can't pass the other edge
    ws.restore_clip(c.id)
    ws.trim_clip(c.id, "end", F(-3))
    assert c.trim_end == F(1, PPQ)


def test_original_extent_off_grid_is_the_limit():
    ws = load(lead_bytes())
    c = clip_of(ws)
    c.offset = F(1, 3)                                     # an off-grid position
    ws.trim_clip(c.id, "start", F(0))                      # past the original start
    assert c.trim_start == 0 and c.start == F(1, 3)


def test_minimum_length_and_edges_cannot_cross(ws):
    c = clip_of(ws)
    ws.trim_clip(c.id, "start", F(4), min_length=F(1))
    ws.trim_clip(c.id, "end", F(5), min_length=F(1))
    assert (c.start, c.end) == (4, 5)
    assert not ws.trim_clip(c.id, "end", F(4), min_length=F(1))      # would cross
    ws.trim_clip(c.id, "start", F(5), min_length=F(1))
    assert (c.start, c.end) == (4, 5)
    ws.trim_clip(c.id, "end", F(0), min_length=F(1))
    assert (c.start, c.end) == (4, 5)


def test_restore_full_clip(ws):
    c = clip_of(ws)
    assert not ws.restore_clip(c.id)                       # nothing to restore
    ws.trim_clip(c.id, "start", F(2))
    ws.trim_clip(c.id, "end", F(6))
    assert ws.restore_clip(c.id) and (c.start, c.end) == (0, 8) and not c.is_trimmed


def test_can_trim_move_matches_the_clamps(ws):
    c = clip_of(ws)
    assert not ws.can_trim_move(c.id, "end", 1) and ws.can_trim_move(c.id, "end", -1)
    assert not ws.can_trim_move(c.id, "start", -1) and ws.can_trim_move(c.id, "start", 1)
    ws.trim_clip(c.id, "end", F(5), min_length=F(1))
    ws.trim_clip(c.id, "start", F(4), min_length=F(1))
    assert ws.can_trim_move(c.id, "end", 1) and ws.can_trim_move(c.id, "start", -1)
    assert not ws.can_trim_move(c.id, "end", -1, F(1)) and not ws.can_trim_move(c.id, "start", 1, F(1))


# -- export: left edge --------------------------------------------------------------
def test_note_across_left_edge_sounds_from_the_edge(ws):
    ws.trim_clip(clip_of(ws).id, "start", F(2))
    assert played(ws) == [(2, 3, 60), (3, 4, 62), (5, 7, 64), (7, 8, 65)]


def test_note_across_left_edge_dropped_without_partial_notes(ws):
    ws.trim_clip(clip_of(ws).id, "start", F(2))
    assert played(ws, partial_notes=False) == [(3, 4, 62), (5, 7, 64), (7, 8, 65)]


def test_settings_are_carried_to_the_left_edge(ws):
    ws.trim_clip(clip_of(ws).id, "start", F(2))
    out, t = export(ws)
    ppq = out.ticks_per_beat
    pc = abs_times(t, ppq, "program_change")
    cc7 = abs_times(t, ppq, "control_change")
    pw = abs_times(t, ppq, "pitchwheel")
    assert [(at, m.program) for at, m in pc] == [(2, 5)]
    assert [(at, m.value) for at, m in cc7] == [(2, 90)]
    assert [(at, m.pitch) for at, m in pw] == [(2, 1000)]
    assert [m.text for _, m in abs_times(t, ppq, "lyrics")] == ["b"]      # "a" was trimmed away


# -- export: right edge -------------------------------------------------------------
def test_note_across_right_edge_is_released(ws):
    ws.trim_clip(clip_of(ws).id, "end", F(2))
    out, t = export(ws)
    assert played(ws) == [(0, 2, 60)]                       # no stuck notes; later notes gone
    assert [m.text for _, m in abs_times(t, out.ticks_per_beat, "lyrics")] == ["a"]
    assert F(sum(m.time for m in t), out.ticks_per_beat) == 2      # the track ends at the trim


def test_untrimmed_whole_export_is_unchanged(ws):
    _out, t = export(ws)
    original = mido.MidiFile(file=__import__("io").BytesIO(lead_bytes())).tracks[1]
    assert [m for m in t] == [m for m in original]


def test_both_edges(ws):
    c = clip_of(ws)
    ws.trim_clip(c.id, "start", F(2))
    ws.trim_clip(c.id, "end", F(5, 2) + 1)                  # 3.5
    assert played(ws) == [(2, 3, 60), (3, F(7, 2), 62)]


# -- export modes --------------------------------------------------------------------
def test_ranges_apply_clip_trims(ws):
    c = clip_of(ws)
    ws.trim_clip(c.id, "start", F(2))
    from midi_interchange.core.ranges import Range
    ws.ranges = [Range(id="r", start=F(1), end=F(6))]
    # preserve: absolute positions; the window is the range within the trims
    assert played(ws, mode=ExportMode.PRESERVE) == [(2, 3, 60), (3, 4, 62), (5, 6, 64)]
    # rebase: the range starts at zero, so everything moves 1 beat earlier
    assert played(ws, mode=ExportMode.REBASE) == [(1, 2, 60), (2, 3, 62), (4, 5, 64)]
    out, t = export(ws, mode=ExportMode.REBASE)
    assert [(at, m.program) for at, m in abs_times(t, out.ticks_per_beat, "program_change")] == [(1, 5)]
    # separate: one rebased file for the range
    res = build_exports(ws, ExportOptions(mode=ExportMode.SEPARATE))
    assert len(res) == 1
    rt = track_by_name(reparse(res[0].midi), "Lead")
    assert [(s, e, p) for s, e, _c, p in notes_of(rt, PPQ)] == [(1, 2, 60), (2, 3, 62), (4, 5, 64)]


def test_range_wholly_outside_the_trims_is_silent(ws):
    from midi_interchange.core.ranges import Range
    ws.trim_clip(clip_of(ws).id, "start", F(6))
    ws.ranges = [Range(id="r", start=F(0), end=F(4))]
    assert played(ws, mode=ExportMode.PRESERVE) == []


def test_trim_silence_measures_inside_the_trims(ws):
    c = clip_of(ws)
    ws.trim_clip(c.id, "start", F(7, 2))                    # 3.5: note 62 (3-4) still sounds
    ws.trim_clip(c.id, "end", F(6))
    assert played(ws, trim=True) == [(0, F(1, 2), 62), (F(3, 2), F(5, 2), 64)]
    ws.restore_clip(c.id)
    assert played(ws, trim=True)[0] == (0, 3, 60)


def test_content_bounds_respect_trims(ws):
    from midi_interchange.core.export_smf import content_bounds
    c = clip_of(ws)
    assert content_bounds(ws.tracks, F(0), None) == (0, 8)
    ws.trim_clip(c.id, "start", F(4))
    ws.trim_clip(c.id, "end", F(6))
    assert content_bounds(ws.tracks, F(0), None) == (5, 6)


# -- badges and counts -----------------------------------------------------------------
def test_channels_and_counts_use_the_trims():
    data = smf([conductor(PPQ), track(note(0, 60, 0, b(2)) + note(3, 70, b(4), b(2)), name="Two")])
    ws = load(data)
    t = ws.tracks[0]
    assert t.channels == (0, 3)
    ws.trim_clip(t.clips[0].id, "start", F(3))
    assert t.channels == (3,)
    assert sum(1 for m in visible_msgs(t.clips[0]) if m.type == "note_on") == 1
    ws.restore_clip(t.clips[0].id)
    assert t.channels == (0, 3)


# -- what travels with a trimmed clip ---------------------------------------------------
def trimmed_ws():
    ws = load(lead_bytes())
    ws.trim_clip(clip_of(ws).id, "start", F(2))
    ws.trim_clip(clip_of(ws).id, "end", F(6))
    return ws


def test_move_keeps_trim_and_positions_the_visible_start():
    ws = trimmed_ws()
    c = clip_of(ws)
    ws.move_clip_to_track(c.id, ws.tracks[0].id, F(10))
    assert (c.start, c.end) == (10, 14) and (c.trim_start, c.trim_end) == (2, 6)
    assert c.offset == 8


def test_duplicate_keeps_trim_and_goes_after_the_visible_end():
    ws = trimmed_ws()
    c = clip_of(ws)
    dup = ws.duplicate_clip(c.id)
    assert (dup.start, dup.end) == (6, 10) and (dup.trim_start, dup.trim_end) == (2, 6)
    assert [x.id for x in ws.tracks[0].clips] == [c.id, dup.id]


def test_butt_uses_visible_edges():
    ws = trimmed_ws()
    first = clip_of(ws)
    ws.add_import(*import_smf_bytes(lead_bytes(name="Other"), "o.mid"))
    second = ws.tracks[1].clips[0]
    ws.move_clip_to_track(second.id, ws.tracks[0].id, F(20))
    ws.trim_clip(second.id, "start", F(21))
    assert second.start == 21 and second.offset == 20
    assert ws.snap_clip_to_previous(second.id)
    assert second.start == first.end == 6
    assert second.offset == 5


def test_merge_tracks_keeps_trim():
    ws = trimmed_ws()
    ws.add_import(*import_smf_bytes(lead_bytes(name="Other"), "o.mid"))
    ws.merge_tracks(ws.tracks[0].id, ws.tracks[1].id)
    assert len(ws.tracks) == 1
    trimmed = [c for c in ws.tracks[0].clips if c.is_trimmed]
    assert len(trimmed) == 1 and (trimmed[0].start, trimmed[0].end) == (2, 6)


def test_undo_and_restore_through_the_controller():
    from midi_interchange.ui.controller import Controller
    from midi_interchange.interchange.payload import Payload
    ctl = Controller()
    ctl.import_payloads([Payload("l.mid", lead_bytes())])
    c = clip_of(ctl.ws)
    ctl.snap = None
    ctl.checkpoint()                                         # as at the start of a drag
    ctl.trim_clip_live(c.id, "start", F(2))
    ctl.trim_clip_live(c.id, "start", F(3))
    assert c.trim_start == 3
    ctl.undo()                                               # one undo reverses the whole drag
    assert not clip_of(ctl.ws).is_trimmed
    ctl.redo()
    c = clip_of(ctl.ws)
    assert c.trim_start == 3
    ctl.restore_clip(c.id)
    assert not clip_of(ctl.ws).is_trimmed
    ctl.undo()
    assert clip_of(ctl.ws).trim_start == 3


def test_controller_trim_snaps_and_shift_bypasses():
    from midi_interchange.ui.controller import Controller
    from midi_interchange.interchange.payload import Payload
    ctl = Controller()
    ctl.import_payloads([Payload("l.mid", lead_bytes())])
    c = clip_of(ctl.ws)                                      # snap: beat
    ctl.trim_clip_live(c.id, "start", F(21, 10))
    assert c.trim_start == 2
    ctl.trim_clip_live(c.id, "start", F(21, 10), bypass_snap=True)
    assert c.trim_start == F(21, 10)
    ctl.trim_clip_live(c.id, "end", F(5, 2))                 # snaps to beat 3, but a beat is the minimum length
    assert c.trim_end == F(31, 10)                           # from the (off-grid) start at 2.1
    ctl.trim_clip_live(c.id, "end", F(5, 2), bypass_snap=True)
    assert c.trim_end == F(5, 2)                             # Shift: only one tick is the minimum
    ctl.trim_clip_live(c.id, "end", F(2), bypass_snap=True)
    assert c.trim_end == c.trim_start + F(1, PPQ)


# -- replace on drop ------------------------------------------------------------------------
def short_part() -> bytes:
    return smf([conductor(PPQ), track(note(0, 60, 0, b(4)), name="Lead")])


def test_replace_on_drop_compares_visible_edges_by_default():
    ws = load(lead_bytes())
    c = clip_of(ws)
    ws.trim_clip(c.id, "end", F(4))                          # visible 0-4, full 0-8
    target = ws.tracks[0].id
    _, stats = place_imports(ws, [import_smf_bytes(short_part(), "s.mid")], Placement(F(0), target))
    assert stats["replaced"] == 1 and len(ws.tracks[0].clips) == 1
    assert not clip_of(ws).is_trimmed


def test_replace_on_drop_can_compare_full_extents():
    ws = load(lead_bytes())
    c = clip_of(ws)
    ws.trim_clip(c.id, "end", F(4))
    target = ws.tracks[0].id
    _, stats = place_imports(ws, [import_smf_bytes(short_part(), "s.mid")],
                             Placement(F(0), target, compare_full_extent=True))
    assert stats["replaced"] == 0 and len(ws.tracks[0].clips) == 2
    # ... and the full extents do match a full-length drop
    ws2 = trimmed_ws()
    _, stats = place_imports(ws2, [import_smf_bytes(lead_bytes(), "l.mid")],
                             Placement(F(0), ws2.tracks[0].id, compare_full_extent=True))
    assert stats["replaced"] == 1
    ws3 = trimmed_ws()
    _, stats = place_imports(ws3, [import_smf_bytes(lead_bytes(), "l.mid")], Placement(F(0), ws3.tracks[0].id))
    assert stats["replaced"] == 0                            # visible edges (2-6) differ from 0-8


# -- timeline gestures ------------------------------------------------------------------------
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_interchange.interchange.payload import Payload  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    from midi_interchange.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    QTest.qWaitForWindowExposed(w)
    w.ctl.import_payloads([Payload("l.mid", lead_bytes())])
    # a second clip further along keeps the first one off the very edge of the view
    QApplication.processEvents()
    w.timeline.set_zoom(20.0, 0)
    w.timeline.horizontalScrollBar().setValue(0)
    w.timeline.verticalScrollBar().setValue(0)
    yield w
    w.close()


def gesture(tl, p0, p1, mods):
    vp = tl.viewport()
    QTest.mousePress(vp, Qt.LeftButton, mods, p0)
    for i in range(1, 7):
        QTest.mouseMove(vp, p0 + (p1 - p0) * i / 6)
    QTest.mouseRelease(vp, Qt.LeftButton, mods, p1)
    QApplication.processEvents()


def test_option_drag_trims_a_clip_edge(win):
    tl, ctl = win.timeline, win.ctl
    c = clip_of(ctl.ws)
    y = tl.header_h() + tl.lane_h // 2
    # right edge: 8 -> 6 (beat snap)
    gesture(tl, QPoint(int(tl.x_of(8)) - 2, y), QPoint(int(tl.x_of(6.2)), y), Qt.AltModifier)
    assert (c.start, c.end) == (0, 6) and not ctl.ws.ranges
    # left edge: 0 -> 2
    gesture(tl, QPoint(int(tl.x_of(0)) + 2, y), QPoint(int(tl.x_of(1.9)), y), Qt.AltModifier)
    assert (c.start, c.end) == (2, 6)
    # beyond the original extent is refused
    gesture(tl, QPoint(int(tl.x_of(6)) + 1, y), QPoint(int(tl.x_of(30)), y), Qt.AltModifier)
    assert c.end == 8
    # one undo reverses the whole (last) drag
    ctl.undo()
    assert clip_of(ctl.ws).trim_end == 6


def test_shift_bypasses_snap_when_trimming(win):
    tl, ctl = win.timeline, win.ctl
    c = clip_of(ctl.ws)
    y = tl.header_h() + tl.lane_h // 2
    mods = Qt.AltModifier | Qt.ShiftModifier
    vp = tl.viewport()
    QTest.mousePress(vp, Qt.LeftButton, mods, QPoint(int(tl.x_of(8)) - 2, y))
    tl._drag_to(tl.x_of(6.3), True, y)                      # Shift held: no snap
    QTest.mouseRelease(vp, Qt.LeftButton, mods, QPoint(int(tl.x_of(6.3)), y))
    assert c.end == F(63, 10)


def test_plain_drag_on_a_clip_edge_still_makes_a_range(win):
    tl, ctl = win.timeline, win.ctl
    y = tl.header_h() + tl.lane_h // 2
    gesture(tl, QPoint(int(tl.x_of(8)) - 2, y), QPoint(int(tl.x_of(4)), y), Qt.NoModifier)
    assert len(ctl.ws.ranges) == 1 and not clip_of(ctl.ws).is_trimmed


def test_option_cursor_is_horizontal_resize_over_an_edge(win):
    tl = win.timeline
    y = tl.header_h() + tl.lane_h // 2
    tl._update_cursor(QPoint(int(tl.x_of(8)) - 2, y), Qt.AltModifier)
    assert tl.viewport().cursor().shape() == Qt.SizeHorCursor
    tl._update_cursor(QPoint(int(tl.x_of(4)), y), Qt.AltModifier)           # the middle: move
    assert tl.viewport().cursor().shape() == Qt.SizeAllCursor
    tl._update_cursor(QPoint(int(tl.x_of(8)) - 2, y), Qt.NoModifier)
    assert tl.viewport().cursor().shape() != Qt.SizeHorCursor


def test_range_edge_wins_for_plain_drag_and_clip_edge_for_option(win):
    tl, ctl = win.timeline, win.ctl
    r = ctl.add_range(F(2), F(8))                             # its end sits on the clip's end
    y = tl.header_h() + tl.lane_h // 2
    pos = QPoint(int(tl.x_of(8)) - 1, y)
    assert tl._hit(pos, Qt.NoModifier)[0] == "edge"
    assert tl._hit(pos, Qt.AltModifier)[0] == "clip_edge"
    assert r


def test_narrow_clip_can_only_be_moved(win):
    tl, ctl = win.timeline, win.ctl
    c = clip_of(ctl.ws)
    tl.set_zoom(1.5, 0)                                       # 8 beats = 12 px, under two grab zones + margin
    ctl.trim_clip_live(c.id, "end", F(2), bypass_snap=True)   # 2 beats = 3 px
    tl.horizontalScrollBar().setValue(0)
    QApplication.processEvents()
    y = tl.header_h() + tl.lane_h // 2
    mid = QPoint(int(tl.x_of(1)), y)
    assert tl._hit(mid, Qt.AltModifier)[0] == "clip"
    before = c.end - c.start
    gesture(tl, mid, QPoint(mid.x() + 12, y), Qt.AltModifier)
    assert c.start > 0 and c.end - c.start == before and c.trim_end == 2


def test_trim_autoscroll_stops_when_the_edge_is_pinned(win):
    tl, ctl = win.timeline, win.ctl
    y = tl.header_h() + tl.lane_h // 2
    hbar, w = tl.horizontalScrollBar(), tl.viewport().width()
    p = QPoint(int(tl.x_of(8)) - 2, y)
    QTest.mousePress(tl.viewport(), Qt.LeftButton, Qt.AltModifier, p)
    assert tl._drag["kind"] == "trim"
    before = hbar.value()
    tl._autoscroll_step(w - 5, y, False)                    # the end is at the clip's original end
    assert hbar.value() == before and not tl._autoscroll.isActive()
    QTest.mouseRelease(tl.viewport(), Qt.LeftButton, Qt.AltModifier, p)


def test_trim_autoscroll_continues_while_the_limit_is_off_screen(win):
    tl, ctl = win.timeline, win.ctl
    c = clip_of(ctl.ws)
    ctl.trim_clip_live(c.id, "end", F(2))
    tl.set_zoom(200.0, 0)
    tl.horizontalScrollBar().setValue(0)
    QApplication.processEvents()
    y = tl.header_h() + tl.lane_h // 2
    hbar, w = tl.horizontalScrollBar(), tl.viewport().width()
    p = QPoint(int(tl.x_of(2)) - 2, y)
    QTest.mousePress(tl.viewport(), Qt.LeftButton, Qt.AltModifier, p)
    assert tl._drag["kind"] == "trim"
    tl._autoscroll_step(w - 5, y, False)                    # the original end (beat 8) is off screen
    assert hbar.value() > 0
    assert c.trim_end > 2                                    # and the edge followed the pointer
    QTest.mouseRelease(tl.viewport(), Qt.LeftButton, Qt.AltModifier, p)
