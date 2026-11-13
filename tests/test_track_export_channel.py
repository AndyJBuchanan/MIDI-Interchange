"""Output-only channel mapping and the colour/channel header controls."""
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QDrag
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QColorDialog, QToolButton

from helpers import conductor, note, smf, track
from test_ui_assembly import app, win
from midi_interchange.core.export_smf import ExportMode
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui.export_panel import start_file_drag
from midi_interchange.ui.track_panel import channel_text_color


@pytest.fixture
def mixed(win):
    c = win.ctl
    c.new_document()
    for channel in (0, 3):
        events = [(0, mido.Message('program_change', channel=channel, program=5)),
                  (0, mido.Message('control_change', channel=channel, control=7, value=91)),
                  (0, mido.Message('pitchwheel', channel=channel, pitch=123)),
                  (0, mido.Message('aftertouch', channel=channel, value=50)),
                  (480, mido.Message('polytouch', channel=channel, note=60, value=45)),
                  (480, mido.Message('sysex', data=(1, 2, 3))),
                  (480, mido.MetaMessage('lyrics', text='hello')),
                  *note(channel, 60 + channel, 0, 4 * 480)]
        c.import_payloads([Payload(f'{channel}.mid', smf([conductor(480), track(events, f'Part {channel}')]))])
    a, b = c.ws.tracks
    c.ws.merge_tracks(b.id, a.id)
    QApplication.processEvents()
    return win, a.id


def midi_messages(midi):
    return [[m.dict() for m in tr] for tr in midi.tracks]


@pytest.mark.parametrize('mode', list(ExportMode))
@pytest.mark.parametrize('channel', [1, 10, 16])
def test_mapping_through_save_and_drag_keeps_sources_and_other_fields(mixed, mode, channel, tmp_path, monkeypatch):
    w, tid = mixed
    c = w.ctl
    t = c.ws.track(tid)
    source = [[e.msg.copy() for e in clip.events] for clip in t.clips]
    for clip in t.clips:
        c.ws.trim_clip(clip.id, 'start', F(1))
        c.ws.trim_clip(clip.id, 'end', F(3))
    c.add_range(F(1), F(3))
    c.set_export_mode(mode)
    baseline = c.build_exports()[0].midi
    assert {m.channel for tr in baseline.tracks for m in tr if hasattr(m, 'channel')} == {0, 3}
    assert any(m.type == 'note_off' for tr in baseline.tracks for m in tr)
    c.set_export_channel(tid, channel)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'saved.mid'), ''))
    w.save_midi()
    from midi_interchange.interchange import drag_export
    monkeypatch.setattr(drag_export, '_DIR', str(tmp_path / 'drag'))
    dragged = []
    monkeypatch.setattr(QDrag, 'exec', lambda self, *a: dragged.extend(u.toLocalFile() for u in self.mimeData().urls()) or Qt.CopyAction)
    start_file_drag(w.export_panel, c, None, pytest.fail, lambda paths: None)
    for path in [tmp_path / 'saved.mid', *dragged]:
        actual = mido.MidiFile(str(path))
        # Only channel numbers may change; event ordering, timing and metadata match.
        expected = midi_messages(baseline)
        for tr in expected:
            for msg in tr:
                if 'channel' in msg:
                    msg['channel'] = channel - 1
        assert midi_messages(actual) == expected
    assert [[e.msg for e in clip.events] for clip in t.clips] == source
    c.set_export_channel(tid, None)
    assert midi_messages(c.build_exports()[0].midi) == midi_messages(baseline)


def test_header_popup_and_undo(win, monkeypatch):
    c = win.ctl
    t = c.ws.tracks[0]
    h = win.track_panel.header(t.id)
    QApplication.processEvents()
    assert h.color_btn.size() == h.mute_btn.size() == h.solo_btn.size()
    assert h.solo_btn.x() == h.mute_btn.x() + h.mute_btn.width()
    assert h.mute_btn.x() > h.color_btn.x() + h.color_btn.width()
    p = win.track_panel
    assert p.clear_s.x() == p.clear_m.x() + p.clear_m.width()
    assert h.color_btn.text() == ''
    before = len(c._undo)
    QTest.mouseClick(h.color_btn, Qt.LeftButton)
    menu = h._color_menu
    channels = next(a.menu() for a in menu.actions() if a.text() == 'Export MIDI channel')
    assert len(channels.actions()) == 17 and channels.actions()[0].isChecked()
    menu.close()
    channels.actions()[16].trigger()
    assert h.color_btn.text() == '16' and '16' in h.color_btn.toolTip()
    assert len(c._undo) == before + 1
    c.set_export_channel(t.id, 16)
    assert len(c._undo) == before + 1
    c.undo()
    assert h.color_btn.text() == ''
    c.redo()
    assert h.color_btn.text() == '16'
    color_before = c.ws.track(t.id).color
    monkeypatch.setattr(QColorDialog, 'getColor', lambda *a: QColor())
    h._pick_color()
    assert c.ws.track(t.id).color == color_before and len(c._undo) == before + 1
    h._choose_color(menu, '#ffffff')
    assert c.ws.track(t.id).export_channel == 16 and '#000000' in h.color_btn.styleSheet()
    c.undo()
    assert c.ws.track(t.id).color == color_before and h.color_btn.text() == '16'
    h._show_color_menu()
    QTest.keyClick(h._color_menu, Qt.Key_Escape)
    assert len(c._undo) == before + 1
    c.set_export_channel(t.id, None)
    assert h.color_btn.text() == ''


@pytest.mark.parametrize('bad', [0, 17, -1, True, 1.5, '2'])
def test_invalid_channel_creates_no_undo(win, bad):
    c = win.ctl
    before = len(c._undo)
    with pytest.raises(ValueError):
        c.set_export_channel(c.ws.tracks[0].id, bad)
    assert len(c._undo) == before


def test_destination_track_controls_moved_copied_clips_and_new_tracks_default(win):
    c = win.ctl
    a, b = c.ws.tracks
    c.set_export_channel(a.id, 16)
    c.set_export_channel(b.id, 10)
    assert a.copy().export_channel == 16
    cid = c.duplicate_clip(a.clips[0].id)
    c.ws.move_clip_to_track(cid, b.id)
    assert {m.channel for m in c.build_exports([b.id])[0].midi.tracks[1] if hasattr(m, 'channel')} == {9}
    c.ws.move_clip_to_track(a.clips[0].id, b.id)
    assert b.export_channel == 10
    new = c.ws.new_track_for_clip(cid, like=b)
    assert new.export_channel is None
    c.import_payloads([Payload('new.mid', smf([track(note(5, 60, 0, 480), 'New')]))])
    assert c.ws.tracks[-1].export_channel is None


def test_channel_text_contrast():
    assert channel_text_color(QColor('#ffff00')) == '#000000'
    assert channel_text_color(QColor('#ffffff')) == '#000000'
    assert channel_text_color(QColor('#000080')) == '#ffffff'
