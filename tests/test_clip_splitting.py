"""Non-destructive splits and the modifier gestures that expose them."""
from fractions import Fraction as F

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

from test_clip_trims import (app, win, ws, clip_of, abs_times, gesture)
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.session import Session, encode, decode
from midi_interchange.core.document import Workspace
from midi_interchange.core.ranges import Range
from helpers import notes_of, reparse, track_by_name


@pytest.mark.parametrize('start,end,offset,cut', [(0, 8, 0, F(2)), (1, 7, 3, F(6)),
                                                (2, 6, -2, F(3, 2))])
def test_split_preserves_source_and_outer_trims(ws, start, end, offset, cut):
    c = clip_of(ws)
    c.trim_start, c.trim_end, c.offset = F(start), F(end), F(offset)
    original = (c.id, c.events, c.length, c.offset, c.source_id, c.name)
    right = ws.split_clip(c.id, cut)
    assert (c.start, c.end, right.start, right.end) == (start + offset, cut, cut, end + offset)
    assert (c.id, c.events, c.length, c.offset, c.source_id, c.name) == original
    assert right.events is c.events and right.id != c.id
    assert right.offset == c.offset and right.length == c.length
    assert ws.split_clip(right.id, (right.start + right.end) / 2)
    ws.restore_clip(c.id)
    assert (c.trim_start, c.trim_end) == (0, 8)
    assert right.start == cut


@pytest.mark.parametrize('cut', [F(-1), F(0), F(8), F(9), F(1, 960)])
def test_invalid_split_is_atomic(ws, cut):
    before = ws.snapshot()
    assert ws.split_clip(clip_of(ws).id, cut) is None
    assert ws.snapshot() == before
    assert ws.split_clip('missing', F(2)) is None


def test_controller_snap_undo_and_noop(win):
    ctl = win.ctl
    c = clip_of(ctl.ws)
    before = ctl.ws.snapshot()
    notifications = []
    ctl.tracksChanged.connect(lambda: notifications.append(True))
    depth = len(ctl._undo)
    assert ctl.split_clip(c.id, F(1, 10)) is None
    assert len(ctl._undo) == depth and not notifications
    right_id = ctl.split_clip(c.id, F(21, 10))
    after = ctl.ws.snapshot()
    assert c.end == 2 and len(ctl._undo) == depth + 1 and len(notifications) == 1
    ctl.undo()
    assert ctl.ws.snapshot() == before
    ctl.redo()
    assert ctl.ws.snapshot() == after
    assert ctl.split_clip(right_id, F(31, 10), True)
    assert ctl.ws.find_clip(right_id)[1].end == F(31, 10)


@pytest.mark.parametrize('mode', list(ExportMode))
@pytest.mark.parametrize('partial', [True, False])
def test_export_seam_and_session(ws, mode, partial):
    c = clip_of(ws)
    right = ws.split_clip(c.id, F(2))
    ws.tracks[0].export_channel = 10
    # A second, excluded track verifies locked range track choices survive.
    duplicate = ws.duplicate_clip(right.id, offset=right.start)
    other = ws.new_track_for_clip(duplicate.id)
    other.name = 'Excluded'
    other.muted = True
    ws.ranges = [Range(F(0), F(8), 'Part', excluded={other.id}, track_locked=True)]
    opts = ExportOptions(mode=mode, partial_notes=partial)
    restored = Workspace()
    restored.restore(decode(encode(Session(ws.snapshot(), {}))).workspace)
    assert restored.tracks[0].clips[0].events is restored.tracks[0].clips[1].events
    for workspace in (ws, restored):
        out = reparse(build_exports(workspace, opts)[0].midi)
        assert not any(m.type == 'track_name' and m.name == 'Excluded' for t in out.tracks for m in t)
        trk = track_by_name(out, 'Lead')
        notes = [(s, e, p) for s, e, _ch, p in notes_of(trk, out.ticks_per_beat)]
        assert (F(0), F(2), 60) in notes
        assert ((F(2), F(3), 60) in notes) == partial
        assert all(m.channel == 9 for m in trk if hasattr(m, 'channel'))
        at_seam = [(m.type, getattr(m, 'note', None)) for _, m in
                   abs_times(trk, out.ticks_per_beat, 'note_off') if _ == 2]
        assert ('note_off', 60) in at_seam
        tick = 0
        seam = []
        for m in trk:
            tick += m.time
            if tick == 2 * out.ticks_per_beat and m.type in ('note_on', 'note_off') and m.note == 60:
                seam.append(m.type)
        assert seam == (['note_off', 'note_on'] if partial else ['note_off'])
        assert len([m for m in trk if m.type == 'lyrics' and m.text == 'a']) == 1
        assert len([m for m in trk if m.type == 'lyrics' and m.text == 'b']) == 1


def point(tl, time):
    return QPoint(round(tl.x_of(time)), tl.header_h() + tl.lane_h // 2)


def test_split_click_overrides_range_edge_and_drag_does_not_repeat(win):
    tl, ctl = win.timeline, win.ctl
    ctl.add_range(F(2), F(6))
    p = point(tl, 2)
    gesture(tl, p, point(tl, 5), Qt.ControlModifier)
    assert [(c.start, c.end) for c in ctl.ws.tracks[0].clips] == [(0, 2), (2, 8)]
    assert [(r.start, r.end) for r in ctl.ws.ranges] == [(2, 6)]
    ctl.undo()
    assert len(ctl.ws.tracks[0].clips) == 1


def test_shift_split_and_invalid_split(win):
    tl, ctl = win.timeline, win.ctl
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.ControlModifier, point(tl, .1))
    assert len(ctl.ws.tracks[0].clips) == 1 and not ctl.ws.ranges
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier, point(tl, 2.3))
    assert clip_of(ctl.ws).end == F(23, 10)


def test_copy_from_edge_uses_copy_cursor_and_does_not_trim(win):
    tl, ctl = win.timeline, win.ctl
    p = point(tl, 8) - QPoint(1, 0)
    mods = Qt.AltModifier | Qt.ControlModifier
    tl._update_cursor(p, mods)
    assert tl.viewport().cursor().pixmap().cacheKey() == tl._copy_cursor.pixmap().cacheKey()
    gesture(tl, p, point(tl, 10), mods)
    assert len(ctl.ws.tracks[0].clips) == 2
    assert all(not c.is_trimmed for c in ctl.ws.tracks[0].clips)
    ctl.undo()
    assert len(ctl.ws.tracks[0].clips) == 1


def test_stationary_pointer_modifiers_and_preview_cleanup(win):
    tl = win.timeline
    tl._pointer = point(tl, 2.3)
    tl.eventFilter(tl, QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier))
    assert tl._split_preview == (clip_of(win.ctl.ws).id, F(2))
    assert tl.viewport().cursor().pixmap().cacheKey() == tl._scissors_cursor.pixmap().cacheKey()
    tl.eventFilter(tl, QKeyEvent(QEvent.KeyPress, Qt.Key_Shift, Qt.ControlModifier | Qt.ShiftModifier))
    assert tl._split_preview[1] == F(23, 10)
    tl.eventFilter(tl, QKeyEvent(QEvent.KeyPress, Qt.Key_Alt, Qt.ControlModifier | Qt.AltModifier))
    assert tl._split_preview is None
    tl.eventFilter(tl, QKeyEvent(QEvent.KeyRelease, Qt.Key_Alt, Qt.ControlModifier))
    assert tl._split_preview is not None
    tl.leaveEvent(QEvent(QEvent.Leave))
    assert tl._split_preview is None


def test_real_key_events_update_stationary_preview(win):
    tl = win.timeline
    tl._pointer = point(tl, 2.3)
    tl.setFocus()
    QTest.keyPress(tl, Qt.Key_Control)
    assert tl._split_preview is not None
    QTest.keyRelease(tl, Qt.Key_Control)
    assert tl._split_preview is None


def test_modified_double_click_does_not_edit_a_range(win):
    tl, ctl = win.timeline, win.ctl
    ctl.add_range(F(1), F(6))
    edits = []
    tl.rangeEditRequested.connect(edits.append)
    QTest.mouseDClick(tl.viewport(), Qt.LeftButton, Qt.ControlModifier, point(tl, 3))
    assert not edits
    assert len(ctl.ws.tracks[0].clips) == 2


@pytest.mark.parametrize('cut', [F(3), F(4), F(6)])
def test_notes_and_lyrics_exactly_at_seam(ws, cut):
    c = clip_of(ws)
    assert ws.split_clip(c.id, cut)
    out = reparse(build_exports(ws, ExportOptions(mode=ExportMode.WHOLE))[0].midi)
    trk = track_by_name(out, 'Lead')
    notes = [(s, e, p) for s, e, _ch, p in notes_of(trk, out.ticks_per_beat)]
    expected = [(F(0), F(3), 60), (F(3), F(4), 62), (F(5), F(7), 64), (F(7), F(8), 65)]
    if cut == 6:
        expected[2:3] = [(F(5), F(6), 64), (F(6), F(7), 64)]
    assert notes == expected
    assert [(t, m.text) for t, m in abs_times(trk, out.ticks_per_beat, 'lyrics')] == [(F(1), 'a'), (F(6), 'b')]


def test_preview_tracks_zoom_and_scroll(win):
    tl, ctl = win.timeline, win.ctl
    tl._pointer = point(tl, 4)
    tl._pointer_mods = Qt.ControlModifier
    tl._refresh_pointer()
    assert tl._split_preview[1] == 4
    tl.set_zoom(40, 0)
    assert tl._split_preview[1] == 2
    tl.horizontalScrollBar().setValue(40)
    assert tl._split_preview[1] == 3
    ctl.delete_clip(clip_of(ctl.ws).id)
    assert tl._split_preview is None


def test_split_halves_move_restore_copy_delete_independently(ws):
    left = clip_of(ws)
    right = ws.split_clip(left.id, F(2))
    ws.move_clip_to_track(right.id, ws.tracks[0].id, F(10))
    assert (left.start, left.end) == (0, 2)
    assert (right.start, right.end) == (10, 16)
    ws.restore_clip(right.id)
    assert (right.start, right.end) == (8, 16)
    assert left.end == 2
    copied = ws.duplicate_clip(left.id)
    assert copied.events is left.events and (copied.start, copied.end) == (2, 4)
    ws.delete_clip(left.id)
    assert ws.find_clip(right.id) and ws.find_clip(copied.id)


@pytest.mark.parametrize('copy', [False, True])
@pytest.mark.parametrize('new_track', [False, True])
def test_shift_move_copy_uses_original_track_and_time(win, copy, new_track):
    tl, ctl = win.timeline, win.ctl
    source = ctl.ws.tracks[0]
    original = source.clips[0]
    duplicate = ctl.ws.duplicate_clip(original.id, offset=F(0))
    ctl.ws.new_track_for_clip(duplicate.id)
    ctl.tracksChanged.emit()
    before = ctl.ws.snapshot()
    mods = Qt.AltModifier | Qt.ShiftModifier
    if copy:
        mods |= Qt.ControlModifier
    p = point(tl, 2)
    QTest.mousePress(tl.viewport(), Qt.LeftButton, mods, p)
    tl._drag_to(tl.x_of(4.3), True, p.y())
    moving_id = tl._drag['cid']
    assert ctl.ws.find_clip(moving_id)[1].start == F(23, 10)
    if copy:
        assert original.start == 0 and moving_id != original.id
    dest_y = tl.lane_top(len(ctl.ws.tracks) if new_track else 1) + tl.lane_h // 2
    tl._drag_to(tl.x_of(5.7), True, dest_y)
    dest, moving = ctl.ws.find_clip(moving_id)
    assert dest.id != source.id and moving.start == 0
    # Remaining on that destination must keep using the original track as reference.
    tl._drag_to(tl.x_of(6.4), True, tl.lane_top(ctl.ws.tracks.index(dest)) + tl.lane_h // 2)
    assert moving.start == 0
    tl._drag_to(tl.x_of(4.3), True, p.y())
    assert ctl.ws.find_clip(moving_id)[0].id == source.id and moving.start == F(23, 10)
    tl._drag_to(tl.x_of(4.3), False, p.y())
    assert moving.start == 2
    QTest.mouseRelease(tl.viewport(), Qt.LeftButton, Qt.AltModifier, p)
    ctl.undo()
    assert ctl.ws.snapshot() == before
