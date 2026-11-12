"""Mute/solo transitions and range locks, including real widget actions."""
from fractions import Fraction as F

import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_ui_assembly import app, win, part
from midi_interchange.interchange.payload import Payload


def test_solo_preserves_mute_and_muting_cancels_solo(win):
    c = win.ctl
    a, b = c.ws.tracks
    c.set_mute(a.id, True)
    c.toggle_solo(a.id)
    assert c.ws.global_tracks() == [a] and a.muted
    c.toggle_solo(a.id)
    assert c.ws.global_tracks() == [b] and a.muted
    c.toggle_solo(a.id)
    c.set_mute(a.id, True)
    assert a.muted and not a.soloed
    c.set_mute(a.id, False)
    assert not a.soloed and c.ws.global_tracks() == [a, b]


def test_exclusive_solo_clear_and_hidden_mutes(win):
    c = win.ctl
    a, b = c.ws.tracks
    c.set_mute(a.id, True)
    c.toggle_solo(a.id)
    c.toggle_solo(b.id)
    assert c.ws.global_tracks() == [a, b]
    c.toggle_solo(b.id, exclusive=True)
    assert a.muted and not a.soloed and c.ws.global_tracks() == [b]
    c.toggle_solo(b.id, exclusive=True)
    assert not any(t.soloed for t in c.ws.tracks)
    c.toggle_solo(a.id)
    win.track_panel.clear_m.click()
    assert a.soloed and not a.muted
    win.track_panel.clear_s.click()
    assert c.ws.global_tracks() == [a, b]


def test_follow_lock_unlock_and_atomic_undo(win):
    c = win.ctl
    a, b = c.ws.tracks
    following = c.add_range(F(0), F(4))
    locked = c.add_range(F(4), F(8))
    c.set_range_locked(locked.id, True)
    depth = len(c._undo)
    c.toggle_solo(a.id)
    assert following.includes(a.id) and not following.includes(b.id)
    assert locked.includes(b.id)
    assert len(c._undo) == depth + 1
    c.undo()
    assert not c.ws.track(a.id).soloed and c.ws.range(following.id).includes(b.id)
    c.redo()
    assert c.ws.track(a.id).soloed and not c.ws.range(following.id).includes(b.id)
    c.set_range_track_included(locked.id, a.id, False)
    c.set_range_locked(locked.id, False)
    r = c.ws.range(locked.id)
    assert not r.track_locked and r.includes(a.id) and not r.includes(b.id)
    c.undo()
    r = c.ws.range(locked.id)
    assert r.track_locked and not r.includes(a.id) and r.includes(b.id)


def test_new_tracks_and_removing_last_solo_update_followers(win):
    c = win.ctl
    a = c.ws.tracks[0]
    r = c.add_range(F(0), F(4))
    locked = c.add_range(F(4), F(8))
    c.set_range_tracks(locked.id, False)
    c.toggle_solo(a.id)
    c.import_payloads([Payload('new.mid', part('New'))])
    new = c.ws.tracks[-1]
    assert locked.includes(new.id) and r.includes(new.id)
    assert new.soloed and not new.muted
    c.remove_track(a.id)
    assert r.includes(new.id)


def test_padlock_and_disabled_checkboxes(win):
    c, tl = win.ctl, win.timeline
    r = c.add_range(F(4), F(12))
    checkbox = tl.toggle_rect(r, 0).center().toPoint()
    lock = tl.lock_rect(r).center().toPoint()
    depth = len(c._undo)
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, checkbox)
    assert r.includes(c.ws.tracks[0].id) and len(c._undo) == depth
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, lock)
    assert r.track_locked
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, checkbox)
    assert not r.includes(c.ws.tracks[0].id)
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, lock)
    assert not r.track_locked and r.includes(c.ws.tracks[0].id)
    actions = {a.text(): a for a in tl.range_menu(r.id).actions()}
    assert not any(t.name in actions for t in c.ws.tracks)
    assert "Tracks in this range" not in actions
    actions['Exclude All Tracks'].trigger()
    assert r.track_locked and not any(r.includes(t.id) for t in c.ws.tracks)


def test_mute_button_on_hidden_mute_and_alt_all(win):
    c = win.ctl
    a, b = c.ws.tracks
    c.set_mute(a.id, True)
    c.toggle_solo(a.id)
    button = win.track_panel.header(a.id).mute_btn
    QTest.mouseClick(button, Qt.LeftButton, Qt.AltModifier)
    assert all(t.muted and not t.soloed for t in c.ws.tracks)
    QTest.mouseClick(button, Qt.LeftButton, Qt.AltModifier)
    assert all(not t.muted and not t.soloed for t in c.ws.tracks)


@pytest.mark.parametrize("solo", [False, True])
@pytest.mark.parametrize("creation", ["import", "move", "copy"])
def test_new_tracks_always_on_without_inheriting_source_mute(win, solo, creation):
    c = win.ctl
    source, other = c.ws.tracks
    c.set_mute(source.id, True)
    if solo:
        c.toggle_solo(other.id)
    following = c.add_range(F(0), F(4))
    locked = c.add_range(F(4), F(8))
    c.set_range_tracks(locked.id, False)
    if creation == "import":
        c.import_payloads([Payload("new.mid", part("New"))])
        new = c.ws.tracks[-1]
    else:
        c.checkpoint()
        cid = source.clips[0].id
        if creation == "copy":
            cid = c.duplicate_clip(cid, checkpoint=False)
        new = c.ws.new_track_for_clip(cid, like=source)
        c.end_clip_gesture()
    assert new in c.ws.global_tracks()
    assert not new.muted and new.soloed == solo
    assert following.includes(new.id) and locked.includes(new.id)
    assert other.soloed == solo
    new_id = new.id
    c.undo()
    assert c.ws.track(new_id) is None
    c.redo()
    new = c.ws.track(new_id)
    assert new in c.ws.global_tracks() and new.soloed == solo and not new.muted


def test_top_m_indicator_ignores_hidden_mutes_but_clear_still_clears_them(win):
    c = win.ctl
    a, b = c.ws.tracks
    c.set_mute(a.id, True)
    assert win.track_panel.clear_m.isChecked()
    c.toggle_solo(a.id)
    assert not win.track_panel.clear_m.isChecked()
    c.set_mute(b.id, True)
    assert win.track_panel.clear_m.isChecked()
    win.track_panel.clear_m.click()
    assert not a.muted and not b.muted and a.soloed
    assert not win.track_panel.clear_m.isChecked()
    c.clear_solos()
    assert c.ws.global_tracks() == [a, b]


def test_named_track_export_ignores_mute_and_solo_in_whole_mode(win):
    from midi_interchange.core.export_smf import export_tracks
    ws = win.ctl.ws
    a, b = ws.tracks
    win.ctl.set_mute(a.id, True)
    assert len(export_tracks(ws, [a.id])) == 1
    win.ctl.set_mute(a.id, False)
    win.ctl.toggle_solo(b.id)
    assert len(export_tracks(ws, [a.id])) == 1


def test_whole_export_without_ids_still_filtered_by_mute_and_solo(win):
    from midi_interchange.core.export_smf import export_tracks
    ws = win.ctl.ws
    a, b = ws.tracks
    win.ctl.set_mute(a.id, True)
    assert len(export_tracks(ws)) == 1
    win.ctl.set_mute(a.id, False)
    win.ctl.toggle_solo(b.id)
    assert len(export_tracks(ws)) == 1
