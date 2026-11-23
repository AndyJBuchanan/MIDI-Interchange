"""Session sources dialog: the (i) button, the dialog, and Solo all source tracks."""
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTextEdit, QToolBar

from helpers import conductor, note, smf, track
from test_ui_assembly import app, win  # noqa: F401
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui import main_window
from midi_interchange.ui.source_info import SourceInfoDialog, SourcesDialog


def part(name, pitch):
    return smf([conductor(480), track(note(0, pitch, 0, 480), name)])


@pytest.fixture
def three(win):
    """Three sources: b.mid and k.mid (from the fixture) plus c.mid, each on its own track."""
    c = win.ctl
    c.import_payloads([Payload("c.mid", part("Chords", 64))])
    QApplication.processEvents()
    assert [s.name for s in c.ws.sources] == ["b.mid", "k.mid", "c.mid"]
    return win


def values(dialog):
    return [v.toPlainText() for v in dialog.detail_host.findChildren(QTextEdit)]


def soloed(ws):
    return [t.name for t in ws.tracks if t.soloed]


# ---------------------------------------------------------------- the (i) button

def test_info_button_sits_in_the_title_band_clear_of_m_and_s(win):
    p = win.track_panel
    for width in (p.minimumWidth(), 240, 400):
        p.resize(width, 400)
        QApplication.processEvents()
        i, m, s = p.info_btn.geometry(), p.clear_m.geometry(), p.clear_s.geometry()
        assert i.right() < m.left() and m.right() < s.left()
        assert 0 <= i.top() and i.bottom() <= win.timeline.header_h()
        text_end = p.title.x() + p.title.sizeHint().width()
        assert i.left() >= text_end            # beside the count, not on it
    assert p.info_btn.toolTip() == "Sources in this session"
    assert p.info_btn.accessibleName()
    assert p.info_btn.cursor().shape() == Qt.PointingHandCursor


def test_info_button_clears_the_count_with_three_digit_track_numbers(win):
    c = win.ctl
    for n in range(118):
        c.import_payloads([Payload(f"x{n}.mid", part(f"T{n}", 60))])
    QApplication.processEvents()
    p = win.track_panel
    assert p.title.text().strip().endswith("/120")
    p.resize(p.minimumWidth(), 400)
    QApplication.processEvents()
    i, m = p.info_btn.geometry(), p.clear_m.geometry()
    assert p.title.x() + p.title.sizeHint().width() <= i.left() and i.right() < m.left()


def test_info_button_opens_the_dialog_and_is_the_only_way_in(win, monkeypatch):
    shown = []
    monkeypatch.setattr(SourcesDialog, "exec", lambda self: shown.append(self))
    QTest.mouseClick(win.track_panel.info_btn, Qt.LeftButton)
    assert len(shown) == 1 and isinstance(shown[0], SourcesDialog) and shown[0].isModal()
    menus = [a.text() for m in win.menuBar().actions() if m.menu() for a in m.menu().actions()]
    toolbar = [a.text() for tb in win.findChildren(QToolBar) for a in tb.actions()]
    assert not any("Source" in t for t in menus + toolbar)


# ---------------------------------------------------------------- the dialog

def test_lists_every_source_in_import_order_with_details(three):
    d = SourcesDialog(three.ctl.ws, three.ctl)
    assert [d.src_list.item(i).text() for i in range(d.src_list.count())] == ["b.mid", "k.mid", "c.mid"]
    assert d.src_list.currentRow() == 0
    assert "3 in this session" in d.windowTitle()
    assert three.ctl.ws.sources[0].file_summary in values(d)
    # everything Source Info shows for that source's track is shown here too
    info = SourceInfoDialog(three.ctl.ws, three.ctl.ws.tracks[0])
    assert set(values(info)) <= set(values(d))
    d.close()
    info.close()


def test_used_by_lists_tracks_and_counts_including_moved_clips(three):
    ws = three.ctl.ws
    bass, keys, _chords = ws.tracks
    d = SourcesDialog(ws, three.ctl)
    assert d.pane.usage(ws.sources[0].id) == "Bass: 1 clip"
    keys.clips.append(replace(bass.clips[0], id="moved"))          # a b.mid clip now on Keys too
    keys.clips.append(replace(bass.clips[0], id="moved2"))
    assert d.pane.usage(ws.sources[0].id).splitlines() == ["Bass: 1 clip", "Keys: 2 clips"]
    assert "Used by:" in [lb.text() for lb in d.detail_host.findChildren(QLabel)]
    d.close()


def test_clipless_tempo_source_reads_no_clips(three):
    ws = three.ctl.ws
    src = ws.sources[2]
    ws.tracks[2].clips.clear()
    ws.tempo_source_id = src.id
    d = SourcesDialog(ws, three.ctl)
    d.src_list.setCurrentRow(2)
    assert "No clips (kept for its tempo map)" in values(d)
    assert not d.solo_btn.isEnabled()
    d.close()


def test_empty_workspace_says_nothing_imported(win):
    win.ctl.new_document()
    d = SourcesDialog(win.ctl.ws, win.ctl)
    assert d.empty_label.text() == "Nothing imported yet."
    assert not d.solo_btn.isEnabled()
    d.close()


# ---------------------------------------------------------------- solo

def test_solo_all_source_tracks_is_exclusive_one_undo_step_and_closes(three):
    c = three.ctl
    ws = c.ws
    ws.tracks[1].soloed = True                  # a different solo, to be replaced
    d = SourcesDialog(ws, c)
    d.src_list.setCurrentRow(0)                 # b.mid -> Bass
    assert d.solo_btn.isEnabled()
    before = len(c._undo)
    d.solo_btn.click()
    assert d.result() == QDialog.Accepted
    assert soloed(ws) == ["Bass"]
    assert len(c._undo) == before + 1
    c.undo()
    assert soloed(ws) == ["Keys"]
    c.redo()
    assert soloed(ws) == ["Bass"]


def test_solo_covers_every_track_the_source_feeds(three):
    c = three.ctl
    ws = c.ws
    bass, keys, chords = ws.tracks
    keys.clips.append(replace(bass.clips[0], id="copy"))        # b.mid also on Keys
    d = SourcesDialog(ws, c)
    d.src_list.setCurrentRow(0)
    d.solo_btn.click()
    assert soloed(ws) == ["Bass", "Keys"]


def test_already_that_set_makes_no_undo_step_but_still_closes(three):
    c = three.ctl
    c.solo_source_tracks(c.ws.sources[0].id)
    d = SourcesDialog(c.ws, c)
    d.src_list.setCurrentRow(0)
    before = len(c._undo)
    d.solo_btn.click()
    assert len(c._undo) == before and d.result() == QDialog.Accepted
    assert soloed(c.ws) == ["Bass"]


def test_solo_follows_mute_rules_and_unlocked_ranges(three):
    c = three.ctl
    ws = c.ws
    c.set_mute(ws.tracks[0].id, True)
    c.add_range(0, 4)
    c.solo_source_tracks(ws.sources[0].id)
    assert soloed(ws) == ["Bass"]
    assert ws.tracks[0].muted and ws.tracks[0] in ws.global_tracks()      # solo overrides the mute
    assert [t.id for t in ws.global_tracks()] == [ws.tracks[0].id]
    assert not ws.ranges[0].excluded.isdisjoint({ws.tracks[1].id, ws.tracks[2].id})   # unlocked range followed
    c.undo()
    assert soloed(ws) == [] and ws.tracks[0].muted


# ---------------------------------------------------------------- close

@pytest.mark.parametrize("how", ["button", "escape"])
def test_close_and_escape_change_nothing(three, how):
    c = three.ctl
    d = SourcesDialog(c.ws, c)
    d.show()
    before = (len(c._undo), soloed(c.ws))
    if how == "button":
        d.close_btn.click()
    else:
        QTest.keyClick(d, Qt.Key_Escape)
    assert d.result() == QDialog.Rejected
    assert (len(c._undo), soloed(c.ws)) == before


def test_source_info_is_unchanged(three):
    t = three.ctl.ws.tracks[0]
    d = SourceInfoDialog(three.ctl.ws, t)
    assert d.windowTitle() == f"Source Info — {t.name}"
    assert d.src_list.count() == 1
    assert "Used by:" not in [lb.text() for lb in d.detail_host.findChildren(QLabel)]
    d.close()
