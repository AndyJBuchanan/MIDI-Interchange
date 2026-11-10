"""Headless GUI tests for clip assembly: drop targeting, cross-track clip drags, New."""
from fractions import Fraction as F

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpers import conductor, note, smf, track  # noqa: E402

from midi_interchange.core.placement import Placement  # noqa: E402
from midi_interchange.interchange.payload import Payload  # noqa: E402
from midi_interchange.ui.timeline import HEADER_H  # noqa: E402


def part(name, pitch=60, ch=0):
    ev = []
    for b in range(4):
        ev += note(ch, pitch + b, b * 480, 240)
    return smf([conductor(480), track(ev, name=name)])


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
    w.ctl.import_payloads([Payload("b.mid", part("Bass", 40)), Payload("k.mid", part("Keys", 70, 1))])
    QApplication.processEvents()
    w.timeline.set_zoom(20.0, 0)
    w.timeline.horizontalScrollBar().setValue(0)
    w.timeline.verticalScrollBar().setValue(0)
    yield w
    w.close()


def win_pos(w, widget, p: QPoint) -> QPointF:
    return QPointF(widget.mapTo(w, p))


def test_drop_targets(win):
    tl, tp, ctl = win.timeline, win.track_panel, win.ctl
    vp = tl.viewport()
    lane1_y = HEADER_H + tl.lane_h + tl.lane_h // 2
    # over a lane at beat 8 -> that track, time 8 (beat snap)
    pl, lane = win.drop_placement(win_pos(win, vp, QPoint(int(tl.x_of(8.2)), lane1_y)))
    assert lane == 1 and pl.target_track_id == ctl.ws.tracks[1].id and pl.time == 8
    # below the last lane -> new tracks at the cursor time
    pl, lane = win.drop_placement(win_pos(win, vp, QPoint(int(tl.x_of(12)), HEADER_H + 3 * tl.lane_h)))
    assert lane is None and pl.target_track_id is None and pl.time == 12
    # over a track header -> that track at time zero
    pl, lane = win.drop_placement(win_pos(win, tp, QPoint(40, HEADER_H + tl.lane_h // 2)))
    assert lane == 0 and pl.target_track_id == ctl.ws.tracks[0].id and pl.time == 0
    # elsewhere (export panel) -> new tracks at zero
    pl, lane = win.drop_placement(win_pos(win, win.export_panel, QPoint(20, 10)))
    assert lane is None and pl == Placement()


def test_drop_import_onto_matching_track(win):
    ctl = win.ctl
    bass = ctl.ws.tracks[0]
    ctl.import_payloads([Payload("b2.mid", part("Bass", 45))], Placement(F(16), bass.id))
    assert len(ctl.ws.tracks) == 2 and [c.start for c in bass.clips] == [0, 16]
    ctl.import_payloads([Payload("x.mid", part("Strings", 50))], Placement(F(16), bass.id))
    assert [t.name for t in ctl.ws.tracks] == ["Bass", "Keys", "Strings"]


def _alt_drag(tl, p0, p1, mods):
    vp = tl.viewport()
    QTest.mousePress(vp, Qt.LeftButton, mods, p0)
    for i in range(1, 7):
        QTest.mouseMove(vp, p0 + (p1 - p0) * i / 6)
    QTest.mouseRelease(vp, Qt.LeftButton, mods, p1)
    QApplication.processEvents()


def test_alt_drag_moves_clip_to_other_track_and_removes_empty(win):
    tl, ctl = win.timeline, win.ctl
    lane = lambda i: HEADER_H + i * tl.lane_h + tl.lane_h // 2  # noqa: E731
    p0 = QPoint(int(tl.x_of(1.0)), lane(1))          # Keys clip
    p1 = QPoint(int(tl.x_of(9.0)), lane(0))          # onto Bass, 8 beats later
    _alt_drag(tl, p0, p1, Qt.AltModifier)
    assert [t.name for t in ctl.ws.tracks] == ["Bass"]
    assert [c.start for c in ctl.ws.tracks[0].clips] == [0, 8]
    ctl.undo()
    assert [t.name for t in ctl.ws.tracks] == ["Bass", "Keys"]


def test_alt_ctrl_drag_copies_clip(win):
    tl, ctl = win.timeline, win.ctl
    y = HEADER_H + tl.lane_h // 2
    _alt_drag(tl, QPoint(int(tl.x_of(1.0)), y), QPoint(int(tl.x_of(9.0)), y),
              Qt.AltModifier | Qt.ControlModifier)
    assert [c.start for c in ctl.ws.tracks[0].clips] == [0, 8]


def test_alt_drag_below_last_lane_makes_new_track(win):
    tl, ctl = win.timeline, win.ctl
    p0 = QPoint(int(tl.x_of(1.0)), HEADER_H + tl.lane_h // 2)
    p1 = QPoint(int(tl.x_of(1.0)), HEADER_H + 2 * tl.lane_h + tl.lane_h // 2)
    _alt_drag(tl, p0, p1, Qt.AltModifier)
    assert [t.name for t in ctl.ws.tracks] == ["Keys", "Bass"]


def test_new_document_is_undoable(win):
    ctl = win.ctl
    win.a_new.trigger()
    assert not ctl.ws.tracks and not ctl.ws.sources
    ctl.undo()
    assert [t.name for t in ctl.ws.tracks] == ["Bass", "Keys"]



def _below_last(win, from_lane, mods):
    tl = win.timeline
    p0 = QPoint(int(tl.x_of(1.0)), HEADER_H + from_lane * tl.lane_h + tl.lane_h // 2)
    p1 = QPoint(int(tl.x_of(1.0)), HEADER_H + len(win.ctl.ws.tracks) * tl.lane_h + tl.lane_h // 2)
    _alt_drag(tl, p0, p1, mods)
    return [(t.name, len(t.clips)) for t in win.ctl.ws.tracks]


def test_alt_drag_below_last_lane_from_last_track_with_several_clips(win):
    win.ctl.import_payloads([Payload("k2.mid", part("Keys", 72))], Placement(F(8), win.ctl.ws.tracks[1].id))
    assert _below_last(win, 1, Qt.AltModifier) == [("Bass", 1), ("Keys", 1), ("Keys", 1)]


def test_alt_drag_lone_clip_below_last_lane_is_a_no_op(win):
    undo_depth = len(win.ctl._undo)
    assert _below_last(win, 1, Qt.AltModifier) == [("Bass", 1), ("Keys", 1)]
    assert len(win.ctl._undo) == undo_depth


def test_copy_lone_clip_below_last_lane_makes_new_track(win):
    assert _below_last(win, 1, Qt.AltModifier | Qt.ControlModifier) == [("Bass", 1), ("Keys", 1), ("Keys", 1)]


def test_solo_and_unsolo(win):
    ctl = win.ctl
    bass, keys = ctl.ws.tracks
    ctl.set_track_enabled(keys.id, False)
    ctl.solo_track(keys.id)
    assert (bass.enabled, keys.enabled) == (False, True) and ctl.is_soloed(keys.id)
    ctl.solo_track(bass.id)                       # switch solo: the original selection is kept
    ctl.unsolo()
    assert (bass.enabled, keys.enabled) == (True, False) and ctl.solo is None
