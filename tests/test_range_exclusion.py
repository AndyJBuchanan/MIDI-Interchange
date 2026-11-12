"""Per-range track exclusion: each range has its own include toggle per track.

The rules under test:
* a new range starts with each track's toggle; after that the range's toggle
  wins and track toggle changes do not reach it;
* range exports (rebase, preserve, separate) use the range toggles: a track is
  silent in a range that excludes it (the range still takes its time) and is
  left out of the file when no range includes it;
* whole export ignores range toggles and uses the track toggles.

Workspace: the Staccato-style song (Bass ch1, Lead ch2, Bass ch5; unique pitches
per track), dropped through the controller. Exports are read back from disk via
both user paths (Save and Drag out). Expected notes come from the generator's
part definitions, not from the model.
"""
from __future__ import annotations

from fractions import Fraction as F

import mido
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpers import notes_of  # noqa: E402
from test_export_assembly import app, drop, expected, export_drag, export_save, gen, payload, win  # noqa: E402,F401

from midi_interchange.core.export_smf import ExportMode  # noqa: E402
from midi_interchange.core.placement import Placement  # noqa: E402

BASS1, LEAD, BASS2 = range(3)


@pytest.fixture
def song(win):
    drop(win, gen.SONG_FILE)
    assert [t.name for t in win.ctl.ws.tracks] == ["Bass", "Lead", "Bass"]
    return win


def tids(win):
    return [t.id for t in win.ctl.ws.tracks]


def add_ranges(win, mode, spans):
    rs = [win.ctl.add_range(F(s), F(e)) for s, e in spans]
    win.ctl.set_export_mode(mode)
    return rs


def exports(win, tmp_path, monkeypatch):
    out = {}
    for how in ("save", "drag"):
        if how == "save":
            d = tmp_path / "save"
            d.mkdir(exist_ok=True)
            out[how] = export_save(win, d)
        else:
            out[how] = export_drag(win, monkeypatch)
    return out


def check_file(mf: mido.MidiFile, per_part: list) -> None:
    """per_part[k]: segments [(start, end, dst)] for song part k, or None if it must be absent."""
    present = [k for k, segs in enumerate(per_part) if segs is not None]
    assert len(mf.tracks) == 1 + len(present), f"{len(mf.tracks)} tracks, expected {1 + len(present)}"
    tracks_notes = [notes_of(t, mf.ticks_per_beat) for t in mf.tracks]
    for k, segs in enumerate(per_part):
        part = gen.SONG[k]
        pitches = {p for _s, _d, p in part.notes}
        holders = [ns for ns in tracks_notes if any(n[3] in pitches for n in ns)]
        if segs is None:
            assert not holders, f"part {k} ({part.track_name}) should be absent"
            continue
        assert len(holders) == 1, f"part {k} in {len(holders)} tracks"
        got = [n for n in holders[0] if n[3] in pitches]
        assert got == expected([(part, 0)], segs), f"part {k} ({part.track_name})"
        assert len(got) == len(holders[0]), "notes from another part leaked in"


def check(win, tmp_path, monkeypatch, per_file: list[list]) -> None:
    for how, files in exports(win, tmp_path, monkeypatch).items():
        assert len(files) == len(per_file), (how, len(files))
        for mf, per_part in zip(files, per_file):
            try:
                check_file(mf, per_part)
            except AssertionError as exc:
                raise AssertionError(f"[{how}] {exc}") from exc


# -- seeding and priority --------------------------------------------------------------
def test_new_range_starts_from_track_toggles(song):
    ctl = song.ctl
    lead = ctl.ws.tracks[LEAD]
    ctl.set_track_enabled(lead.id, False)
    r = ctl.add_range(F(0), F(4))
    assert [r.includes(i) for i in tids(song)] == [True, False, True]


def test_track_toggle_changes_do_not_reach_existing_ranges(song):
    ctl = song.ctl
    bass, lead = ctl.ws.tracks[BASS1], ctl.ws.tracks[LEAD]
    ctl.set_track_enabled(lead.id, False)
    r = ctl.add_range(F(0), F(4))
    ctl.set_track_enabled(lead.id, True)
    ctl.set_track_enabled(bass.id, False)
    assert not r.includes(lead.id) and r.includes(bass.id)
    ctl.set_all_enabled(False)
    assert [r.includes(i) for i in tids(song)] == [True, False, True]


def test_include_exclude_all_and_reset(song):
    ctl = song.ctl
    r = ctl.add_range(F(0), F(4))
    ctl.set_range_tracks(r.id, False)
    assert not any(r.includes(i) for i in tids(song))
    ctl.set_range_tracks(r.id, True)
    assert all(r.includes(i) for i in tids(song))
    ctl.set_track_enabled(ctl.ws.tracks[BASS2].id, False)
    ctl.set_range_tracks(r.id, None)
    assert [r.includes(i) for i in tids(song)] == [True, True, False]


def test_undo_redo_range_toggles(song):
    ctl = song.ctl
    r = ctl.add_range(F(0), F(4))
    lead = ctl.ws.tracks[LEAD].id
    ctl.set_range_track_included(r.id, lead, False)
    assert not ctl.ws.ranges[0].includes(lead)
    ctl.undo()
    assert ctl.ws.ranges[0].includes(lead)
    ctl.redo()
    assert not ctl.ws.ranges[0].includes(lead)
    ctl.undo()
    ctl.set_range_track_included(r.id, ctl.ws.tracks[BASS1].id, False)   # the undo snapshot is a real copy
    ctl.undo()
    assert all(ctl.ws.ranges[0].includes(i) for i in tids(song))


def test_tracks_created_after_the_range(song):
    ctl, ws = song.ctl, song.ctl.ws
    r = ctl.add_range(F(0), F(4))
    lead = ws.tracks[LEAD]
    ctl.set_range_track_included(r.id, lead.id, False)
    # a new import starts with its own toggle (on)
    drop(song, "keys_part.mid")
    keys = ws.tracks[-1]
    assert keys.name == "Keys" and r.includes(keys.id)
    # a clip moved onto a new track takes the range state of the track it came from
    t = ws.new_track_for_clip(lead.clips[0].id, like=lead)
    assert t is not None and not r.includes(t.id)


# -- export ---------------------------------------------------------------------------
def test_rebase_excluded_track_is_silent_in_that_range(song, tmp_path, monkeypatch):
    r1, _r2 = add_ranges(song, ExportMode.REBASE, [(0, 4), (8, 12)])
    song.ctl.set_range_track_included(r1.id, song.ctl.ws.tracks[LEAD].id, False)
    both = [(0, 4, 0), (8, 12, 4)]
    check(song, tmp_path, monkeypatch, [[both, [(8, 12, 4)], both]])


def test_preserve_overlapping_ranges_union_per_track(song, tmp_path, monkeypatch):
    r1, _r2 = add_ranges(song, ExportMode.PRESERVE, [(0, 8), (4, 12)])
    song.ctl.set_range_track_included(r1.id, song.ctl.ws.tracks[LEAD].id, False)
    check(song, tmp_path, monkeypatch, [[[(0, 12, 0)], [(4, 12, 4)], [(0, 12, 0)]]])


def test_separate_one_file_per_range_with_its_tracks(song, tmp_path, monkeypatch):
    ctl = song.ctl
    r1, r2, r3 = add_ranges(song, ExportMode.SEPARATE, [(0, 4), (8, 12), (12, 16)])
    ctl.set_range_track_included(r1.id, ctl.ws.tracks[BASS2].id, False)
    ctl.set_range_tracks(r2.id, False)
    ctl.set_range_track_included(r2.id, ctl.ws.tracks[LEAD].id, True)
    ctl.set_range_tracks(r3.id, False)          # a range with no tracks gives no file
    check(song, tmp_path, monkeypatch, [
        [[(0, 4, 0)], [(0, 4, 0)], None],
        [None, [(8, 12, 0)], None],
    ])


def test_track_in_no_range_is_left_out(song, tmp_path, monkeypatch):
    ctl = song.ctl
    rs = add_ranges(song, ExportMode.REBASE, [(0, 4), (8, 12)])
    for r in rs:
        ctl.set_range_track_included(r.id, ctl.ws.tracks[BASS2].id, False)
    both = [(0, 4, 0), (8, 12, 4)]
    check(song, tmp_path, monkeypatch, [[both, both, None]])
    assert [t.name for t in ctl.export_tracks()] == ["Bass", "Lead"]


def test_disabled_track_still_exports_from_a_range_that_includes_it(song, tmp_path, monkeypatch):
    ctl = song.ctl
    add_ranges(song, ExportMode.REBASE, [(0, 4)])
    ctl.set_track_enabled(ctl.ws.tracks[LEAD].id, False)
    seg = [(0, 4, 0)]
    check(song, tmp_path, monkeypatch, [[seg, seg, seg]])


def test_whole_export_ignores_range_toggles(song, tmp_path, monkeypatch):
    ctl = song.ctl
    (r,) = add_ranges(song, ExportMode.WHOLE, [(0, 4)])
    ctl.set_range_track_included(r.id, ctl.ws.tracks[BASS1].id, False)
    ctl.set_track_enabled(ctl.ws.tracks[LEAD].id, False)
    whole = [(0, 1000, 0)]
    check(song, tmp_path, monkeypatch, [[whole, None, whole]])


def test_rebase_trim_uses_only_included_tracks(song, tmp_path, monkeypatch):
    """Lead plays at 2 and 4 (half-beat notes); the Bass tracks play on every beat.
    With only Lead in the range, trimming [1, 5) gives [2, 4.5), not [1, 5)."""
    ctl = song.ctl
    (r,) = add_ranges(song, ExportMode.REBASE, [(1, 5)])
    ctl.set_range_tracks(r.id, False)
    ctl.set_range_track_included(r.id, ctl.ws.tracks[LEAD].id, True)
    ctl.set_trim(True)
    check(song, tmp_path, monkeypatch, [[None, [(2, F(9, 2), 0)], None]])


def test_explicit_track_export_follows_range_toggles(song, tmp_path):
    ctl = song.ctl
    (r,) = add_ranges(song, ExportMode.REBASE, [(0, 4)])
    lead = ctl.ws.tracks[LEAD].id
    ctl.set_range_track_included(r.id, lead, False)
    assert ctl.export_tracks([lead]) == []
    ctl.set_range_track_included(r.id, lead, True)
    (mf,) = export_save(song, tmp_path, track_ids=[lead])
    check_file(mf, [None, [(0, 4, 0)], None])


# -- timeline -------------------------------------------------------------------------
def _prepare(song):
    tl = song.timeline
    tl.set_zoom(30.0, 0)
    tl.horizontalScrollBar().setValue(0)
    tl.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    return tl


def test_click_toggle_in_lane(song):
    ctl = song.ctl
    r = ctl.add_range(F(4), F(12))
    tl = _prepare(song)
    lead = ctl.ws.tracks[LEAD].id
    rect = tl.toggle_rect(r, LEAD)
    assert rect is not None
    assert rect.left() > tl.x_of(4.0) and rect.right() < tl.x_of(12.0)
    edits = []
    tl.rangeEditRequested.connect(edits.append)
    QTest.mouseClick(tl.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center().toPoint())
    assert not r.includes(lead) and r.includes(ctl.ws.tracks[BASS1].id)
    assert ctl.selected_range_id == r.id
    # a quick second click arrives as a double-click event: it flips again, it doesn't edit the range
    pt = rect.center()
    tl.mouseDoubleClickEvent(QMouseEvent(QEvent.MouseButtonDblClick, pt, tl.viewport().mapToGlobal(pt),
                                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert r.includes(lead), "second quick click did not flip the toggle back"
    assert edits == [], "double-clicking a toggle must not open the range editor"
    assert len(ctl.ws.ranges) == 1, "clicking a toggle must not draw a range"


def test_no_toggle_when_range_too_narrow(song):
    ctl = song.ctl
    tl = _prepare(song)
    r = ctl.add_range(F(4), F(4) + F(1, 4))      # 7.5 px at 30 px/beat
    assert tl.toggle_rect(r, 0) is None
    menu = tl.range_menu(r.id)
    acts = {a.text(): a for a in menu.actions()}
    assert acts["Lead"].isChecked()
    acts["Lead"].trigger()
    assert not r.includes(ctl.ws.tracks[LEAD].id)
    acts["Include All Tracks"].trigger()
    assert all(r.includes(i) for i in tids(song))


def test_excluded_section_is_drawn_dimmed_with_toggle_states(song):
    ctl = song.ctl
    r = ctl.add_range(F(4), F(12))
    ctl.set_range_track_included(r.id, ctl.ws.tracks[LEAD].id, False)
    tl = _prepare(song)
    img = tl.viewport().grab().toImage()

    def lum(x0, x1, lane):
        top = tl.lane_top(lane)
        vals = [QColor(img.pixelColor(x, y)).lightness()
                for x in range(int(x0), int(x1), 2) for y in range(top + 20, top + tl.lane_h - 4, 2)]
        return sum(vals) / len(vals)

    inside = (tl.x_of(6.0), tl.x_of(10.0))
    outside = (tl.x_of(13.0), tl.x_of(17.0))
    assert lum(*inside, LEAD) < lum(*outside, LEAD) * 0.75, "excluded lane section not dimmed"
    assert lum(*inside, BASS1) > lum(*outside, BASS1) * 0.85, "included lane section dimmed"
    on = img.pixelColor(tl.toggle_rect(r, BASS1).toRect().topLeft() + QPoint(10, 10))   # clear of the tick
    off = img.pixelColor(tl.toggle_rect(r, LEAD).toRect().topLeft() + QPoint(10, 10))   # clear of the tick
    assert on.red() > 200 and on.blue() < 120, f"included toggle not filled: {on.name()}"
    assert off.lightness() < 60, f"excluded toggle filled: {off.name()}"


# -- studio test round 2026-11-10 ---------------------------------------------------
def _drag_names(win, monkeypatch) -> list[str]:
    import os
    import tempfile
    from PySide6.QtGui import QDrag
    from midi_interchange.interchange import drag_export
    from midi_interchange.ui.export_panel import start_file_drag
    monkeypatch.setattr(drag_export, "_DIR", tempfile.mkdtemp(prefix="drag-test-"))
    urls: list = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: urls.extend(self.mimeData().urls()) or Qt.CopyAction)
    start_file_drag(win.export_panel, win.ctl, None, pytest.fail, lambda _p: None)
    return [os.path.basename(u.toLocalFile()) for u in urls]


@pytest.mark.parametrize("mode", [ExportMode.REBASE, ExportMode.PRESERVE, ExportMode.SEPARATE])
@pytest.mark.parametrize("single_track", [False, True])
def test_unnamed_range_names_for_drag_and_save(song, monkeypatch, tmp_path, mode, single_track):
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    ctl = song.ctl
    r, = add_ranges(song, mode, [(0, 4)])
    if single_track:
        ctl.set_range_tracks(r.id, False)
        ctl.set_range_track_included(r.id, ctl.ws.tracks[LEAD].id, True)
    assert ctl.default_export_name() == "Range 1"
    assert _drag_names(song, monkeypatch) == ["Range 1.mid"]
    def save_dialog(_parent, _title, default, _filter):
        assert Path(default).name == "Range 1.mid"
        return str(tmp_path / "Range 1.mid"), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    song.save_midi()
    assert (tmp_path / "Range 1.mid").exists()


@pytest.mark.parametrize("mode", [ExportMode.REBASE, ExportMode.PRESERVE, ExportMode.SEPARATE])
@pytest.mark.parametrize("named", [False, True])
def test_multiple_range_filenames_and_separate_save_base(song, monkeypatch, tmp_path, mode, named):
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    ctl = song.ctl
    r1, r2 = add_ranges(song, mode, [(0, 4), (4, 8)])
    if named:
        ctl.update_range(r1.id, name="Verse")
        ctl.update_range(r2.id, name="Chorus")
    labels = ["Verse", "Chorus"] if named else ["Range 1", "Range 2"]
    joined = " + ".join(labels)
    assert ctl.default_export_name() == joined
    separate = mode is ExportMode.SEPARATE
    assert _drag_names(song, monkeypatch) == ([s + ".mid" for s in labels] if separate else [joined + ".mid"])
    def save_dialog(_parent, _title, default, _filter):
        assert Path(default).name == ("Export" if separate else joined) + ".mid"
        return str(tmp_path / Path(default).name), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    song.save_midi()
    expected = ["Export - " + s + ".mid" for s in labels] if separate else [joined + ".mid"]
    assert sorted(p.name for p in tmp_path.glob("*.mid")) == sorted(expected)


def test_export_name_joins_the_range_names(song):
    ctl = song.ctl
    r1, r2, r3, r4 = add_ranges(song, ExportMode.REBASE, [(0, 4), (4, 8), (8, 12), (12, 16)])
    ctl.update_range(r1.id, name="Verse")
    ctl.update_range(r2.id, name="Chorus")
    ctl.update_range(r3.id, name="Verse")          # repeated: named once
    ctl.update_range(r4.id, name="Outro")
    ctl.set_range_tracks(r4.id, False)             # range labels don't depend on track inclusion
    ctl.select_range(r2.id)
    assert ctl.default_export_name() == "Verse + Chorus + Outro"
    ctl.set_export_mode(ExportMode.WHOLE)          # whole export ignores ranges
    assert ctl.default_export_name() == "MIDI Interchange Export"


def test_separate_drag_files_with_the_same_range_name_all_arrive(song, monkeypatch):
    ctl = song.ctl
    r1, r2, r3 = add_ranges(song, ExportMode.SEPARATE, [(0, 4), (4, 8), (8, 12)])
    for r, n in ((r1, "Verse"), (r2, "Chorus"), (r3, "Chorus")):
        ctl.update_range(r.id, name=n)
    ctl.set_range_tracks(r1.id, False)
    ctl.set_range_track_included(r1.id, ctl.ws.tracks[LEAD].id, True)
    assert _drag_names(song, monkeypatch) == ["Verse.mid", "Chorus.mid", "Chorus (2).mid"]


def test_alt_click_track_toggle_sets_every_range(song):
    ctl = song.ctl
    rs = add_ranges(song, ExportMode.REBASE, [(0, 4), (8, 12)])
    lead = ctl.ws.tracks[LEAD].id
    cb = song.track_panel.header(lead).enabled_cb
    QTest.mouseClick(cb, Qt.LeftButton, Qt.NoModifier, cb.rect().center())
    assert not ctl.ws.track(lead).enabled and all(r.includes(lead) for r in rs)   # plain click: track only
    ctl.set_track_enabled(lead, True)
    depth = len(ctl._undo)
    QTest.mouseClick(cb, Qt.LeftButton, Qt.AltModifier, cb.rect().center())
    assert not ctl.ws.track(lead).enabled and not any(r.includes(lead) for r in rs)
    assert len(ctl._undo) == depth + 1, "one undo step"
    ctl.undo()
    assert ctl.ws.track(lead).enabled and all(r.includes(lead) for r in ctl.ws.ranges)
    # Alt-click on a track already in that state still brings the ranges in line
    ctl.set_range_track_included(ctl.ws.ranges[0].id, lead, False)
    ctl.set_track_enabled(lead, True, ranges_too=True)
    assert all(r.includes(lead) for r in ctl.ws.ranges)


def test_off_track_is_drawn_normally_inside_ranges_that_include_it(song):
    ctl = song.ctl
    ctl.add_range(F(4), F(12))
    ctl.set_track_enabled(ctl.ws.tracks[LEAD].id, False)       # still included by the range
    tl = _prepare(song)
    img = tl.viewport().grab().toImage()

    def max_sat(x0, x1, lane):
        top = tl.lane_top(lane)
        return max(QColor(img.pixelColor(x, y)).hsvSaturation()
                   for x in range(int(x0), int(x1)) for y in range(top + 4, top + tl.lane_h - 4))

    inside = max_sat(tl.x_of(5.0), tl.x_of(11.8), LEAD)           # clear of the range toggle
    outside = max_sat(tl.x_of(0.1), tl.x_of(3.8), LEAD)
    assert outside < 60, "off track should be grey outside the range"
    assert inside > 120, "off track should be in colour inside a range that includes it"


def test_track_headers_are_clipped_below_the_title_band(song):
    from midi_interchange.ui.timeline import HEADER_H
    tp = song.track_panel
    tp._set_offset(song.timeline.lane_h // 2)       # first header half scrolled under the band
    QApplication.processEvents()
    h = tp.header(song.ctl.ws.tracks[0].id)
    assert h.isVisible()
    top = h.mapTo(tp, h.visibleRegion().boundingRect().topLeft()).y()
    assert top >= HEADER_H, f"header visible from y={top}, inside the title band"


def _window_drop(win, path: str, lane: int | None) -> None:
    """Drop a file on the window the way Finder does (drag-enter, then drop)."""
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from midi_interchange.ui.timeline import HEADER_H
    tl = win.timeline
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    y = HEADER_H + (lane if lane is not None else len(win.ctl.ws.tracks) + 1) * tl.lane_h + tl.lane_h // 2
    pt = tl.viewport().mapTo(win, QPoint(int(tl.x_of(0.2)), y))
    win.dragEnterEvent(QDragEnterEvent(pt, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    win.dropEvent(QDropEvent(QPointF(pt), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    QApplication.processEvents()


def test_separate_files_dropped_back_one_by_one_keep_their_tracks(win, monkeypatch):
    """Studio report 2026-11-10: tracks A-G, ranges with A B / C D / E F, drag out
    as separate files, New, drop each file back onto track A in turn. Every
    file's tracks must arrive under their own names with their own notes."""
    import tempfile
    from PySide6.QtGui import QDrag
    from midi_interchange.interchange import drag_export
    from midi_interchange.ui.export_panel import start_file_drag
    ctl = win.ctl
    drop(win, gen.SEVEN_FILE)
    assert [t.name for t in ctl.ws.tracks] == list("ABCDEFG")
    rs = add_ranges(win, ExportMode.SEPARATE, [(0, 16), (16, 32), (32, 48)])   # the three 4-bar sections
    for k, r in enumerate(rs):
        ctl.set_range_tracks(r.id, False)
        for t in ctl.ws.tracks[2 * k:2 * k + 2]:
            ctl.set_range_track_included(r.id, t.id, True)
    monkeypatch.setattr(drag_export, "_DIR", tempfile.mkdtemp(prefix="drag-test-"))
    urls: list = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: urls.extend(self.mimeData().urls()) or Qt.CopyAction)
    start_file_drag(win.export_panel, ctl, None, pytest.fail, lambda _p: None)
    paths = [u.toLocalFile() for u in urls]
    assert len(paths) == 3

    win.a_new.trigger()
    QApplication.processEvents()
    pitches = {p.track_name: {n[2] for n in p.notes} for p in gen.SEVEN}
    for k, path in enumerate(paths):
        _window_drop(win, path, 0 if ctl.ws.tracks else None)       # onto track A once it exists
        want = list("ABCDEF")[:2 * k + 2]
        assert [t.name for t in ctl.ws.tracks] == want, f"after file {k + 1}"
    for t in ctl.ws.tracks:
        got = {e.msg.note for c in t.clips for e in c.events if e.msg.type == "note_on"}
        assert got and got <= pitches[t.name], f"track {t.name} holds another track's notes"
