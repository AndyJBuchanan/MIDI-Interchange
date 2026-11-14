"""Timeline management: Tempo Map menus, the marker row and Show Markers (headless)."""
import mido
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from helpers import conductor, note, smf, track  # noqa: E402
from midi_interchange.interchange.payload import Payload  # noqa: E402
from midi_interchange.ui import theme  # noqa: E402
from midi_interchange.ui.main_window import MainWindow  # noqa: E402

BASE = 22 + 16 + 20          # ruler + tempo row + range strip
ROW = 16


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)


@pytest.fixture
def win(app, tmp_path):
    w = MainWindow(make_settings(tmp_path))
    w.resize(1200, 700)
    w.show()
    QTest.qWaitForWindowExposed(w)
    yield w
    w.close()


def marker_file(bpm=100.0, name="Marks"):
    marks = track([(0, mido.MetaMessage("marker", text="Verse")),
                   (960, mido.MetaMessage("cue_marker", text="Cue"))], name=name)
    return smf([conductor(480, tempos=((0, bpm),)), marks])


def notes_file(bpm=140.0, name="Lead"):
    return smf([conductor(480, tempos=((0, bpm),)), track(note(0, 60, 0, 480), name=name)])


def load(win, data, name="f.mid"):
    win.ctl.import_payloads([Payload(name, data)])
    QApplication.processEvents()


def track_named(win, name):
    return next(t for t in win.ctl.ws.tracks if t.name == name)


def tempo_items(menu: QMenu):
    sub = next(a for a in menu.actions() if a.text() == "Tempo Map").menu()
    return [a for a in sub.actions() if a.isCheckable()]


# ------------------------------------------------------------------ menus
def test_header_menu_lists_files_with_maps_current_ticked(win):
    load(win, marker_file(100.0), "a.mid")
    load(win, notes_file(140.0), "b.mid")
    items = tempo_items(win.header_menu())
    assert len(items) == 2
    assert [a.isChecked() for a in items] == [True, False]
    assert "a.mid" in items[0].text() and "100" in items[0].text()


def test_header_menu_with_no_map_says_so(win):
    sub = next(a for a in win.header_menu().actions() if a.text() == "Tempo Map").menu()
    assert [(a.text(), a.isEnabled()) for a in sub.actions()] == [
        ("No imported tempo maps (using 120 BPM, 4/4)", False)]


def test_right_click_on_ruler_and_info_rows_asks_for_the_menu_but_the_strip_does_not(win, monkeypatch):
    class NoMenu:                                                  # never block on a real menu
        def exec(self, *_a):
            pass
    monkeypatch.setattr(win, "header_menu", lambda: NoMenu())
    load(win, marker_file())
    tl = win.timeline
    asked = []
    tl.headerMenuRequested.connect(asked.append)
    vp = tl.viewport()
    for y in (5, 22 + 5, tl.marker_top() + 5):
        QTest.mouseClick(vp, Qt.RightButton, Qt.NoModifier, QPoint(300, y))
    assert len(asked) == 3
    assert tl.range_top() == 22 + 16 + ROW
    QTest.mouseClick(vp, Qt.RightButton, Qt.NoModifier, QPoint(300, tl.range_top() + 5))
    assert len(asked) == 3                       # the range strip has no tempo menu


def test_choosing_a_map_adopts_it_and_undo_restores_the_previous(win):
    load(win, marker_file(100.0), "a.mid")
    load(win, notes_file(140.0), "b.mid")
    ws = win.ctl.ws
    first = ws.tempo_source_id
    items = tempo_items(win.header_menu())
    items[1].trigger()
    assert ws.tempo_source_id != first
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(140.0, abs=0.01)
    win.ctl.undo()
    assert ws.tempo_source_id == first
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(100.0, abs=0.01)


def test_track_menu_item_adopts_that_tracks_map_and_is_absent_without_one(win):
    load(win, marker_file(100.0), "a.mid")
    load(win, notes_file(140.0), "b.mid")
    ws = win.ctl.ws

    menus = []

    def item(name):
        m = QMenu()
        menus.append(m)
        win._add_track_actions(m, track_named(win, name).id)
        return next((a for a in m.actions() if a.text() == "Use This Track's Tempo Map"), None)

    a = item("Lead")
    assert a is not None and not a.isChecked()
    assert item("Marks").isChecked()
    a.trigger()
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(140.0, abs=0.01)
    assert item("Lead").isChecked()
    win.ctl.undo()
    assert ws.tempo_map.effective_tempos()[0].bpm == pytest.approx(100.0, abs=0.01)

    # a file with no tempo map: no item
    bare = smf([track(note(0, 62, 0, 480), name="Bare")])
    load(win, bare, "bare.mid")
    assert item("Bare") is None


# ------------------------------------------------------------------ header height
def test_no_markers_means_ruler_tempo_row_and_range_strip(win):
    tl = win.timeline
    assert tl.header_h() == BASE and tl.range_top() == 38 and not tl.marker_row_shown()
    load(win, notes_file())
    assert tl.header_h() == BASE


def test_marker_row_appears_with_markers_moves_lanes_and_undo_removes_it(win):
    tl = win.timeline
    load(win, notes_file(), "n.mid")
    top = tl.lane_top(0)
    changes = []
    tl.headerHeightChanged.connect(changes.append)
    load(win, marker_file(), "m.mid")
    assert tl.marker_row_shown() and tl.header_h() == BASE + ROW
    assert tl.lane_top(0) == top + ROW
    assert changes == [BASE + ROW]
    assert win.track_panel.lanes.y() == tl.header_h()
    win.ctl.undo()
    assert tl.header_h() == BASE and tl.lane_top(0) == top
    win.ctl.redo()
    assert tl.header_h() == BASE + ROW


def test_row_follows_mute_and_solo_of_the_export_set(win):
    tl, ctl = win.timeline, win.ctl
    load(win, marker_file(), "m.mid")
    load(win, notes_file(), "n.mid")
    marks, lead = track_named(win, "Marks"), track_named(win, "Lead")
    assert tl.header_h() == BASE + ROW
    ctl.set_mute(marks.id, True)
    assert tl.header_h() == BASE
    ctl.set_mute(marks.id, False)
    assert tl.header_h() == BASE + ROW
    ctl.toggle_solo(lead.id)                   # solo elsewhere: Marks is no longer exported
    assert tl.header_h() == BASE
    assert tl.header_markers() == []
    ctl.toggle_solo(lead.id)
    assert tl.header_h() == BASE + ROW


def test_markers_come_from_exported_tracks_only(win):
    load(win, marker_file(name="One"), "one.mid")
    load(win, marker_file(name="Two"), "two.mid")
    tl = win.timeline
    assert len(tl.header_markers()) == 4
    win.ctl.set_mute(track_named(win, "One").id, True)
    assert len(tl.header_markers()) == 2
    assert tl.header_h() == BASE + ROW


def test_show_markers_off_hides_the_row_and_persists(app, tmp_path):
    path = tmp_path / "s.ini"
    w = MainWindow(QSettings(str(path), QSettings.IniFormat))
    load(w, marker_file())
    assert w.a_markers.isChecked() and w.timeline.header_h() == BASE + ROW
    w.a_markers.trigger()
    assert w.timeline.header_h() == BASE and w.timeline.header_markers()   # markers still exist
    w.settings.sync()
    w.close()

    w2 = MainWindow(QSettings(str(path), QSettings.IniFormat))
    assert not w2.a_markers.isChecked()
    load(w2, marker_file())
    assert w2.timeline.header_h() == BASE
    w2.a_markers.trigger()
    assert w2.timeline.header_h() == BASE + ROW
    w2.close()


def test_show_markers_is_one_action_on_the_toolbar_and_in_the_timing_menu(win):
    assert win.a_markers.isCheckable() and win.a_markers.iconText() == "Markers"
    timing = next(a for a in win.menuBar().actions() if a.text() == "&Timing").menu()
    assert win.a_markers in timing.actions()
    from PySide6.QtWidgets import QToolBar
    assert any(win.a_markers in tb.actions() for tb in win.findChildren(QToolBar))


def test_adopting_a_tempo_map_does_not_change_the_height(win):
    load(win, marker_file(100.0), "a.mid")
    load(win, notes_file(140.0), "b.mid")
    before = win.timeline.header_h()
    tempo_items(win.header_menu())[1].trigger()
    assert win.timeline.header_h() == before


def test_a_drop_grows_the_header_after_the_drop_not_during_it(win, tmp_path):
    load(win, notes_file(), "n.mid")
    tl = win.timeline
    p = tmp_path / "m.mid"
    p.write_bytes(marker_file())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    pt = tl.viewport().mapTo(win, QPoint(200, tl.header_h() + 30))
    win.dragEnterEvent(QDragEnterEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert tl.header_h() == BASE
    win.dropEvent(QDropEvent(QPointF(pt), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    QApplication.processEvents()
    assert tl.header_h() == BASE + ROW


# ------------------------------------------------------------------ hit testing
@pytest.mark.parametrize("with_markers", [False, True])
def test_hit_testing_follows_the_header(win, with_markers):
    load(win, notes_file())
    if with_markers:
        load(win, marker_file())
    tl, ctl = win.timeline, win.ctl
    assert tl.marker_row_shown() == with_markers
    tl.set_zoom(20, 0)
    tl.horizontalScrollBar().setValue(0)
    r = ctl.add_range(ctl.ws.end * 0 + 4, ctl.ws.end * 0 + 8)
    x_in = int(tl.x_of(6))
    assert tl._hit(QPointF(x_in, tl.range_top() + 5))[0] == "body"
    assert tl._hit(QPointF(x_in + 200, tl.range_top() + 5))[0] == "strip"
    assert tl._hit(QPointF(x_in, tl.range_top() - 3))[0] == "empty"      # the row above is not the strip
    for i, t in enumerate(ctl.ws.tracks):
        hit = tl._hit(QPointF(int(tl.x_of(30)), tl.lane_top(i) + tl.lane_h // 2))
        assert hit == ("lane", t.id)
    assert tl.lane_at(tl.header_h() - 1) == -1 and tl.lane_at(tl.header_h() + 1) == 0
    ctl.delete_range(r.id)
    # a drag on the ruler starts a range
    vp = tl.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(10)), 8))
    for dx in (20, 60, 120):
        QTest.mouseMove(vp, QPoint(int(tl.x_of(10)) + dx, 8))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_of(10)) + 120, 8))
    assert len(ctl.ws.ranges) == 1


# ------------------------------------------------------------------ colour
def test_dark_colours_are_lightened_on_the_info_row():
    black = theme.readable_on_info(QColor("#000000"))
    assert black != QColor("#000000") and black.lightnessF() > 0.3
    bright = QColor("#ffcc66")
    assert theme.readable_on_info(bright) == bright


def test_a_marker_on_a_black_track_is_not_drawn_black(win):
    load(win, marker_file())
    track_named(win, "Marks").color = "#000000"
    (_t, _text, color), *_ = win.timeline.header_markers()
    assert color != QColor("#000000")
    assert color == theme.readable_on_info(QColor("#000000"))
