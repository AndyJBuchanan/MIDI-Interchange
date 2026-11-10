"""Headless GUI workflow test: the success criterion, driven through real widgets."""
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpers import notes_of, track_by_name  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


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
    yield w
    w.close()


def x_for(tl, beats):
    return int(round(tl.x_of(beats)))


def drag(widget, p0, p1, mods=Qt.NoModifier):
    QTest.mousePress(widget, Qt.LeftButton, mods, p0)
    steps = 6
    for i in range(1, steps + 1):
        p = p0 + (p1 - p0) * i / steps
        QTest.mouseMove(widget, p)
    QTest.mouseRelease(widget, Qt.LeftButton, mods, p1)


def test_full_workflow(win, tmp_path):
    paths = sorted(str(p) for p in SAMPLES.glob("*.mid"))
    assert paths, "run tools/make_demo_midi.py first"
    win.import_paths(paths)
    ctl, tl = win.ctl, win.timeline
    assert len(ctl.ws.tracks) == 5
    QApplication.processEvents()
    tl.set_zoom(20.0, 0)
    tl.horizontalScrollBar().setValue(0)
    vp = tl.viewport()
    y_lane = 58 + tl.lane_h // 2

    # create a range by dragging across lanes: beats 4.2 -> 11.8 snaps to beats 4..12
    drag(vp, QPoint(x_for(tl, 4.2), y_lane), QPoint(x_for(tl, 11.8), y_lane))
    assert len(ctl.ws.ranges) == 1
    r = ctl.ws.ranges[0]
    assert (r.start, r.end) == (F(4), F(12))
    assert ctl.selected_range_id == r.id

    # resize the end edge to beat 16
    drag(vp, QPoint(x_for(tl, 12), y_lane), QPoint(x_for(tl, 16.1), y_lane))
    assert (r.start, r.end) == (F(4), F(16))

    # move the body in the range strip by +4 beats
    y_strip = 38 + 10
    drag(vp, QPoint(x_for(tl, 8), y_strip), QPoint(x_for(tl, 12), y_strip))
    assert (r.start, r.end) == (F(8), F(20))

    # undo restores previous position; redo re-applies
    ctl.undo()
    r = ctl.ws.ranges[0]
    assert (r.start, r.end) == (F(4), F(16))
    ctl.redo()
    r = ctl.ws.ranges[0]
    assert (r.start, r.end) == (F(8), F(20))

    # numeric entry through the export panel
    ep = win.export_panel
    ep.start_edit.setText("3.1")
    ep.end_edit.setText("5.1.000")
    ep._commit_positions()
    assert (r.start, r.end) == (F(8), F(16))

    # rename a track via its header, disable another
    bass = next(t for t in ctl.ws.tracks if t.name == "Bass")
    hdr = win.track_panel.header(bass.id)
    hdr.name_edit.setText("Low End")
    hdr._commit_name()
    assert bass.name == "Low End"
    drums = next(t for t in ctl.ws.tracks if t.name == "Drums")
    win.track_panel.header(drums.id).enabled_cb.setChecked(False)
    assert drums.enabled is False

    # export (rebase) and verify
    from midi_interchange.core.export_smf import ExportMode, save_exports
    ctl.set_export_mode(ExportMode.REBASE)
    out = tmp_path / "out.mid"
    save_exports(ctl.build_exports(), str(out))
    mf = mido.MidiFile(str(out))
    names = [m.name for t in mf.tracks for m in t if m.type == "track_name"]
    # the range was drawn while Drums was on: the range's toggle wins
    assert "Low End" in names and "Drums" in names
    ctl.set_range_track_included(r.id, drums.id, False)
    save_exports(ctl.build_exports(), str(out))
    mf = mido.MidiFile(str(out))
    names = [m.name for t in mf.tracks for m in t if m.type == "track_name"]
    assert "Low End" in names and "Drums" not in names
    bass_notes = notes_of(track_by_name(mf, "Low End"), mf.ticks_per_beat)
    assert bass_notes and bass_notes[0][0] == 0 and max(n[1] for n in bass_notes) <= 8

    # delete range with keyboard
    tl.setFocus()
    QTest.keyClick(tl, Qt.Key_Backspace)
    assert ctl.ws.ranges == []


def test_shift_bypasses_snap_and_alt_moves_clip(win):
    win.import_paths([str(SAMPLES / "vocal_lyrics.mid")])
    ctl, tl = win.ctl, win.timeline
    QApplication.processEvents()
    tl.set_zoom(40.0, 0)
    tl.horizontalScrollBar().setValue(0)
    vp = tl.viewport()
    y = 58 + tl.lane_h // 2
    drag(vp, QPoint(x_for(tl, 1.3), y), QPoint(x_for(tl, 2.7), y), Qt.ShiftModifier)
    r = ctl.ws.ranges[0]
    assert r.start != int(r.start) and abs(float(r.start) - 1.3) < 0.05

    clip = ctl.ws.tracks[0].clips[0]
    drag(vp, QPoint(x_for(tl, 18), y), QPoint(x_for(tl, 22.1), y), Qt.AltModifier)
    assert clip.offset == F(4)
    ctl.undo()
    assert ctl.ws.tracks[0].clips[0].offset == 0


def test_zoom_keeps_anchor(win):
    win.import_paths([str(SAMPLES / "piano_96bpm.mid")])
    tl = win.timeline
    tl.set_zoom(30.0, 0)
    tl.horizontalScrollBar().setValue(300)
    t_before = tl.t_of(400)
    tl.zoom_by(2.0, 400)
    assert abs(tl.t_of(400) - t_before) < 0.1


def test_alt_wheel_lane_height_is_gentle(win):
    """Studio 2026-11-10: Alt+wheel was too sensitive. 3 px per wheel notch,
    and small trackpad deltas add up instead of each stepping 6 px."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    tl = win.timeline
    tl.set_lane_height(68)

    def wheel(dy):
        pos = QPointF(200, 120)
        tl.wheelEvent(QWheelEvent(pos, tl.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy),
                                  Qt.NoButton, Qt.AltModifier, Qt.NoScrollPhase, False))

    wheel(120)
    assert tl.lane_h == 71
    for _ in range(4):
        wheel(10)                       # a slow trackpad stroke: 40 units
    assert tl.lane_h == 72
    wheel(-240)
    assert tl.lane_h == 66


def test_drop_preview_knows_song_titles(win):
    """Studio 2026-11-10: the drop preview still compared exact names, so over a
    matching row it said 'names differ' for a new Staccato generation."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDragEnterEvent
    from midi_interchange.ui.timeline import HEADER_H
    win.import_paths([str(SAMPLES / "non-synthetic" / "Industrial EBM Anthem_1793561268176.mid")])
    QApplication.processEvents()
    tl = win.timeline
    tl.set_zoom(20.0, 0)
    tl.horizontalScrollBar().setValue(0)
    tl.verticalScrollBar().setValue(0)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(SAMPLES / "non-synthetic" / "Staccato Generation_1794336609801.mid"))])

    def preview(lane):
        y = HEADER_H + lane * tl.lane_h + tl.lane_h // 2
        pt = tl.viewport().mapTo(win, QPoint(int(tl.x_of(8.1)), y))
        win.dragEnterEvent(QDragEnterEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        return tl._drop_ind[2]

    assert preview(0).startswith("Onto “Heavy EBM Drums - Industrial EBM Anthem”")
    assert "nothing matches “Piercing Lead - Industrial EBM Anthem”" in preview(2)   # not in the new generation
    win.dragLeaveEvent(None)
