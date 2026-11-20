"""Controller display (docs/plans/controller-display.md): the pure line builder, the picker, the mode
and style buttons, the track's controller box, the lane layout, painting, and the guarantee that it is
display only: export, save and drag-out bytes never change."""
import time
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QFileDialog

from helpers import cc, conductor, load, note, smf, to_bytes, track
from test_ui_assembly import app, win
from midi_interchange.core import controllers as ctlr
from midi_interchange.core.export_smf import ExportMode, audible_events
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui import timeline as timeline_module
from midi_interchange.ui.export_panel import start_file_drag
from midi_interchange.ui.timeline import MAX_PPB, MIN_PPB, controller_polyline

BEAT = 480


def pb(value, ch=0):
    return mido.Message('pitchwheel', channel=ch, pitch=value)


def at(value, ch=0):
    return mido.Message('aftertouch', channel=ch, value=value)


def clip_of(events, name='T'):
    """The first clip of a one-track workspace built from (tick, message) events; returns (ws, clip)."""
    ws = load(smf([conductor(BEAT), track(events, name)]))
    return ws, ws.tracks[0].clips[0]


def line(clip, key, channel=None):
    ln = ctlr.controller_points(clip, key, channel)
    return None if ln is None else ln.series


def import_parts(ctl, **parts):
    """One imported file per keyword: name=events (ticks at 480 PPQ)."""
    for name, events in parts.items():
        ctl.import_payloads([Payload(f'{name}.mid', smf([conductor(BEAT), track(events, name)]))])
    QApplication.processEvents()


PAD = [*note(0, 60, 0, 4 * BEAT), (0, cc(0, 1, 10)), (BEAT, cc(0, 1, 100)), (2 * BEAT, cc(0, 1, 40)),
       (0, cc(0, 7, 90)), (0, pb(0)), (2 * BEAT, pb(4096)), (0, cc(0, 0, 3)), (0, cc(0, 121, 0))]
LEAD = [*note(0, 64, 0, 4 * BEAT), (BEAT, at(40)), (0, cc(0, 64, 127)), (0, cc(0, 20, 5)), (0, cc(0, 32, 4)),
        (0, mido.Message('polytouch', channel=0, note=64, value=30))]


@pytest.fixture
def cw(win):
    """The shared window, emptied, then Pad (CC1, CC7, pitch bend) and Lead (aftertouch, CC20, CC64)."""
    win.ctl.new_document()
    import_parts(win.ctl, Pad=PAD, Lead=LEAD)
    pad, lead = win.ctl.ws.tracks
    return win, pad, lead


def combo_texts(w):
    return [w.controller_combo.itemText(i) for i in range(w.controller_combo.count())]


# ---------------------------------------------------------------- pure: what is listed and how it is named

def test_order_labels_and_short_labels():
    ws, clip = clip_of([*note(0, 60, 0, BEAT), (0, cc(0, 64, 1)), (0, cc(0, 7, 1)), (0, cc(0, 20, 1)),
                        (0, cc(0, 1, 1)), (0, at(1)), (0, pb(1)), (0, cc(0, 11, 1)), (0, cc(0, 10, 1))])
    keys = ctlr.clip_controllers(clip)
    assert keys == ['pb', 'at', 'cc1', 'cc7', 'cc10', 'cc11', 'cc20', 'cc64']
    assert [ctlr.label(k) for k in keys] == ['Pitch Bend', 'Aftertouch', '1 Mod Wheel', '7 Volume', '10 Pan',
                                             '11 Expression', 'CC 20', '64 Sustain']
    assert [ctlr.short_label(k) for k in keys] == ['PB', 'AT', 'CC1', 'CC7', 'CC10', 'CC11', 'CC20', 'CC64']


def test_controllers_that_are_not_curves_are_not_listed():
    excluded = [0, 32, 6, 38, 96, 97, 98, 99, 100, 101, *range(120, 128)]
    ws, clip = clip_of([*note(0, 60, 0, BEAT), *((0, cc(0, n, 5)) for n in excluded),
                        (0, mido.Message('polytouch', channel=0, note=60, value=9))])
    assert ctlr.clip_controllers(clip) == []
    assert not any(ctlr.is_valid_key(f'cc{n}') for n in excluded)
    assert not ctlr.is_valid_key('pk') and not ctlr.is_valid_key('cc128') and not ctlr.is_valid_key('cc07')


def test_values_scale_and_pitch_bend_centres():
    ws, clip = clip_of([*note(0, 60, 0, 4 * BEAT), (0, cc(0, 7, 0)), (BEAT, cc(0, 7, 127)),
                        (0, pb(0)), (BEAT, pb(-8192)), (2 * BEAT, pb(8191))])
    times, values = line(clip, 'cc7')
    assert (times, values) == ([0.0, 1.0], [0.0, 1.0])
    assert line(clip, 'pb')[1] == [0.5, 0.0, 16383 / 16384]


def test_untrimmed_start_has_no_value_before_the_first_event():
    ws, clip = clip_of([*note(0, 60, 0, 4 * BEAT), (BEAT, cc(0, 7, 50)), (2 * BEAT, cc(0, 7, 60))])
    ln = ctlr.controller_points(clip, 'cc7', None)
    assert ln.carried is None and ln.times == (1.0, 2.0)


def test_step_and_joined_polylines_hold_to_the_clip_end():
    y_of = lambda v: 1 - v
    times, values = [0.0, 1.0, 2.0], [0.2, 0.8, 0.5]
    steps = controller_polyline(times, values, 0.0, 10.0, 0.0, 100.0, False, 50.0, 1000, y_of)
    assert steps == [(0, y_of(.2)), (10, y_of(.2)), (10, y_of(.8)), (20, y_of(.8)), (20, y_of(.5)), (50, y_of(.5))]
    joined = controller_polyline(times, values, 0.0, 10.0, 0.0, 100.0, True, 50.0, 1000, y_of)
    assert joined == [(0, y_of(.2)), (10, y_of(.8)), (20, y_of(.5)), (50, y_of(.5))]
    # a view that starts after the first points begins from the point before it
    late = controller_polyline(times, values, 0.0, 10.0, 1.5, 100.0, False, 50.0, 1000, y_of)
    assert late[0] == (10, y_of(.8))


def test_trimmed_start_carries_the_value_export_writes():
    events = [*note(0, 60, 0, 6 * BEAT), *((i * BEAT, cc(0, 7, 10 * (i + 1))) for i in range(5))]
    ws, clip = clip_of(events)
    ws.trim_clip(clip.id, 'start', F(3, 2))
    ws.trim_clip(clip.id, 'end', F(7, 2))
    ln = ctlr.controller_points(clip, 'cc7', 0)
    assert ln.carried == 20 / 127 and ln.start == 1.5
    times, values = ln.series
    assert [(t + float(clip.offset), round(v * 127)) for t, v in zip(times, values)] == \
        [(1.5, 20), (2.0, 30), (3.0, 40)]                        # nothing from beat 4: past the trimmed end
    exported = sorted(((float(e.time), e.msg.value) for e in audible_events(clip) if e.msg.type == 'control_change'),
                      key=lambda x: x[0])
    assert exported == [(1.5, 20), (2.0, 30), (3.0, 40)]


def test_trimmed_start_carry_on_merged_channels_is_the_latest_value():
    events = [*note(0, 60, 0, 4 * BEAT), *note(3, 62, 0, 4 * BEAT), (0, cc(0, 7, 10)), (BEAT, cc(3, 7, 99)),
              (3 * BEAT, cc(0, 7, 11))]
    ws, clip = clip_of(events)
    ws.trim_clip(clip.id, 'start', F(3, 2))
    assert ctlr.controller_points(clip, 'cc7', 0).carried == 10 / 127
    assert ctlr.controller_points(clip, 'cc7', 3).carried == 99 / 127
    merged = ctlr.controller_points(clip, 'cc7', None)
    last_written = [e.msg.value for e in audible_events(clip) if e.msg.type == 'control_change' and e.time == F(3, 2)][-1]
    assert round(merged.carried * 127) == last_written == 99


def test_a_controller_only_in_the_trimmed_away_end_is_not_listed():
    events = [*note(0, 60, 0, 4 * BEAT), (0, cc(0, 1, 5)), (3 * BEAT, cc(0, 7, 5)), (3 * BEAT, at(5))]
    ws, clip = clip_of(events)
    assert ctlr.clip_controllers(clip) == ['at', 'cc1', 'cc7']
    ws.trim_clip(clip.id, 'end', F(2))
    assert ctlr.clip_controllers(clip) == ['cc1']
    assert ctlr.controller_points(clip, 'cc7', None) is None


def test_muted_clips_still_list_their_controllers():
    ws, clip = clip_of([*note(0, 60, 0, 4 * BEAT), (0, cc(0, 7, 5)), (3 * BEAT, cc(0, 1, 5))])
    clip.muted = True
    ws.trim_clip(clip.id, 'end', F(2))
    assert ctlr.clip_controllers(clip) == ['cc7']


def test_two_channels_give_one_line_each_or_one_merged_line():
    ws, clip = clip_of([*note(0, 60, 0, 4 * BEAT), *note(3, 62, 0, 4 * BEAT), (0, cc(0, 7, 10)), (BEAT, cc(3, 7, 99)),
                        (2 * BEAT, cc(0, 7, 20))])
    own = ctlr.controller_lines(clip, 'cc7', merged=False)
    assert [ln.times for ln in own] == [(0.0, 2.0), (1.0,)]
    merged = ctlr.controller_lines(clip, 'cc7', merged=True)
    assert len(merged) == 1 and merged[0].times == (0.0, 1.0, 2.0)


def test_the_timeline_merges_channels_only_when_an_export_channel_is_set(cw):
    w, pad, lead = cw
    c = w.ctl
    c.new_document()
    import_parts(c, Two=[*note(0, 60, 0, 4 * BEAT), *note(3, 62, 0, 4 * BEAT), (0, cc(0, 7, 10)), (BEAT, cc(3, 7, 99))])
    t = c.ws.tracks[0]
    assert len(w.timeline.controller_lines_for(t, t.clips[0], 'cc7')) == 2
    c.set_export_channel(t.id, 5)
    assert len(w.timeline.controller_lines_for(t, t.clips[0], 'cc7')) == 1
    c.set_export_channel(t.id, None)
    assert len(w.timeline.controller_lines_for(t, t.clips[0], 'cc7')) == 2


# ---------------------------------------------------------------- the picker

def test_picker_defaults_to_off_and_lists_the_union_in_order(cw):
    w, pad, lead = cw
    assert w.ctl.controller_show is None and w.controller_combo.currentData() is None
    assert combo_texts(w) == ['Off', 'Pitch Bend', 'Aftertouch', '1 Mod Wheel', '7 Volume', 'CC 20', '64 Sustain']
    assert [w.controller_combo.itemData(i) for i in range(w.controller_combo.count())] == \
        [None, 'pb', 'at', 'cc1', 'cc7', 'cc20', 'cc64']
    w.ctl.new_document()
    assert combo_texts(w) == ['Off']


def test_picking_sets_the_view_and_the_view_menu_follows(cw):
    w, pad, lead = cw
    w.controller_combo.setCurrentIndex(4)
    assert w.ctl.controller_show == 'cc7'
    checked = [a.text() for a in w.controller_menu.actions() if a.isChecked()]
    assert checked == ['7 Volume']
    assert [a.text() for a in w.controller_menu.actions()] == combo_texts(w)
    # and the other way: the menu choice moves the toolbar list
    next(a for a in w.controller_menu.actions() if a.text() == 'Aftertouch').trigger()
    assert w.ctl.controller_show == 'at' and w.controller_combo.currentData() == 'at'
    next(a for a in w.controller_menu.actions() if a.text() == 'Off').trigger()
    assert w.ctl.controller_show is None and w.controller_combo.currentIndex() == 0


def test_picker_refreshes_after_delete_trim_undo_and_redo(cw):
    w, pad, lead = cw
    c = w.ctl
    c.remove_track(lead.id)
    assert combo_texts(w) == ['Off', 'Pitch Bend', '1 Mod Wheel', '7 Volume']
    c.undo()
    assert 'Aftertouch' in combo_texts(w) and '64 Sustain' in combo_texts(w)
    c.redo()
    assert 'Aftertouch' not in combo_texts(w)
    c.undo()
    c.checkpoint()                                            # a trim drag checkpoints once, at its start
    c.trim_clip_live(lead.clips[0].id, 'end', F(1))           # the aftertouch at beat 1 is trimmed away
    assert 'Aftertouch' not in combo_texts(w) and '64 Sustain' in combo_texts(w)
    c.undo()
    assert 'Aftertouch' in combo_texts(w)


def test_a_choice_with_no_data_stays_greyed_and_marked_and_returns_with_undo(cw):
    w, pad, lead = cw
    c = w.ctl
    c.set_controller_show('cc64')
    c.remove_track(lead.id)
    i = w.controller_combo.currentIndex()
    assert w.controller_combo.itemText(i) == '64 Sustain (none in workspace)'
    assert not w.controller_combo.model().item(i).isEnabled()
    assert c.controller_show == 'cc64'
    assert not next(a for a in w.controller_menu.actions() if a.isChecked()).isEnabled()
    c.undo()
    i = w.controller_combo.currentIndex()
    assert w.controller_combo.itemText(i) == '64 Sustain' and w.controller_combo.model().item(i).isEnabled()
    assert c.controller_show == 'cc64'


# ---------------------------------------------------------------- the mode and style buttons

def test_buttons_are_disabled_while_nothing_is_shown(cw):
    w, pad, lead = cw
    assert not w.controller_mode_btn.isEnabled() and not w.controller_style_btn.isEnabled()
    w.ctl.set_controller_show('cc1')
    assert w.controller_mode_btn.isEnabled() and w.controller_style_btn.isEnabled()
    w.ctl.set_controller_show(None)
    assert not w.controller_mode_btn.isEnabled()
    w.ctl.set_track_controller(pad.id, 'none')            # an override to None shows nothing
    assert not w.controller_mode_btn.isEnabled()
    w.ctl.set_track_controller(pad.id, 'cc7')             # a track showing its own controller counts
    assert w.controller_mode_btn.isEnabled() and w.controller_style_btn.isEnabled()
    w.ctl.undo()
    w.ctl.undo()
    assert not w.controller_mode_btn.isEnabled()


def test_buttons_toggle_and_tooltips_follow_the_setting(cw):
    w, pad, lead = cw
    w.ctl.set_controller_show('cc1')
    mode, style = w.controller_mode_btn, w.controller_style_btn
    assert not mode.isChecked() and not style.isChecked()
    assert mode.toolTip() == 'Controller in a lane under the notes. Click to draw it over the notes.'
    assert style.toolTip() == 'Controller drawn as steps. Click to join the points with lines.'
    mode.click()
    style.click()
    assert w.ctl.controller_overlay and w.ctl.controller_joined
    assert mode.toolTip() == 'Controller drawn over the notes. Click to draw it in a lane under the notes.'
    assert style.toolTip() == 'Controller joined with lines. Click to draw it as steps.'
    assert w.a_ctl_overlay.isChecked() and w.a_ctl_joined.isChecked()      # the View menu ticks follow
    w.a_ctl_overlay.trigger()
    w.a_ctl_joined.trigger()
    assert not w.ctl.controller_overlay and not w.ctl.controller_joined
    assert not mode.isChecked() and not style.isChecked()
    mode.click()
    mode.click()
    assert not w.ctl.controller_overlay


def test_mode_tooltip_has_no_short_lane_sentence_at_any_height(cw):
    w, pad, lead = cw
    w.ctl.set_controller_show('cc1')
    for h in (28, 40, 100):
        w.timeline.set_lane_height(h)
        assert w.controller_mode_btn.toolTip() == 'Controller in a lane under the notes. Click to draw it over the notes.'


def test_the_style_setting_reaches_the_painter(cw, monkeypatch):
    w, pad, lead = cw
    seen = []
    real = timeline_module.controller_polyline

    def spy(*args, **kw):
        seen.append(args[6])
        return real(*args, **kw)
    monkeypatch.setattr(timeline_module, 'controller_polyline', spy)
    w.ctl.set_controller_show('cc1')
    w.timeline.viewport().grab()
    assert seen and set(seen) == {False}
    seen.clear()
    w.ctl.set_controller_joined(True)
    w.timeline.viewport().grab()
    assert seen and set(seen) == {True}


def test_picker_mode_and_style_make_no_undo_step(cw):
    w, pad, lead = cw
    c = w.ctl
    before = (len(c._undo), len(c._redo))
    c.set_controller_show('cc1')
    c.set_controller_overlay(True)
    c.set_controller_joined(True)
    w.controller_combo.setCurrentIndex(2)
    c.set_controller_overlay(False)
    assert (len(c._undo), len(c._redo)) == before
    c.undo()
    c.redo()
    assert (c.controller_show, c.controller_overlay, c.controller_joined) == ('at', False, True)   # undo leaves view state


# ---------------------------------------------------------------- the track's controller box

def box_geom(header):
    return header.ctl_box.geometry()


def test_box_sits_under_the_delete_button_clear_of_the_info_text(cw):
    w, pad, lead = cw
    QApplication.processEvents()
    for t in (pad, lead):
        h = w.track_panel.header(t.id)
        h.layout().activate()
        box, rm = box_geom(h), h.remove_btn.geometry()
        assert h.ctl_box.isVisibleTo(h)
        assert box.top() >= rm.bottom()                              # under the cross
        assert box.right() == rm.right()                             # right-aligned with it
        assert h.rect().contains(box)                                # inside the header at the default height
        assert h.info.geometry().right() < box.left()                # clear of the info text
        assert h.info.geometry().top() < box.bottom() and h.info.geometry().bottom() >= box.top()   # on the info line


def test_box_is_hidden_in_short_lanes(cw):
    w, pad, lead = cw
    h = w.track_panel.header(pad.id)
    assert w.timeline.lane_h >= 45 and h.ctl_box.isVisibleTo(h)
    w.timeline.set_lane_height(40)
    QApplication.processEvents()
    assert not h.ctl_box.isVisibleTo(h)
    w.timeline.set_lane_height(70)
    QApplication.processEvents()
    assert h.ctl_box.isVisibleTo(h)


def is_red(h):
    from midi_interchange.ui import theme
    return theme.SOLO.name() in h.ctl_box.styleSheet()


def test_box_is_red_only_when_the_track_overrides_the_view(cw):
    w, pad, lead = cw
    c = w.ctl
    h = w.track_panel.header(pad.id)
    assert not is_red(h) and h.ctl_box.text() == ''                  # Off and following: an empty box
    c.set_controller_show('cc7')
    assert not is_red(h) and h.ctl_box.text() == 'CC7'
    c.set_controller_show('cc1')
    assert not is_red(h) and h.ctl_box.text() == 'CC1'               # the picker changes, still normal
    c.set_track_controller(pad.id, 'pb')
    assert is_red(h) and h.ctl_box.text() == 'PB'
    assert not is_red(w.track_panel.header(lead.id))                 # only that track
    c.set_track_controller(pad.id, 'none')
    assert is_red(h) and h.ctl_box.text() == '–'
    c.set_track_controller(pad.id, None)
    assert not is_red(h) and h.ctl_box.text() == 'CC1'


def test_box_label_and_tooltip(cw):
    w, pad, lead = cw
    h = w.track_panel.header(lead.id)
    w.ctl.set_controller_show('cc1')
    assert h.ctl_box.toolTip() == 'Controller: follows view (1 Mod Wheel)'
    w.ctl.set_controller_show(None)
    assert h.ctl_box.toolTip() == 'Controller: follows view (Off)'
    w.ctl.set_track_controller(lead.id, 'cc20')
    assert h.ctl_box.text() == 'CC20'
    assert h.ctl_box.toolTip() == 'Controller: CC 20 (this track; click to change)'
    w.ctl.set_track_controller(pad.id, 'cc7')
    assert w.track_panel.header(pad.id).ctl_box.toolTip() == 'Controller: 7 Volume (this track; click to change)'


def test_a_track_following_a_controller_it_lacks_is_dimmed_not_red(cw):
    w, pad, lead = cw
    w.ctl.set_controller_show('cc7')                                  # only Pad has CC7
    has, lacks = w.track_panel.header(pad.id), w.track_panel.header(lead.id)
    assert lacks.ctl_box.text() == 'CC7' and not is_red(lacks)
    assert lacks.ctl_box.styleSheet() != has.ctl_box.styleSheet()


def menu_state(h):
    return [(a.text(), a.isChecked()) for a in h._build_controller_menu().actions() if not a.isSeparator()]


def test_popup_lists_follow_none_then_this_tracks_controllers(cw):
    w, pad, lead = cw
    h = w.track_panel.header(pad.id)
    assert menu_state(h) == [('Follow view (Off)', True), ('None', False), ('Pitch Bend', False),
                             ('1 Mod Wheel', False), ('7 Volume', False)]
    w.ctl.set_controller_show('cc1')
    w.ctl.set_track_controller(pad.id, 'cc7')
    assert menu_state(h) == [('Follow view (1 Mod Wheel)', False), ('None', False), ('Pitch Bend', False),
                             ('1 Mod Wheel', False), ('7 Volume', True)]
    w.ctl.set_track_controller(pad.id, 'none')
    assert menu_state(w.track_panel.header(pad.id))[1] == ('None', True)
    assert [t for t, _c in menu_state(w.track_panel.header(lead.id))[2:]] == ['Aftertouch', 'CC 20', '64 Sustain']
    menu = h._build_controller_menu()
    assert [a.isSeparator() for a in menu.actions()][:3] == [False, False, True]


def test_choosing_in_the_popup_applies_it(cw):
    w, pad, lead = cw
    h = w.track_panel.header(pad.id)
    next(a for a in h._build_controller_menu().actions() if a.text() == '7 Volume').trigger()
    assert pad.controller == 'cc7' or w.ctl.ws.track(pad.id).controller == 'cc7'
    h = w.track_panel.header(pad.id)
    next(a for a in h._build_controller_menu().actions() if a.text().startswith('Follow view')).trigger()
    assert w.ctl.ws.track(pad.id).controller is None
    h._show_controller_menu()
    assert h._controller_menu is not None
    h._controller_menu.close()


def test_override_is_one_undo_step_and_undo_redo_restore_it_and_the_colour(cw):
    w, pad, lead = cw
    c = w.ctl
    h = lambda: w.track_panel.header(pad.id)
    before = len(c._undo)
    c.set_track_controller(pad.id, 'cc1')
    assert len(c._undo) == before + 1
    c.set_track_controller(pad.id, 'cc1')                             # the current value: no step
    assert len(c._undo) == before + 1
    c.set_track_controller(pad.id, 'none')
    assert len(c._undo) == before + 2
    c.undo()
    assert c.ws.track(pad.id).controller == 'cc1' and is_red(h()) and h().ctl_box.text() == 'CC1'
    c.undo()
    assert c.ws.track(pad.id).controller is None and not is_red(h())
    c.redo()
    c.redo()
    assert c.ws.track(pad.id).controller == 'none' and is_red(h()) and h().ctl_box.text() == '–'
    with pytest.raises(ValueError):
        c.set_track_controller(pad.id, 'cc0')
    with pytest.raises(ValueError):
        c.set_track_controller(pad.id, 'bogus')


def test_a_new_track_from_a_clip_move_follows_the_view_and_a_merged_override_goes_with_its_track(cw):
    w, pad, lead = cw
    c = w.ctl
    c.set_track_controller(pad.id, 'cc7')
    c.move_clip_to_track(pad.clips[0].id, None)                       # onto a new track
    new = next(t for t in c.ws.tracks if t.id not in (pad.id, lead.id))
    assert new.controller is None and new.id != pad.id
    c.set_track_controller(lead.id, 'cc20')
    c.merge_tracks(lead.id, new.id)
    assert c.ws.track(lead.id) is None and new.controller is None


def test_colour_box_menu_has_no_controller_entry(cw):
    w, pad, lead = cw
    menu = w.track_panel.header(pad.id)._build_color_menu()
    texts = [a.text() for a in menu.actions()] + [a.text() for sub in menu.actions() if sub.menu()
                                                  for a in sub.menu().actions()]
    assert not any('ontroller' in t for t in texts)
    assert [a.text() for a in menu.actions() if a.menu()] == ['Export MIDI channel']


# ---------------------------------------------------------------- lane layout

LANE_HEIGHTS = (28, 52, 68, 220)


def strip_px(lane_h):
    return max(10, round(0.3 * lane_h))


def rows(tl):
    return [tl.row_h(i) for i in range(len(tl.ctl.ws.tracks))]


def test_rows_are_equal_while_the_display_is_off(cw):
    """Existing tests compute positions as header_h + i * lane_h; this keeps that true."""
    w, pad, lead = cw
    tl = w.timeline
    for h in LANE_HEIGHTS:
        tl.set_lane_height(h)
        for i in range(2):
            assert tl.row_h(i) == h and tl.row_y(i) == i * h
            assert tl.lane_top(i) == tl.header_h() + i * h - tl.verticalScrollBar().value()
            assert tl.lane_at(tl.lane_top(i)) == i
        w.ctl.set_controller_show('cc7')
        w.ctl.set_controller_show(None)
        assert rows(tl) == [h, h]
    w.ctl.set_controller_show('cc7')
    w.ctl.set_controller_show(None)
    w.ctl.set_controller_overlay(True)
    assert rows(tl) == [tl.lane_h] * 2           # Off with nothing overridden, whatever the mode


def test_lane_mode_grows_only_tracks_that_show_and_have_the_controller(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    for h in LANE_HEIGHTS:                                            # no fallback at any height
        tl.set_lane_height(h)
        c.set_controller_show('cc7')                                  # only Pad has CC7
        assert rows(tl) == [h + strip_px(h), h], h
        c.set_controller_show('cc1')
        assert rows(tl) == [h + strip_px(h), h], h
        c.set_controller_show('cc64')                                 # only Lead
        assert rows(tl) == [h, h + strip_px(h)], h
        c.set_controller_show(None)


def test_overlay_mode_leaves_every_row_at_the_normal_height(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.set_controller_show('cc7')
    c.set_controller_overlay(True)
    for h in LANE_HEIGHTS:
        tl.set_lane_height(h)
        assert rows(tl) == [h, h]
        assert tl.track_layout(pad).overlay and not tl.track_layout(pad).strip
    c.set_controller_overlay(False)
    assert tl.row_h(0) == tl.lane_h + strip_px(tl.lane_h)


def test_overrides_decide_the_row_height(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    h = tl.lane_h
    c.set_controller_show('cc7')
    c.set_track_controller(pad.id, 'none')                            # to None: normal height
    assert rows(tl) == [h, h]
    c.set_track_controller(pad.id, 'cc20')                            # an override to a controller it lacks
    assert rows(tl) == [h, h]
    c.set_controller_show(None)                                       # picker Off, one track overrides
    c.set_track_controller(pad.id, 'pb')
    assert rows(tl) == [h + strip_px(h), h]
    c.set_track_controller(lead.id, 'at')
    assert rows(tl) == [h + strip_px(h)] * 2
    c.undo()
    assert rows(tl) == [h + strip_px(h), h]


def test_the_note_area_is_identical_with_the_display_off_in_lane_and_in_overlay(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    for h in LANE_HEIGHTS:
        tl.set_lane_height(h)
        c.set_controller_show(None)
        off = tl.track_layout(pad, 5)
        for key in ('cc7', 'cc64'):                                    # with data and without
            c.set_controller_show(key)
            for overlay in (False, True):
                c.set_controller_overlay(overlay)
                lay = tl.track_layout(pad, 5)
                assert (lay.note_top, lay.note_h) == (off.note_top, off.note_h), (h, key, overlay)
        c.set_controller_overlay(False)
    c.set_controller_show('cc7')
    lay = tl.track_layout(pad, 100)
    assert lay.strip and lay.strip_top == 100 + tl.lane_h and lay.strip_h == strip_px(tl.lane_h)
    assert not tl.track_layout(lead).strip


def test_the_overlay_fallback_is_gone():
    assert not hasattr(timeline_module, 'STRIP_MIN_AREA') and not hasattr(timeline_module, 'STRIP_GAP')
    assert 'fallback' not in timeline_module.TrackLayout.__dataclass_fields__


def many_tracks(w, n=12):
    """Pad and Lead plus n more tracks; every third one has CC1 (like Pad)."""
    w.ctl.new_document()
    for i in range(n):
        events = PAD if i % 3 == 0 else LEAD if i % 3 == 1 else [*note(0, 62, 0, BEAT)]
        import_parts(w.ctl, **{f'T{i}': events})
    w.resize(1000, 520)
    QApplication.processEvents()
    return w.ctl.ws.tracks


def test_row_geometry_agrees_across_unequal_rows(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    tracks = many_tracks(w)
    c.set_controller_show('cc1')                                      # Pad-like tracks only
    heights = rows(tl)
    assert len(set(heights)) == 2
    for scroll in (0, 70, 200):
        tl.verticalScrollBar().setValue(scroll)
        for i in range(len(tracks)):
            top = tl.lane_top(i)
            if top >= tl.header_h():                                  # rows under the ruler can't be pointed at
                assert tl.lane_at(top) == i
            if top + tl.row_h(i) - 1 >= tl.header_h():
                assert tl.lane_at(top + tl.row_h(i) - 1) == i
                assert tl.lane_at(top + tl.row_h(i)) in (i + 1, -1)
        assert tl.lane_top(len(tracks)) == tl.lane_top(len(tracks) - 1) + tl.row_h(len(tracks) - 1)
    vp = tl.viewport().height()
    assert tl.verticalScrollBar().maximum() == max(0, tl.header_h() + sum(heights) + 24 - vp)
    assert tl.content_rows_h() == sum(heights)
    assert tl.lane_at(tl.lane_top(len(tracks))) == -1


def assert_headers_follow_rows(w):
    tl, panel = w.timeline, w.track_panel
    QApplication.processEvents()
    for i, t in enumerate(w.ctl.ws.tracks):
        g = panel.header(t.id).geometry()
        assert (g.y(), g.height()) == (tl.row_y(i) - tl.verticalScrollBar().value(), tl.row_h(i)), i


def test_headers_follow_rows_after_every_kind_of_change(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    many_tracks(w)
    steps = [lambda: c.set_controller_show('cc1'),
             lambda: c.set_controller_overlay(True),
             lambda: c.set_controller_overlay(False),
             lambda: c.set_track_controller(c.ws.tracks[1].id, 'cc64'),
             lambda: c.undo(),
             lambda: c.redo(),
             lambda: tl.set_lane_height(46),
             lambda: tl.set_lane_height(120),
             lambda: tl.verticalScrollBar().setValue(97),
             lambda: c.set_controller_show('pb'),
             lambda: c.remove_track(c.ws.tracks[0].id)]
    for step in steps:
        step()
        assert_headers_follow_rows(w)
    tl.verticalScrollBar().setValue(tl.verticalScrollBar().maximum())
    assert_headers_follow_rows(w)


def top_track(tl):
    return tl.ctl.ws.tracks[tl.lane_at(tl.header_h())]


def test_the_track_at_the_top_stays_at_the_top_when_heights_change(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    tracks = many_tracks(w)
    tl.verticalScrollBar().setValue(3 * tl.lane_h + 20)                # track 3 at the top, 20 px into it
    tid = tracks[3].id

    def at_top():
        i = tl.lane_at(tl.header_h())
        return c.ws.tracks[i].id, tl.header_h() - tl.lane_top(i)
    assert at_top() == (tid, 20)
    c.set_controller_show('cc1')                                      # tracks 0, 3, 6, 9 grow
    assert at_top() == (tid, 20) and tl.row_y(3) == tl.row_h(0) + 2 * tl.lane_h
    c.set_controller_overlay(True)
    assert at_top() == (tid, 20) and tl.row_y(3) == 3 * tl.lane_h
    c.set_controller_overlay(False)
    c.set_track_controller(tracks[0].id, 'none')                       # a track above shrinks
    assert at_top() == (tid, 20)
    c.undo()
    assert at_top() == (tid, 20)
    c.set_controller_show('pb')
    assert at_top()[0] == tid
    c.set_controller_show(None)
    assert at_top() == (tid, 20) and tl.verticalScrollBar().value() == 3 * tl.lane_h + 20
    # the offset is clamped to the new height of the top track
    c.set_controller_show('cc1')
    tl.verticalScrollBar().setValue(tl.row_y(3) + tl.row_h(3) - 1)
    c.set_controller_show(None)
    assert at_top()[0] == tid and at_top()[1] <= tl.lane_h - 1


def test_a_lane_height_change_keeps_the_scroll_value(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    many_tracks(w)
    c.set_controller_show('cc1')
    tl.verticalScrollBar().setValue(90)
    tl.set_lane_height(100)
    assert tl.verticalScrollBar().value() == 90


def test_heights_hold_still_during_a_clip_drag_and_update_on_release(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    tracks = many_tracks(w)
    c.set_controller_show('cc1')
    src = next(t for t in tracks if 'cc1' in c.track_controllers(t))
    dst = next(t for t in tracks if 'cc1' not in c.track_controllers(t) and tracks.index(t) > tracks.index(src))
    before = rows(tl)
    clip = src.clips[0]
    tl.begin_drag()
    tl._drag = {'kind': 'clip', 'cid': clip.id, 'orig_off': clip.start, 'origin': src.copy(), 'copy': False,
                'grab': F(0), 'checkpointed': False}
    y = tl.lane_top(tracks.index(dst)) + 3                            # the destination row, by its frozen position
    tl._drag_clip(100.0, y, False)
    assert dst.clips and 'cc1' in c.track_controllers(dst)           # the data moved onto the destination
    assert tl.gesture_active and rows(tl) == before                   # but no row moved under the pointer
    assert tl.lane_at(y) == tracks.index(dst)
    assert_headers_follow_rows(w)
    tl._drag = None
    tl.end_drag()
    after = rows(tl)
    assert after != before and after[tracks.index(dst)] == tl.lane_h + strip_px(tl.lane_h)
    assert_headers_follow_rows(w)


def test_an_external_drag_holds_heights_and_a_new_track_is_the_normal_height(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.set_controller_show('cc1')
    before = rows(tl)
    tl.begin_drag(external=True)
    import_parts(c, Extra=PAD)                                        # a track appears mid-gesture
    during = rows(tl)
    assert during[:2] == before and during[2] == tl.lane_h
    tl.end_drag()
    assert rows(tl)[2] == tl.lane_h + strip_px(tl.lane_h)


def test_a_click_that_changes_nothing_leaves_the_scroll_alone(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    many_tracks(w)
    c.set_controller_show('cc1')
    tl.verticalScrollBar().setValue(55)
    tl.begin_drag()
    tl.end_drag()
    assert tl.verticalScrollBar().value() == 55


def test_drop_placement_and_the_drop_indicator_pick_the_right_row_below_a_tall_row(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.set_controller_show('cc64')                                     # Lead is the tall one (row 1); Pad is plain
    c.set_controller_show('cc1')                                      # now Pad (row 0) is tall, Lead is below it
    assert tl.row_h(0) > tl.row_h(1)
    y_lead = tl.lane_top(1) + 4                                       # in the old uniform geometry this is still Pad
    assert y_lead < tl.header_h() + 2 * tl.lane_h and tl.lane_at(y_lead) == 1
    vp_pt = QPointF(300, y_lead)
    win_pt = w.mapFromGlobal(tl.viewport().mapToGlobal(vp_pt.toPoint()))
    placement, lane = w.drop_placement(QPointF(win_pt), True)
    assert lane == 1 and placement.target_track_id == lead.id
    y_in_strip = tl.lane_top(0) + tl.lane_h + 3                       # inside Pad's strip: still Pad
    assert tl.lane_at(y_in_strip) == 0
    tl.set_drop_indicator((0, F(1), 'x'))
    assert not tl.viewport().grab().isNull()
    panel_pt = w.track_panel.mapTo(w, QPoint(10, tl.lane_top(1) + 4))
    placement, lane = w.drop_placement(QPointF(panel_pt), True)       # dropped on the header column
    assert lane == 1 and placement.target_track_id == lead.id
    tl.set_drop_indicator(None)


def test_a_grip_reorder_below_a_tall_row_gives_the_right_index(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    many_tracks(w, 6)
    c.set_controller_show('cc1')                                      # rows 0 and 3 are tall
    panel = w.track_panel
    n = len(c.ws.tracks)

    def global_at(content_y):
        return panel.mapToGlobal(QPoint(10, tl.header_h() + content_y - panel._voffset))
    offs = tl._ensure_rows()
    assert offs[1] - offs[0] > tl.lane_h
    assert panel._index_at_global(global_at(offs[1] - 3)) == 1       # near the bottom of the tall row 0
    assert panel._index_at_global(global_at(offs[0] + 3)) == 0
    mid = offs[0] + (offs[1] - offs[0]) // 2 + 3
    assert panel._index_at_global(global_at(mid)) == 1               # the nearer boundary of a tall row
    assert panel._index_at_global(global_at(offs[n] + 500)) == n
    assert panel._index_at_global(global_at(-50)) == 0
    for i in range(n + 1):                                            # every boundary maps to itself
        assert panel._index_at_global(global_at(offs[i])) == i
    tid = c.ws.tracks[0].id
    panel._grip_press(tid, global_at(0))
    panel._grip_move(global_at(offs[4] + 1))
    assert panel._drop_index == 4
    ind = panel._indicator().geometry()
    assert ind.y() == tl.row_y(4) - panel._voffset - 1
    panel._grip_release(global_at(offs[4] + 1))
    assert [t.id for t in c.ws.tracks].index(tid) == 3


def test_clicks_and_range_toggles_work_in_and_below_a_strip(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.set_controller_show('cc1')
    r = c.add_range(F(0), F(4))
    x = tl.x_of(1.0)
    y_strip = tl.lane_top(0) + tl.lane_h + tl.strip_px() // 2
    hit = tl._hit(QPointF(x + 40, y_strip))
    assert hit[:2] == ('clip', pad.id)                                # the strip is part of the clip
    assert tl._hit(QPointF(x + 40, y_strip), Qt.AltModifier)[:2] == ('clip', pad.id)
    tr = tl.toggle_rect(r, 1)                                         # a lower row: at its new position
    assert tr.top() == tl.lane_top(1) + 4 and tl.lane_top(1) == tl.header_h() + tl.row_h(0)
    assert tl._hit(tr.center())[:2] == ('toggle', r.id)
    assert tl._hit(tr.center())[2] == lead.id


def test_the_strip_is_painted_in_the_row_and_the_notes_do_not_move(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    tl.set_zoom(28.0, 0)
    tl.horizontalScrollBar().setValue(0)
    tl.verticalScrollBar().setValue(0)
    for h in (46, 68):
        tl.set_lane_height(h)
        c.set_controller_show(None)
        plain = tl.viewport().grab().toImage()
        c.set_controller_show('cc7')
        lane = tl.viewport().grab().toImage()
        top = tl.header_h()
        # the notes region of Pad's lane is pixel-identical; only the strip below it differs
        x0, x1 = int(tl.x_of(0.5)), int(tl.x_of(3.5))
        for y in range(top + 3, top + h - 4):
            for x in range(x0, x1, 7):
                assert plain.pixelColor(x, y) == lane.pixelColor(x, y), (h, x, y)
        assert any(plain.pixelColor(x, top + h + 4) != lane.pixelColor(x, top + h + 4) for x in range(x0, x1))
        # Lead's lane moved down by the strip but is otherwise the same
        shift = tl.strip_px()
        assert tl.lane_top(1) == top + h + shift


def test_painting_visits_only_the_visible_rows_with_200_tracks(cw, monkeypatch):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.new_document()
    c.import_payloads([Payload(f't{i}.mid', smf([conductor(BEAT), track(PAD if i % 5 == 0 else LEAD, f'T{i}')]))
                       for i in range(200)])
    QApplication.processEvents()
    assert len(c.ws.tracks) == 200
    c.set_controller_show('cc1')
    calls = []
    real = tl._paint_track_regions
    monkeypatch.setattr(tl, '_paint_track_regions', lambda p, t, top, rh, *a: (calls.append(c.ws.tracks.index(t)), real(p, t, top, rh, *a)))
    for scroll in (0, 5000, tl.verticalScrollBar().maximum()):
        tl.verticalScrollBar().setValue(scroll)
        calls.clear()
        tl.viewport().grab()
        first, last = tl.lane_at(tl.header_h()), tl.lane_at(tl.viewport().height() - 1)
        last = last if last >= 0 else 199
        assert calls and set(calls) >= set(range(first, last + 1))
        assert len(calls) <= last - first + 2
    started = time.perf_counter()
    for _ in range(20):
        tl._ensure_rows()
        tl.lane_at(500)
        tl.row_y(150)
    assert time.perf_counter() - started < 0.5                         # prefix sums: no loop per call


def test_the_session_applies_the_controller_view_before_the_scroll_offset(cw):
    from midi_interchange.ui import session
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    many_tracks(w)
    c.set_controller_show('cc1')
    tl.verticalScrollBar().setValue(2 * tl.row_h(0))
    saved = session.capture(w)
    c.set_controller_show(None)
    tl.verticalScrollBar().setValue(0)
    session.apply_session(w, saved)
    assert c.controller_show == 'cc1'
    assert tl.verticalScrollBar().value() == saved.settings['vertical_scroll']
    assert_headers_follow_rows(w)


def test_the_box_threshold_is_the_row_height(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    tl.set_lane_height(40)                                            # a normal lane under 45 px
    c.set_controller_show('cc7')
    QApplication.processEvents()
    hp, hl = w.track_panel.header(pad.id), w.track_panel.header(lead.id)
    assert tl.row_h(0) >= 45 > tl.row_h(1)                            # 40 + 12 = 52 for the tall row
    assert hp.ctl_box.isVisibleTo(hp) and not hl.ctl_box.isVisibleTo(hl)
    c.set_controller_overlay(True)
    QApplication.processEvents()
    assert not hp.ctl_box.isVisibleTo(hp)
    c.set_controller_overlay(False)
    tl.set_lane_height(28)                                            # 28 + 10 = 38: still hidden
    QApplication.processEvents()
    assert not hp.ctl_box.isVisibleTo(hp)


def test_the_box_stays_under_the_delete_button_in_a_tall_row(cw):
    w, pad, lead = cw
    tl, c = w.timeline, w.ctl
    c.set_controller_show('cc7')
    QApplication.processEvents()
    h = w.track_panel.header(pad.id)
    h.layout().activate()
    assert h.height() == tl.row_h(0) > tl.lane_h
    box, rm = h.ctl_box.geometry(), h.remove_btn.geometry()
    assert h.ctl_box.isVisibleTo(h) and box.top() >= rm.bottom() and box.right() == rm.right()
    assert box.bottom() < tl.lane_h                                   # anchored to the top, not centred in the row
    assert h.rect().contains(box)


# ---------------------------------------------------------------- painting

def dense(beats=800):
    """A CC and a pitch bend every 1/32 beat (a Reason curve), plus notes."""
    step = BEAT // 32
    events = [*note(0, 60, 0, 8 * BEAT)]
    for i in range(beats * 32):
        events.append((i * step, cc(0, 1, (i * 7) % 128)))
        events.append((i * step, pb(((i * 131) % 16384) - 8192)))
    return events


@pytest.mark.parametrize('overlay', [False, True])
@pytest.mark.parametrize('joined', [False, True])
def test_dense_curves_paint_at_the_widest_and_narrowest_zoom(cw, overlay, joined):
    w, pad, lead = cw
    c = w.ctl
    c.new_document()
    import_parts(c, Dense=dense())
    t = c.ws.tracks[0]
    clip = t.clips[0]
    c.set_controller_overlay(overlay)
    c.set_controller_joined(joined)
    tl = w.timeline
    width = tl.viewport().width()
    for key in ('cc1', 'pb'):
        c.set_controller_show(key)
        for ppb in (MIN_PPB, MAX_PPB):
            tl.set_zoom(ppb, 0)
            tl.horizontalScrollBar().setValue(0 if ppb == MIN_PPB else int(300 * ppb))
            started = time.perf_counter()
            image = tl.viewport().grab()
            assert not image.isNull() and time.perf_counter() - started < 5
            times, values = tl.controller_lines_for(t, clip, key)[0].series
            a = tl.t_of(0) - float(clip.offset)
            b = tl.t_of(width) - float(clip.offset)
            pts = controller_polyline(times, values, float(clip.offset) * ppb - tl.horizontalScrollBar().value(),
                                      ppb, a, b, joined, tl.x_of(float(clip.end)), width, lambda v: 1 - v)
            assert len(pts) <= 2 * width + 4        # at most two points per pixel column (plus the closing hold)


# ---------------------------------------------------------------- display only

def export_bytes(ctl):
    return sorted(to_bytes(r.midi) for r in ctl.build_exports())


@pytest.fixture
def displays(cw):
    """Pad and Lead with trims, a second channel, an export channel and two ranges."""
    w, pad, lead = cw
    c = w.ctl
    import_parts(c, Two=[*note(0, 60, 0, 6 * BEAT), *note(3, 62, 0, 6 * BEAT), (0, cc(0, 7, 10)), (BEAT, cc(3, 7, 99)),
                         (4 * BEAT, cc(0, 7, 120))])
    two = c.ws.tracks[2]
    c.set_export_channel(two.id, 4)
    c.trim_clip_live(pad.clips[0].id, 'start', F(1))
    c.trim_clip_live(lead.clips[0].id, 'end', F(3))
    c.add_range(F(1), F(3))
    c.add_range(F(4), F(6))
    steps = [lambda: None,
             lambda: c.set_controller_show('cc7'),
             lambda: (c.set_controller_overlay(True), c.set_controller_joined(True)),
             lambda: c.set_controller_show('pb'),
             lambda: c.set_controller_show(None)]
    return w, (pad, lead, two), steps


@pytest.mark.parametrize('mode', list(ExportMode))
def test_export_is_byte_identical_whatever_is_displayed(displays, mode):
    w, (pad, lead, two), steps = displays
    c = w.ctl
    c.set_export_mode(mode)
    c.set_controller_show(None)
    c.set_controller_overlay(False)
    c.set_controller_joined(False)
    baseline = export_bytes(c)
    undo_depth = len(c._undo)
    for step in steps:
        step()
        assert export_bytes(c) == baseline
    for override in ('cc1', 'none', 'pb', None):                      # per-track overrides change nothing either
        for t in (pad, lead, two):
            c.set_track_controller(t.id, override)
        assert export_bytes(c) == baseline
    assert len(c._undo) > undo_depth


@pytest.mark.parametrize('mode', list(ExportMode))
def test_save_and_drag_out_payloads_are_identical_with_display_on(displays, mode, tmp_path, monkeypatch):
    w, (pad, lead, two), _steps = displays
    c = w.ctl
    c.set_export_mode(mode)
    from midi_interchange.interchange import drag_export

    def run(label):
        out = tmp_path / label
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out / 'saved.mid'), ''))
        out.mkdir()
        w.save_midi()
        monkeypatch.setattr(drag_export, '_DIR', str(out / 'drag'))
        dragged = []
        monkeypatch.setattr(QDrag, 'exec', lambda self, *a: dragged.extend(
            u.toLocalFile() for u in self.mimeData().urls()) or Qt.CopyAction)
        start_file_drag(w.export_panel, c, None, pytest.fail, lambda paths: None)
        saved = sorted(p for p in out.glob('*.mid'))
        return ([p.read_bytes() for p in saved], [Path(p).read_bytes() for p in sorted(dragged)])
    off = run('off')
    c.set_controller_show('cc7')
    c.set_controller_overlay(True)
    c.set_controller_joined(True)
    for t in (pad, lead, two):
        c.set_track_controller(t.id, 'cc1' if t is pad else None)
    on = run('on')
    assert on == off and off[0] and off[1]
    assert sorted(to_bytes(r.midi) for r in c.build_exports()) == sorted(off[1])


# ---------------------------------------------------------------- real data

REASON = Path(__file__).parents[1] / 'samples' / 'reason-check' / 'curves for simplify.reason'


def test_reason_curves_song_lists_its_controllers_and_draws(win):
    win.ctl.new_document()
    win.import_paths([str(REASON)])
    QApplication.processEvents()
    assert combo_texts(win) == ['Off', '1 Mod Wheel']
    assert len(win.ctl.ws.tracks) == 3
    win.ctl.set_controller_show('cc1')
    for overlay in (False, True):
        for joined in (False, True):
            win.ctl.set_controller_overlay(overlay)
            win.ctl.set_controller_joined(joined)
            for zoom in (MIN_PPB, 3.0, MAX_PPB):
                win.timeline.set_zoom(zoom, 0)
                assert not win.timeline.viewport().grab().isNull()
    for t in win.ctl.ws.tracks:
        assert win.timeline.controller_lines_for(t, t.clips[0], 'cc1')


def test_showing_a_controller_changes_the_painted_lane_and_nothing_when_off(cw):
    w, pad, lead = cw
    tl = w.timeline
    off = tl.viewport().grab().toImage()
    w.ctl.set_controller_show('cc1')
    lane = tl.viewport().grab().toImage()
    assert lane != off
    w.ctl.set_controller_overlay(True)
    assert tl.viewport().grab().toImage() not in (off, lane)
    w.ctl.set_controller_show(None)
    w.ctl.set_controller_overlay(False)
    assert tl.viewport().grab().toImage() == off
