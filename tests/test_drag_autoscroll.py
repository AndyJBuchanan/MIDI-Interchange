"""Shared timeline reach and edge scrolling, including external MIDI drags."""
from fractions import Fraction as F

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from helpers import conductor, note, smf, track
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui.main_window import MainWindow
from midi_interchange.ui import theme
from midi_interchange.ui.timeline import HEADER_H


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    data = smf([conductor(480), track(note(0, 60, 0, 4 * 480), name="Lead")])
    w.ctl.import_payloads([Payload("lead.mid", data)])
    QApplication.processEvents()
    w.timeline.set_zoom(20, 0)
    w.timeline.horizontalScrollBar().setValue(120)
    yield w, data
    w.close()


def enter(w, data, x=None):
    tl = w.timeline
    pos = QPoint(tl.viewport().width() - 5 if x is None else x, HEADER_H + 25)
    pt = tl.viewport().mapTo(w, pos)
    mime = QMimeData()
    mime.setData("audio/midi", data)
    event = QDragEnterEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    w.dragEnterEvent(event)
    assert event.isAccepted()
    return mime, pos, pt  # keep MIME data alive for Qt events


def scroll_far(tl, pos):
    for _ in range(200):
        tl._autoscroll_step(pos.x(), pos.y(), False)


def test_length_uses_content_ranges_and_temporary_reach(win):
    w, _ = win
    tl = w.timeline
    assert tl.total_beats() == 128
    w.ctl.add_range(F(100), F(160))
    assert tl.total_beats() == 192
    tl.begin_drag(external=True)
    tl._drag_reach = 220
    assert tl.total_beats() == 252
    tl.end_drag(cancel=True)
    assert tl.total_beats() == 192


def test_external_move_scrolls_and_leave_restores_view(win):
    w, data = win
    tl = w.timeline
    before = tl.total_beats(), tl.horizontalScrollBar().value(), tl.horizontalScrollBar().maximum()
    mime, pos, pt = enter(w, data, x=100)
    assert not tl._autoscroll.isActive()
    pos.setX(tl.viewport().width() - 5)
    pt = tl.viewport().mapTo(w, pos)
    event = QDragMoveEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    w.dragMoveEvent(event)
    assert event.isAccepted() and tl._autoscroll.isActive()
    scroll_far(tl, pos)
    assert tl.total_beats() > before[0]
    assert tl.horizontalScrollBar().value() > before[1]
    assert tl._drop_ind[1] == tl.time_at(pos.x())
    w.dragLeaveEvent(QDragLeaveEvent())
    assert (tl.total_beats(), tl.horizontalScrollBar().value(), tl.horizontalScrollBar().maximum()) == before
    assert not tl._autoscroll.isActive() and tl._drop_ind is None
    tl._autoscroll_step(pos.x(), pos.y(), False)
    assert tl.horizontalScrollBar().value() == before[1]


def test_timer_reads_cursor_and_updates_preview_without_move_events(win, monkeypatch):
    w, data = win
    tl = w.timeline
    mime, pos, _ = enter(w, data)
    monkeypatch.setattr(QCursor, "pos", lambda: tl.viewport().mapToGlobal(pos))
    before = tl.horizontalScrollBar().value()
    tl._autoscroll_tick()
    assert tl.horizontalScrollBar().value() == before + 15
    assert tl._drop_ind[1] == tl.time_at(pos.x())
    # The left edge uses the same speed.
    pos.setX(5)
    tl._autoscroll_tick()
    assert tl.horizontalScrollBar().value() == before
    w.dragLeaveEvent(QDragLeaveEvent())


def test_drop_discards_furthest_reach_and_uses_current_placement(win):
    w, data = win
    tl = w.timeline
    mime, pos, _ = enter(w, data)
    scroll_far(tl, pos)
    far_length = tl.total_beats()
    tl.horizontalScrollBar().setValue(120)
    pos.setX(100)
    pt = tl.viewport().mapTo(w, pos)
    placement, _ = w.drop_placement(QPointF(pt))
    w.dropEvent(QDropEvent(QPointF(pt), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert any(c.start == placement.time for t in w.ctl.ws.tracks for c in t.clips)
    assert tl.total_beats() == max(float(w.ctl.ws.end) + 32, 128)
    assert tl.total_beats() < far_length
    assert tl._drag_reach is None and not tl._autoscroll.isActive()


def test_late_drop_keeps_length_needed_for_new_content(win):
    w, data = win
    tl = w.timeline
    mime, pos, pt = enter(w, data)
    scroll_far(tl, pos)
    placement, _ = w.drop_placement(QPointF(pt))
    scroll = tl.horizontalScrollBar().value()
    assert placement.time > 128
    w.dropEvent(QDropEvent(QPointF(pt), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert w.ctl.ws.end == placement.time + 4
    assert tl.total_beats() == float(w.ctl.ws.end) + 32
    assert tl.horizontalScrollBar().value() == scroll
    assert not tl._autoscroll.isActive()


@pytest.mark.parametrize("clip", [False, True])
def test_internal_drags_extend_and_release_recomputes_length(win, clip):
    w, _ = win
    tl = w.timeline
    tl.horizontalScrollBar().setValue(0)
    mods = Qt.AltModifier if clip else Qt.NoModifier
    start = QPoint(20, HEADER_H + 25) if clip else QPoint(200, 10)
    vp = tl.viewport()
    QTest.mousePress(vp, Qt.LeftButton, mods, start)
    pos = QPoint(vp.width() - 5, start.y())
    scroll_far(tl, pos)
    assert tl.total_beats() > 128
    if clip:
        assert w.ctl.ws.tracks[0].clips[0].start > 128
    else:
        assert w.ctl.ws.ranges[0].end > 128
    QTest.mouseRelease(vp, Qt.LeftButton, mods, pos)
    end = max(float(w.ctl.ws.end), *(float(r.end) for r in w.ctl.ws.ranges), 0)
    assert tl.total_beats() == max(end + 32, 128)
    assert tl._drag_reach is None and not tl._autoscroll.isActive()


def test_external_drag_outside_timeline_stops_scrolling(win):
    w, data = win
    tl = w.timeline
    mime, _, _ = enter(w, data)
    pt = w.track_panel.mapTo(w, QPoint(10, HEADER_H + 25))
    w.dragMoveEvent(QDragMoveEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert not tl._autoscroll.isActive()
    assert tl._drop_ind[1] == 0
    w.dragLeaveEvent(QDragLeaveEvent())


@pytest.mark.parametrize("new_track", [False, True])
def test_drop_time_visible_in_ruler_when_destination_is_below_view(win, new_track):
    w, data = win
    tl = w.timeline
    # Scroll a matching lane above the viewport, or leave the new-track lane
    # below it. The ruler must still show the actual drop time in both cases.
    for _ in range(12):
        w.ctl.import_payloads([Payload("lead.mid", data)])
    tl.set_lane_height(220)
    lane = None if new_track else 0
    tl.verticalScrollBar().setValue(0 if new_track else tl.verticalScrollBar().maximum())
    if not new_track:
        assert tl.lane_top(lane) + tl.lane_h <= HEADER_H
    else:
        assert tl.lane_top(len(w.ctl.ws.tracks)) >= tl.viewport().height()
    tl.set_drop_indicator((lane, F(16), "Drop here"))
    x = round(tl.x_of(16))
    image = tl.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    assert image.pixelColor(round(x * scale), round(3 * scale)) == theme.ACCENT
    tl.set_drop_indicator(None)
    image = tl.viewport().grab().toImage()
    assert image.pixelColor(round(x * scale), round(3 * scale)) != theme.ACCENT
