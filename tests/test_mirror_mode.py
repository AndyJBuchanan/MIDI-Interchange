"""Mirror mode (docs/plans/mirror-mode.md): the watcher with a fake clock and simulated saves, the pure
carry-over, the read-only guard, the cue, unmirror and the session. Files live in tmp_path; reads are
synchronous (an inline executor), so nothing here waits on a thread or on real time."""
import os
import re
import shutil
from concurrent.futures import Future
from datetime import datetime
from fractions import Fraction as F
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDrag, QDropEvent, QImage, QPalette, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QWidget

from helpers import conductor, note, smf, to_bytes, track
from test_ui_assembly import app, win  # noqa: F401
from midi_interchange.core.document import Workspace
from midi_interchange.core.export_smf import ExportMode
from midi_interchange.core.import_result import ImportResult
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.mirror import carry_over
from midi_interchange.core.placement import Placement, place_imports
from midi_interchange.core.ranges import Range
from midi_interchange.core.session import SessionStore
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui import main_window, theme
from midi_interchange.ui import mirror as mirror_module
from midi_interchange.ui.controller import Controller
from midi_interchange.ui.export_panel import start_file_drag
from midi_interchange.ui.mirror import MirrorWatcher, read_snapshot
from midi_interchange.ui.session import apply_session, capture

SAMPLES = Path(__file__).parents[1] / 'samples'
CUBASE_A = SAMPLES / 'project-sets' / 'indy-001x.cpr'
CUBASE_B = SAMPLES / 'project-sets' / 'GA & Padshop 2-(alt instr 2)-01.cpr'
REASON_A = SAMPLES / 'reason-probe' / 'r03.reason'
REASON_B = SAMPLES / 'reason-probe' / 'r11.reason'
BEAT = 480


# ---------------------------------------------------------------- helpers

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Inline:
    """A synchronous executor: the read runs at submit and is done at once."""

    def submit(self, fn, *args):
        f = Future()
        try:
            f.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001
            f.set_exception(exc)
        return f


class Manual:
    """An executor whose reads run only when the test says so (a read in progress)."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        f = Future()
        self.pending.append((f, fn, args))
        return f

    def run(self):
        for f, fn, args in self.pending:
            try:
                f.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001
                f.set_exception(exc)
        self.pending = []


def song(**parts):
    """A one-file SMF: name=(pitch,) per track, each with one 4-beat note."""
    tracks = [conductor(BEAT)]
    for name, pitch in parts.items():
        tracks.append(track(note(0, pitch, 0, 4 * BEAT), name.replace('_', ' ')))
    return smf(tracks)


def result_of(data, name='song.mid', preserve=False):
    src, tracks = import_smf_bytes(data, name)
    return ImportResult(src, tracks, preserve_track_state=preserve)


def workspace_of(result):
    ws = Workspace()
    place_imports(ws, [result], Placement())
    return ws


def by_name(ws, name):
    return next(t for t in ws.tracks if t.name == name)


def state(ws):
    """Everything an edit could change, comparable."""
    return (
        [s.id for s in ws.sources],
        [(t.id, t.name, t.color, t.export_channel, t.controller, t.muted, t.soloed,
          [(c.id, c.start, c.end, c.trim_start, c.trim_end, c.muted) for c in t.clips]) for t in ws.tracks],
        ws.tempo_source_id,
        [(r.id, r.start, r.end, r.name, sorted(r.excluded), r.track_locked) for r in ws.ranges],
    )


def advance(watcher, clock, seconds, step=0.25):
    """Poll every `step` seconds of fake time until `seconds` have passed."""
    end = clock.t + seconds
    while clock.t < end - 1e-9:
        clock.t += step
        watcher.poll()


class Events:
    def __init__(self, watcher):
        self.imported, self.unchanged, self.failed, self.missing = [], [], [], []
        watcher.imported.connect(self.imported.append)
        watcher.unchanged.connect(lambda: self.unchanged.append(1))
        watcher.failed.connect(self.failed.append)
        watcher.missingChanged.connect(self.missing.append)


def watch(path, executor=None):
    clock = FakeClock()
    w = MirrorWatcher(str(path), clock=clock, executor=executor or Inline())
    w.set_baseline(read_snapshot(str(path)))
    return w, clock, Events(w)


def names(result):
    return [t.name for t in result.tracks]


@pytest.fixture
def mid(tmp_path, app):
    p = tmp_path / 'Song.mid'
    p.write_bytes(song(Bass=40, Keys=60))
    return p


def save_in_place(path, data):
    with open(path, 'r+b') as fh:
        fh.seek(0)
        fh.write(data)
        fh.truncate()


def save_replace(path, data):
    tmp = path.with_name(path.stem + '-01.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- watcher: simulated saves

def test_in_place_rewrite_is_read_once_after_it_settles(mid):
    w, clock, ev = watch(mid)
    advance(w, clock, 2)
    assert w.read_count == 0 and not ev.imported          # nothing changed: nothing read
    inode = os.stat(mid).st_ino
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
    assert os.stat(mid).st_ino == inode
    advance(w, clock, 0.25)
    assert w.read_count == 0                              # not read the moment it changes
    advance(w, clock, 1)
    assert w.read_count == 1 and len(ev.imported) == 1
    assert names(ev.imported[0]) == ['Bass', 'Keys', 'Lead']
    advance(w, clock, 3)
    assert w.read_count == 1                              # and not again


def test_temp_file_then_rename_is_picked_up_by_the_inode_even_at_the_same_size(mid):
    w, clock, ev = watch(mid)
    before = os.stat(mid)
    save_replace(mid, song(Bass=40, Keys=61))             # same length, new file
    after = os.stat(mid)
    assert after.st_size == before.st_size and after.st_ino != before.st_ino
    advance(w, clock, 1.5)
    assert len(ev.imported) == 1 and w.read_count == 1


def test_a_partial_write_is_not_read_until_the_complete_file_has_settled(mid):
    w, clock, ev = watch(mid)
    full = song(Bass=40, Keys=60, Lead=70)
    save_in_place(mid, full[:len(full) // 2])
    advance(w, clock, 0.25)
    save_in_place(mid, full[:3 * len(full) // 4])
    advance(w, clock, 0.25)
    save_in_place(mid, full)
    advance(w, clock, 0.25)
    assert w.read_count == 0 and not ev.failed            # still inside the settle time
    advance(w, clock, 1)
    assert w.read_count == 1 and not ev.failed
    assert names(ev.imported[0]) == ['Bass', 'Keys', 'Lead']


def test_two_saves_inside_the_settle_time_make_one_read(mid):
    w, clock, ev = watch(mid)
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 0.25)
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70, Pad=72))
    advance(w, clock, 1.5)
    assert w.read_count == 1 and len(ev.imported) == 1
    assert names(ev.imported[0]) == ['Bass', 'Keys', 'Lead', 'Pad']


def test_garbage_keeps_the_last_import_reports_and_the_good_save_is_picked_up(mid):
    w, clock, ev = watch(mid)
    mid.write_bytes(b'this is not midi at all' * 4)
    advance(w, clock, 1)
    assert len(ev.failed) == 1 and ev.failed[0] and not ev.imported
    assert w.retrying
    save_replace(mid, song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 1.5)
    assert len(ev.imported) == 1 and names(ev.imported[0]) == ['Bass', 'Keys', 'Lead']
    assert not w.retrying


def test_a_failed_read_retries_three_times_two_seconds_apart_then_waits_for_a_change(mid):
    w, clock, ev = watch(mid)
    mid.write_bytes(b'garbage' * 10)
    advance(w, clock, 1)
    assert w.read_count == 1
    advance(w, clock, 1.5)
    assert w.read_count == 1                              # not before 2 s
    advance(w, clock, 0.75)
    assert w.read_count == 2
    advance(w, clock, 2.25)
    assert w.read_count == 3
    advance(w, clock, 2.25)
    assert w.read_count == 4 and len(ev.failed) == 4
    assert not w.retrying
    advance(w, clock, 30)
    assert w.read_count == 4                              # gave up until the file changes
    save_in_place(mid, song(Bass=40))
    advance(w, clock, 1)
    assert len(ev.imported) == 1


def test_deleted_then_restored(mid):
    w, clock, ev = watch(mid)
    data = mid.read_bytes()
    mid.unlink()
    advance(w, clock, 2.5)
    assert ev.missing == []                               # tolerated for a few seconds
    advance(w, clock, 1)
    assert ev.missing == [True] and w.missing
    advance(w, clock, 5)
    assert ev.missing == [True] and not ev.imported       # the last import stays, nothing is read
    mid.write_bytes(song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 1.5)
    assert ev.missing == [True, False] and not w.missing
    assert len(ev.imported) == 1 and names(ev.imported[0]) == ['Bass', 'Keys', 'Lead']


def test_a_gap_shorter_than_the_tolerance_says_nothing(mid):
    w, clock, ev = watch(mid)
    data = mid.read_bytes()
    mid.unlink()
    advance(w, clock, 1)
    mid.write_bytes(data)
    advance(w, clock, 2)
    assert ev.missing == []


def test_a_change_during_a_read_discards_the_stale_result(mid):
    manual = Manual()
    w, clock, ev = watch(mid, manual)
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 1)
    assert len(manual.pending) == 1                       # the read has started and is not done
    manual.pending[0][0].set_result(read_snapshot(str(mid)))   # it reads the first save...
    manual.pending = []
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70, Pad=72))   # ...but the file is saved again first
    advance(w, clock, 0.25)
    assert not ev.imported                                # the stale result is thrown away
    advance(w, clock, 1)
    manual.run()
    advance(w, clock, 0.25)
    assert len(ev.imported) == 1 and names(ev.imported[0]) == ['Bass', 'Keys', 'Lead', 'Pad']


def test_only_one_read_runs_at_a_time(mid):
    manual = Manual()
    w, clock, ev = watch(mid, manual)
    save_in_place(mid, song(Bass=40))
    advance(w, clock, 3)
    assert len(manual.pending) == 1


def test_a_touch_with_identical_bytes_is_read_but_not_re_imported(mid):
    w, clock, ev = watch(mid)
    stat = os.stat(mid)
    os.utime(mid, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))    # Reason's mtime-only save
    advance(w, clock, 1.5)
    assert w.read_count == 1 and ev.unchanged == [1] and not ev.imported
    advance(w, clock, 3)
    assert w.read_count == 1                              # remembered: not read again


def test_a_save_with_new_bytes_after_a_touch_still_imports(mid):
    w, clock, ev = watch(mid)
    stat = os.stat(mid)
    os.utime(mid, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    advance(w, clock, 1.5)
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 1.5)
    assert len(ev.imported) == 1


def test_a_cubase_project_replaced_by_temp_file_and_rename(tmp_path, app):
    p = tmp_path / 'Song.cpr'
    shutil.copy(CUBASE_A, p)
    w, clock, ev = watch(p)
    temp = tmp_path / 'Song-01.cpr'
    shutil.copy(CUBASE_B, temp)
    advance(w, clock, 0.5)
    os.replace(temp, p)
    advance(w, clock, 1.5)
    assert len(ev.imported) == 1
    assert names(ev.imported[0]) != names(read_snapshot(str(CUBASE_A)).result)
    assert names(ev.imported[0]) == names(read_snapshot(str(CUBASE_B)).result)


DTRACKS = SAMPLES / 'project-cubase-phases' / 'DTracks'


def test_a_track_disabled_then_re_enabled_in_cubase_goes_and_comes_back(tmp_path, app):
    """d0 (three enabled tracks) -> d1 (B disabled) -> d5 (B enabled again): B leaves the workspace, then
    returns as a new track, and A and C keep their ids and states throughout."""
    p = tmp_path / 'Song.cpr'
    shutil.copy(DTRACKS / 'd0.cpr', p)
    w, clock, ev = watch(p)
    ws = workspace_of(read_snapshot(str(p)).result)
    a, c = by_name(ws, 'Pianoteq 9 A'), by_name(ws, 'Pianoteq 9 C')
    a.color, c.muted = '#123456', True
    ids = {a.id, c.id}
    for src, expected_names, counts in (
            ('d1', ['Pianoteq 9 A', 'Pianoteq 9 C'], {'tracks': 2, 'new': 0, 'gone': 1}),
            ('d5', ['Pianoteq 9 A', 'Pianoteq 9 B', 'Pianoteq 9 C'], {'tracks': 3, 'new': 1, 'gone': 0})):
        save_replace(p, (DTRACKS / f'{src}.cpr').read_bytes())
        advance(w, clock, 1.5)
        result = ev.imported[-1]
        snap, got, _ = carry_over(ws, result)
        assert names(result) == expected_names and got == counts
        assert {t.id for t in snap['tracks']} >= ids
        kept = {t.name: t for t in snap['tracks']}
        assert kept['Pianoteq 9 A'].id == a.id and kept['Pianoteq 9 A'].color == '#123456'
        assert kept['Pianoteq 9 C'].id == c.id and kept['Pianoteq 9 C'].muted
        ws.tracks = list(snap['tracks'])


def test_mirror_passes_include_disabled_on_every_reimport(tmp_path, app):
    p = tmp_path / 'Song.cpr'
    shutil.copy(DTRACKS / 'd0.cpr', p)
    clock = FakeClock()
    w = MirrorWatcher(str(p), clock=clock, executor=Inline(), include_disabled=True)
    w.set_baseline(read_snapshot(str(p), True))
    ev = Events(w)
    save_replace(p, (DTRACKS / 'd1.cpr').read_bytes())
    advance(w, clock, 1.5)
    assert names(ev.imported[0]) == ['Pianoteq 9 A', 'Pianoteq 9 B', 'Pianoteq 9 C']
    assert [t.muted for t in ev.imported[0].tracks] == [False, True, False]
    save_replace(p, (DTRACKS / 'd2.cpr').read_bytes())
    advance(w, clock, 1.5)
    assert len(ev.imported) == 2 and names(ev.imported[-1]) == ['Pianoteq 9 A', 'Pianoteq 9 B', 'Pianoteq 9 C']


def test_a_reason_song_written_in_place(tmp_path, app):
    p = tmp_path / 'Song.reason'
    shutil.copy(REASON_A, p)
    w, clock, ev = watch(p)
    save_in_place(p, REASON_B.read_bytes())
    advance(w, clock, 1.5)
    assert len(ev.imported) == 1 and names(ev.imported[0]) == names(read_snapshot(str(REASON_B)).result)


def test_stop_ends_the_watch(mid):
    w, clock, ev = watch(mid)
    w.stop()
    save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
    advance(w, clock, 3)
    assert w.read_count == 0 and not ev.imported


# ---------------------------------------------------------------- carry-over (pure)

def test_a_matched_track_keeps_its_id_colour_channel_override_and_mute(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    bass, keys = by_name(ws, 'Bass'), by_name(ws, 'Keys')
    bass.color, bass.export_channel, bass.controller, bass.muted = '#123456', 5, 'cc7', True
    snap, counts, _ = carry_over(ws, result_of(song(Bass=41, Keys=61)))
    nb = next(t for t in snap['tracks'] if t.name == 'Bass')
    assert nb.id == bass.id and nb.color == '#123456' and nb.export_channel == 5
    assert nb.controller == 'cc7' and nb.muted
    nk = next(t for t in snap['tracks'] if t.name == 'Keys')
    assert nk.id == keys.id and not nk.muted
    assert nb.clips[0].events is not bass.clips[0].events        # the clips come from the new import
    assert counts == {'tracks': 2, 'new': 0, 'gone': 0}


def test_solo_in_the_app_is_kept_and_other_tracks_follow_the_file(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60, Lead=70)))
    by_name(ws, 'Bass').soloed = True
    new = result_of(song(Bass=40, Keys=60, Lead=70), preserve=True)
    next(t for t in new.tracks if t.name == 'Keys').muted = True          # the file saved Keys muted
    snap, _, _ = carry_over(ws, new)
    flags = {t.name: (t.muted, t.soloed) for t in snap['tracks']}
    assert flags == {'Bass': (False, True), 'Keys': (True, False), 'Lead': (False, False)}


def test_a_file_without_saved_state_does_not_clear_a_track_muted_in_the_app(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    by_name(ws, 'Keys').muted = True
    snap, _, _ = carry_over(ws, result_of(song(Bass=40, Keys=60)))
    assert {t.name: t.muted for t in snap['tracks']} == {'Bass': False, 'Keys': True}


def test_a_locked_range_keeps_its_exclusions_for_matched_tracks(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60, Lead=70)))
    bass, keys, lead = (by_name(ws, n) for n in ('Bass', 'Keys', 'Lead'))
    r = Range(F(4), F(8), name='Verse', track_locked=True, excluded={keys.id})
    ws.ranges.append(r)
    snap, _, _ = carry_over(ws, result_of(song(Bass=40, Keys=60, Lead=70)))
    [nr] = snap['ranges']
    assert nr.id == r.id and (nr.start, nr.end, nr.name, nr.track_locked) == (F(4), F(8), 'Verse', True)
    assert nr.excluded == {keys.id}


def test_a_new_track_is_included_in_every_range_and_follows_the_unlocked_ones(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    keys = by_name(ws, 'Keys')
    ws.ranges.append(Range(F(0), F(4), track_locked=True, excluded={keys.id}))
    ws.ranges.append(Range(F(4), F(8)))
    ws.sync_ranges()
    snap, counts, _ = carry_over(ws, result_of(song(Bass=40, Keys=60, Lead=70)))
    lead = next(t for t in snap['tracks'] if t.name == 'Lead')
    assert counts == {'tracks': 3, 'new': 1, 'gone': 0}
    assert lead.id not in {t.id for t in ws.tracks}
    assert all(lead.id not in r.excluded for r in snap['ranges'])
    assert snap['ranges'][0].excluded == {keys.id}


def test_a_new_track_gets_the_next_colour_after_the_ones_in_use(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    used = {t.color for t in ws.tracks}
    snap, _, _ = carry_over(ws, result_of(song(Bass=40, Keys=60, Lead=70)))
    assert next(t for t in snap['tracks'] if t.name == 'Lead').color not in used


def test_a_gone_track_leaves_the_ranges_cleanly(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60, Lead=70)))
    keys = by_name(ws, 'Keys')
    ws.ranges.append(Range(F(0), F(4), track_locked=True, excluded={keys.id}))
    snap, counts, _ = carry_over(ws, result_of(song(Bass=40, Lead=70)))
    assert counts == {'tracks': 2, 'new': 0, 'gone': 1}
    assert snap['ranges'][0].excluded == set()
    assert keys.id not in {t.id for t in snap['tracks']}


def test_repeated_names_pair_in_order(app):
    data = smf([conductor(BEAT), track(note(0, 40, 0, BEAT), 'Drums'), track(note(0, 41, 0, BEAT), 'Drums')])
    ws = workspace_of(result_of(data))
    first, second = ws.tracks
    snap, counts, _ = carry_over(ws, result_of(data))
    assert [t.id for t in snap['tracks']] == [first.id, second.id] and counts['new'] == 0
    data3 = smf([conductor(BEAT), track(note(0, 40, 0, BEAT), 'Drums'), track(note(0, 41, 0, BEAT), 'Drums'),
                 track(note(0, 42, 0, BEAT), 'Drums')])
    snap, counts, _ = carry_over(ws, result_of(data3))
    assert [t.id for t in snap['tracks']][:2] == [first.id, second.id] and counts == {'tracks': 3, 'new': 1, 'gone': 0}


def test_a_reordered_track_matches_by_name(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    bass, keys = ws.tracks
    snap, _, _ = carry_over(ws, result_of(song(Keys=60, Bass=40)))
    assert [t.id for t in snap['tracks']] == [keys.id, bass.id]


def test_a_renamed_track_arrives_new_and_the_old_one_is_gone(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    keys = by_name(ws, 'Keys')
    ws.ranges.append(Range(F(0), F(4), track_locked=True, excluded={keys.id}))
    snap, counts, _ = carry_over(ws, result_of(song(Bass=40, Piano=60)))
    assert counts == {'tracks': 2, 'new': 1, 'gone': 1}
    piano = next(t for t in snap['tracks'] if t.name == 'Piano')
    assert piano.id != keys.id and snap['ranges'][0].excluded == set()


def test_the_tempo_map_and_sources_are_replaced(app):
    ws = workspace_of(result_of(smf([conductor(BEAT, tempos=((0, 100.0),)),
                                     track(note(0, 40, 0, BEAT), 'Bass')])))
    old_source = ws.sources[0]
    new = result_of(smf([conductor(BEAT, tempos=((0, 90.0),)), track(note(0, 40, 0, BEAT), 'Bass')]))
    snap, _, _ = carry_over(ws, new)
    assert snap['sources'] == [new.source] and snap['sources'][0].id != old_source.id
    assert snap['tempo_source_id'] == new.source.id
    assert round(snap['tempo_map'].effective_tempos()[0].bpm) == 90


def test_carry_over_does_not_change_the_workspace(app):
    ws = workspace_of(result_of(song(Bass=40, Keys=60)))
    ws.ranges.append(Range(F(0), F(4)))
    before = state(ws)
    carry_over(ws, result_of(song(Bass=40, Lead=70)))
    assert state(ws) == before


def test_ranges_are_kept_by_time_even_past_the_end(app):
    ws = workspace_of(result_of(song(Bass=40)))
    ws.ranges.append(Range(F(400), F(404), name='Far'))
    snap, _, _ = carry_over(ws, result_of(song(Bass=40)))
    assert [(r.start, r.end, r.name) for r in snap['ranges']] == [(F(400), F(404), 'Far')]


# ---------------------------------------------------------------- the window

class Mirrored:
    def __init__(self, win, path, clock):
        self.win, self.path, self.clock = win, path, clock
        self.ctl = win.ctl

    @property
    def watcher(self):
        return self.win._mirror_watcher

    def saved(self, data, how=save_replace):
        how(self.path, data)
        advance(self.watcher, self.clock, 1.5)
        QApplication.processEvents()

    def status(self):
        return self.win.statusBar().currentMessage()


@pytest.fixture
def mirrored(win, mid, monkeypatch):
    """The shared window (it holds Bass and Keys from its own files), now mirroring Song.mid."""
    monkeypatch.setattr(win, '_confirm_mirror_replace', lambda: True)
    clock = FakeClock()
    palette = QApplication.palette()
    assert win.start_mirror(str(mid), clock=clock, executor=Inline())
    win._mirror_watcher._timer.stop()                      # tests poll by hand, with the fake clock
    QApplication.processEvents()
    yield Mirrored(win, mid, clock)
    win.unmirror()
    QApplication.setPalette(palette)                       # leave the shared application as the other tests expect


def action_texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_entering_over_a_workspace_asks_first_and_cancel_changes_nothing(win, mid, monkeypatch):
    asked = []
    monkeypatch.setattr(win, '_confirm_mirror_replace', lambda: asked.append(1) or False)
    before = state(win.ctl.ws)
    undo = win.ctl.can_undo()
    assert not win.start_mirror(str(mid))
    assert asked == [1] and state(win.ctl.ws) == before and not win.ctl.mirroring
    assert win.ctl.can_undo() == undo and win._mirror_watcher is None
    assert win.windowTitle() == 'MIDI Interchange' and not win.mirror_banner.isVisible()


def test_the_real_confirmation_dialog_offers_replace_and_cancel(win, mid, monkeypatch):
    seen = {}

    def fake_exec(self):
        seen['buttons'] = [b.text() for b in self.buttons()]
        seen['default'] = self.defaultButton().text()
        return 0
    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    assert not win.start_mirror(str(mid))                   # nothing clicked: not confirmed
    assert 'Replace Workspace' in seen['buttons'] and seen['default'] == 'Cancel'
    assert not win.ctl.mirroring


def test_an_empty_workspace_enters_without_asking(win, mid, monkeypatch):
    win.ctl.new_document()
    monkeypatch.setattr(win, '_confirm_mirror_replace', lambda: pytest.fail('asked'))
    try:
        assert win.start_mirror(str(mid), clock=FakeClock(), executor=Inline())
        win._mirror_watcher._timer.stop()
    finally:
        win.unmirror()


def test_an_unreadable_file_does_not_enter_and_changes_nothing(win, tmp_path, monkeypatch):
    bad = tmp_path / 'Bad.mid'
    bad.write_bytes(b'nope' * 20)
    warned = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warned.append(a[2]))
    before = state(win.ctl.ws)
    assert not win.start_mirror(str(bad))
    assert warned and 'Bad.mid' in warned[0] and state(win.ctl.ws) == before and not win.ctl.mirroring


def test_entering_replaces_the_workspace_at_bar_one_with_no_undo(mirrored):
    ctl = mirrored.ctl
    assert ctl.mirroring
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys']
    assert [s.name for s in ctl.ws.sources] == ['Song.mid']
    assert min(c.start for t in ctl.ws.tracks for c in t.clips) == 0
    assert not ctl.can_undo() and not ctl.can_redo()
    assert not mirrored.win.a_undo.isEnabled() and not mirrored.win.a_redo.isEnabled()
    assert mirrored.watcher._timer.isActive() is False       # stopped by the fixture; start() ran in start_mirror
    assert 'Mirroring Song.mid: 2 tracks at bar 1' in mirrored.status()


def test_the_cue_title_banner_frame_and_button(mirrored):
    w = mirrored.win
    assert w.windowTitle() == 'MIDI Interchange — Mirroring Song.mid'
    assert w.mirror_banner.isVisible() and w.unmirror_btn.isVisible() and w.mirror_frame.isVisible()
    text = w.mirror_label.text()
    assert 'MIRRORING' in text and 'Song.mid' in text and 'read-only' in text
    assert 'updates when the file is saved' in text and re.search(r'Last updated \d\d:\d\d:\d\d', text)
    assert w.mirror_banner.toolTip() == str(mirrored.path.resolve()) or w.mirror_banner.toolTip() == os.path.abspath(mirrored.path)
    assert w.unmirror_btn.text() == 'Unmirror'
    frame, central = w.mirror_frame, w.centralWidget()
    assert frame.geometry() == central.rect()
    assert frame.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert frame.parent() is central
    w.resize(1100, 640)
    QApplication.processEvents()
    assert frame.geometry() == central.rect()
    assert w.mirror_banner.geometry().top() == 0 and w.mirror_banner.width() == central.width()
    w.resize(1200, 700)


def test_the_frame_paints_the_mirror_colour_on_its_edges_and_nothing_inside(mirrored):
    frame = mirrored.win.mirror_frame
    img = QImage(frame.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    frame.render(img, QPoint(), QRegion(), QWidget.RenderFlags())
    w, h = img.width(), img.height()
    for x, y in ((0, 0), (w - 1, h // 2), (w // 2, h - 1), (1, h // 2), (w // 2, 2)):
        c = img.pixelColor(x, y)
        assert (c.red(), c.green(), c.blue(), c.alpha()) == (theme.MIRROR.red(), theme.MIRROR.green(),
                                                              theme.MIRROR.blue(), 255)
    assert img.pixelColor(w // 2, h // 2).alpha() == 0
    assert img.pixelColor(10, 10).alpha() == 0


def test_the_banner_text_contrast_is_at_least_4_5(app):
    assert theme._contrast(theme.MIRROR_TEXT, theme.MIRROR) >= 4.5
    assert theme._contrast(theme.MIRROR, theme.MIRROR_TEXT) >= 4.5


def test_the_cue_colour_is_clear_of_the_colours_that_already_mean_something(app):
    for other in (theme.ACCENT, theme.SOLO, theme.TEMPO_COL):
        assert theme.mix(theme.MIRROR, other, 0).name() != other.name()
        assert abs(theme.MIRROR.hueF() - other.hueF()) > 0.03


def test_the_chrome_is_tinted_and_the_lanes_are_not(mirrored):
    app = QApplication.instance()
    tinted = app.palette().color(QPalette.Window)
    mirrored.win.unmirror()
    plain = app.palette().color(QPalette.Window)
    assert tinted.name() != plain.name()
    assert tinted.blue() > plain.blue() and tinted.green() > plain.green()
    assert theme.PANEL_BG_MIRROR.name() != theme.PANEL_BG.name()
    assert theme.RULER_BG_MIRROR.name() != theme.RULER_BG.name() and theme.INFO_BG_MIRROR.name() != theme.INFO_BG.name()
    assert theme.LANE_A.name() == '#202125' and theme.LANE_B.name() == '#24252a'


def test_the_track_panel_and_ruler_paint_the_tinted_backgrounds_while_mirroring(mirrored):
    w = mirrored.win
    panel = w.track_panel.grab().toImage()
    tl = w.timeline.viewport().grab().toImage()
    assert panel.pixelColor(2, 2).name() == theme.RULER_BG_MIRROR.name()
    assert tl.pixelColor(2, 2).name() == theme.RULER_BG_MIRROR.name()
    w.unmirror()
    QApplication.processEvents()
    assert w.track_panel.grab().toImage().pixelColor(2, 2).name() == theme.RULER_BG.name()
    assert w.timeline.viewport().grab().toImage().pixelColor(2, 2).name() == theme.RULER_BG.name()


def test_the_toolbar_button_and_menu_entries(win):
    assert win.a_mirror.text() == 'Open && Mirror MIDI/Project File…' and win.a_mirror.iconText() == 'Mirror…'
    assert win.a_unmirror.text() == 'Unmirror'
    toolbar_texts = [a.iconText() for a in win.main_toolbar.actions() if not a.isSeparator() and a.iconText()]
    assert toolbar_texts.index('Mirror…') == toolbar_texts.index('Open') + 1
    file_menu = next(a.menu() for a in win.menuBar().actions() if a.text() == '&File')
    assert action_texts(file_menu)[:7] == ['New', 'Open…', 'Open && Mirror MIDI/Project File…', 'Unmirror', 'Sync Mutes to File', 'Show Mirror Log', 'Save MIDI…']
    assert win.a_mirror.isEnabled() and not win.a_unmirror.isEnabled()


# -- re-import through the window -------------------------------------------------

def test_a_save_updates_the_timeline_and_keeps_ranges_locks_mute_selection_and_view(mirrored):
    ctl, tl = mirrored.ctl, mirrored.win.timeline
    ws = ctl.ws
    bass, keys = ws.tracks
    r1 = ctl.add_range(F(0), F(2))
    r2 = ctl.add_range(F(4), F(6))
    ctl.set_range_tracks(r2.id, True)
    ctl.set_range_track_included(r2.id, keys.id, False)
    ctl.set_mute(bass.id, True)
    tl.set_zoom(33.0, 0)
    tl.horizontalScrollBar().setValue(7)
    zoom, scroll = tl.ppb, tl.horizontalScrollBar().value()
    ctl.select_range(r1.id)
    mirrored.saved(song(Bass=41, Keys=61, Lead=70))
    ws = ctl.ws
    assert [t.name for t in ws.tracks] == ['Bass', 'Keys', 'Lead']
    assert ws.tracks[0].id == bass.id and ws.tracks[1].id == keys.id
    assert ws.tracks[0].muted and not ws.tracks[2].muted
    assert [r.id for r in ws.ranges] == [r1.id, r2.id] and ctl.selected_range_id == r1.id
    assert ws.range(r2.id).track_locked and ws.range(r2.id).excluded == {keys.id}
    assert ws.tracks[2].id not in ws.range(r1.id).excluded and ws.tracks[2].id not in ws.range(r2.id).excluded
    assert (tl.ppb, tl.horizontalScrollBar().value()) == (zoom, scroll)
    assert not ctl.can_undo() and not ctl.can_redo()
    assert re.fullmatch(r'Mirror: Song\.mid re-imported at \d\d:\d\d:\d\d: 3 tracks \(1 new\)', mirrored.status())
    assert re.search(r'Last updated \d\d:\d\d:\d\d', mirrored.win.mirror_label.text())


def test_the_status_names_new_and_gone_tracks(mirrored):
    mirrored.saved(song(Bass=40, Lead=70))
    assert re.fullmatch(r'Mirror: Song\.mid re-imported at \d\d:\d\d:\d\d: 2 tracks \(1 new, 1 gone\)', mirrored.status())


def test_a_failed_read_keeps_the_import_reports_it_and_a_good_save_clears_it(mirrored):
    ctl = mirrored.ctl
    before = state(ctl.ws)
    mirrored.saved(b'broken' * 30)
    assert state(ctl.ws) == before
    st = mirrored.status()
    assert re.fullmatch(r"Mirror: Song\.mid couldn't be read at \d\d:\d\d:\d\d \(.+\)\. "
                        r"Keeping the version from \d\d:\d\d:\d\d; retrying\.", st), st
    assert 'Last read failed' in mirrored.win.mirror_label.text()
    mirrored.saved(song(Bass=40, Keys=60, Lead=70))
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys', 'Lead']
    assert 'Last read failed' not in mirrored.win.mirror_label.text()


def test_a_missing_file_says_so_and_a_restored_one_is_read(mirrored):
    data = mirrored.path.read_bytes()
    mirrored.path.unlink()
    advance(mirrored.watcher, mirrored.clock, 3.5)
    assert mirrored.status() == 'Mirror: Song.mid not found; waiting for it'
    assert 'Song.mid not found; waiting for it' in mirrored.win.mirror_label.text()
    assert [t.name for t in mirrored.ctl.ws.tracks] == ['Bass', 'Keys']       # the last import stays
    mirrored.saved(song(Bass=40, Keys=60, Lead=70), how=lambda p, d: p.write_bytes(d))
    assert 'not found' not in mirrored.win.mirror_label.text()
    assert [t.name for t in mirrored.ctl.ws.tracks] == ['Bass', 'Keys', 'Lead']


def test_restoring_the_same_file_clears_the_waiting_notice(mirrored):
    data = mirrored.path.read_bytes()
    mirrored.path.unlink()
    advance(mirrored.watcher, mirrored.clock, 3.5)
    mirrored.path.write_bytes(data)
    advance(mirrored.watcher, mirrored.clock, 1.5)
    assert 'not found' not in mirrored.win.mirror_label.text()
    assert 'same content' in mirrored.status()


def test_a_finished_read_waits_for_a_gesture_to_end(mirrored):
    ctl, tl = mirrored.ctl, mirrored.win.timeline
    tl._external_drag = True
    mirrored.saved(song(Bass=40, Keys=60, Lead=70))
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys'] and mirrored.win._mirror_pending is not None
    tl._external_drag = False
    mirrored.win._apply_mirror_pending()
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys', 'Lead'] and mirrored.win._mirror_pending is None
    ctl.file_drag_active = True
    mirrored.saved(song(Bass=40))
    assert len(ctl.ws.tracks) == 3
    ctl.file_drag_active = False
    mirrored.win._apply_mirror_pending()
    assert [t.name for t in ctl.ws.tracks] == ['Bass']


def test_a_newer_finished_read_replaces_one_still_waiting(mirrored):
    ctl, tl = mirrored.ctl, mirrored.win.timeline
    tl._external_drag = True
    mirrored.saved(song(Bass=40, Keys=60, Lead=70))
    mirrored.saved(song(Bass=40, Keys=60, Lead=70, Pad=72))
    tl._external_drag = False
    mirrored.win._apply_mirror_pending()
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys', 'Lead', 'Pad']


def test_repeated_re_imports_and_edits_never_make_an_undo_step(mirrored):
    ctl = mirrored.ctl
    for i in range(3):
        mirrored.saved(song(Bass=40 + i, Keys=60))
        r = ctl.add_range(F(i), F(i + 2))
        ctl.update_range(r.id, name=f'R{i}')
        ctl.set_range_tracks(r.id, True)
        ctl.set_mute(ctl.ws.tracks[0].id, i % 2 == 0)
        ctl.toggle_solo(ctl.ws.tracks[1].id)
        ctl.delete_range(r.id)
    ctl.checkpoint()
    assert not ctl.can_undo() and not ctl.can_redo()


# -- read-only -------------------------------------------------------------------

def test_every_editing_method_is_refused_and_changes_nothing(mirrored):
    ctl = mirrored.ctl
    bass, keys = ctl.ws.tracks
    clip = bass.clips[0]
    ctl.add_range(F(0), F(2))
    before = state(ctl.ws)
    calls = [
        lambda: ctl.import_payloads([Payload('x.mid', song(Bass=40))]),
        lambda: ctl.new_document(),
        lambda: ctl.move_clip_live(clip.id, F(3), keys.id),
        lambda: ctl.trim_clip_live(clip.id, 'end', F(1)),
        lambda: ctl.split_clip(clip.id, F(2)),
        lambda: ctl.toggle_clip_mute(clip.id),
        lambda: ctl.restore_clip(clip.id),
        lambda: ctl.move_clip_to_track(clip.id, keys.id),
        lambda: ctl.move_clip_to_track(clip.id, None),
        lambda: ctl.delete_clip(clip.id),
        lambda: ctl.duplicate_clip(clip.id),
        lambda: ctl.snap_clip_to_previous(clip.id),
        lambda: ctl.merge_tracks(bass.id, keys.id),
        lambda: ctl.rename_track(bass.id, 'Renamed'),
        lambda: ctl.set_export_channel(bass.id, 3),
        lambda: ctl.set_track_color(bass.id, '#ffffff'),
        lambda: ctl.move_track(bass.id, 1),
        lambda: ctl.remove_track(bass.id),
        lambda: ctl.adopt_tempo(ctl.ws.sources[0].id),
        lambda: ctl.undo(),
        lambda: ctl.redo(),
        lambda: ctl.move_clip(bass.id, clip.id, F(5)),
    ]
    for call in calls:
        call()
        assert state(ctl.ws) == before
    assert not ctl.can_undo()
    ctl.checkpoint()
    assert not ctl.can_undo()


def test_a_refused_edit_says_why(mirrored):
    mirrored.ctl.rename_track(mirrored.ctl.ws.tracks[0].id, 'Nope')
    assert mirrored.status() == 'Mirroring: read-only (unmirror to edit)'
    mirrored.ctl.import_payloads([Payload('x.mid', song(Bass=40))])
    assert mirrored.status() == 'Mirroring: unmirror to import'


def test_file_actions_undo_and_redo_are_disabled_and_unmirror_is_enabled(mirrored):
    w = mirrored.win
    for a in (w.a_new, w.a_open, w.a_mirror, w.a_undo, w.a_redo):
        assert not a.isEnabled(), a.text()
    assert w.a_unmirror.isEnabled()
    assert not w.tempo_menu.isEnabled()
    button = w.main_toolbar.widgetForAction(w.a_mirror)
    assert theme.MIRROR.name() in button.styleSheet()


def test_a_second_mirror_is_refused_while_mirroring(mirrored, tmp_path):
    other = tmp_path / 'Other.mid'
    other.write_bytes(song(Pad=50))
    assert not mirrored.win.start_mirror(str(other))
    assert [t.name for t in mirrored.ctl.ws.tracks] == ['Bass', 'Keys']


def test_the_track_menu_offers_only_what_stays_allowed(mirrored):
    w = mirrored.win
    bass = mirrored.ctl.ws.tracks[0]
    m = QMenu()
    assert w._add_track_actions(m, bass.id)
    assert action_texts(m) == ['Mute', "Follow File's Mute/Solo", 'Save This Track…', 'Source Info…']
    for banned in ('Rename', 'Move Up', 'Move Down', 'Merge Into', "Use This Track's Tempo Map", 'Remove Track'):
        assert banned not in action_texts(m)


def test_the_clip_menu_offers_only_the_allowed_track_items(mirrored, monkeypatch):
    w = mirrored.win
    shown = []

    class Recording(QMenu):
        def exec(self, *a):
            shown.append(self)
    monkeypatch.setattr(main_window, 'QMenu', Recording)
    bass = mirrored.ctl.ws.tracks[0]
    w.clip_menu(bass.id, bass.clips[0].id, QPoint(5, 5))
    [menu] = shown
    top = action_texts(menu)
    assert len(top) == 2 and top[0].startswith('Clip:') and top[1] == 'Track: Bass'
    sub = next(a.menu() for a in menu.actions() if a.text() == 'Track: Bass')
    assert action_texts(sub) == ['Mute', "Follow File's Mute/Solo", 'Save This Track…', 'Source Info…']


def test_the_tempo_map_menus_are_unavailable(mirrored):
    w = mirrored.win
    assert not w.tempo_menu.isEnabled()
    assert w.header_menu().actions() == []
    m = QMenu()
    w._fill_tempo_menu(m)
    assert [a.isEnabled() for a in m.actions()] == [False]


def test_track_headers_are_read_only_but_mute_and_solo_work(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    QApplication.processEvents()
    before = state(ctl.ws)
    for t in ctl.ws.tracks:
        h = w.track_panel.header(t.id)
        assert h.name_edit.isReadOnly()
        for widget in (h.remove_btn, h.grip, h.color_btn, h.ctl_box):
            assert not widget.isEnabled()
        assert h.mute_btn.isEnabled() and h.solo_btn.isEnabled()
        h.remove_btn.click()
        h.color_btn.click()
        h.name_edit.setText('X')
        h.name_edit.editingFinished.emit()
    assert [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys'] and state(ctl.ws) == before
    h = w.track_panel.header(ctl.ws.tracks[0].id)
    h.mute_btn.click()
    assert ctl.ws.tracks[0].muted
    h.solo_btn.click()
    assert ctl.ws.tracks[0].soloed


def test_header_grip_drag_does_not_reorder(mirrored):
    p, ctl = mirrored.win.track_panel, mirrored.ctl
    ids = [t.id for t in ctl.ws.tracks]
    p._grip_press(ids[0], QPoint(0, 0))
    p._drop_index = 2
    p._grip_release(QPoint(0, 0))
    assert [t.id for t in ctl.ws.tracks] == ids


def clip_point(w, track_index=0):
    tl = w.timeline
    y = tl.lane_top(track_index) + tl.lane_h // 2
    return QPoint(int(tl.x_of(1.0)), y)


def test_alt_option_and_cmd_gestures_on_a_clip_do_nothing(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    tl = w.timeline
    tl.set_zoom(40.0, 0)
    tl.horizontalScrollBar().setValue(0)
    QApplication.processEvents()
    before = [(t.id, [(c.id, c.start, c.end, c.trim_start, c.trim_end, c.muted) for c in t.clips]) for t in ctl.ws.tracks]
    for mods in (Qt.AltModifier, Qt.AltModifier | Qt.ControlModifier, Qt.ControlModifier):
        assert tl._clip_action(mods) is None
    vp = tl.viewport()
    for mods in (Qt.AltModifier, Qt.AltModifier | Qt.ControlModifier, Qt.ControlModifier):
        QTest.mouseMove(vp, clip_point(w, 0))
        QTest.mousePress(vp, Qt.LeftButton, mods, clip_point(w, 0))
        QTest.mouseMove(vp, clip_point(w, 1) + QPoint(60, 0))
        QTest.mouseRelease(vp, Qt.LeftButton, mods, clip_point(w, 1) + QPoint(60, 0))
        QApplication.processEvents()
        assert tl._drag is None
    after = [(t.id, [(c.id, c.start, c.end, c.trim_start, c.trim_end, c.muted) for c in t.clips]) for t in ctl.ws.tracks]
    assert after == before and not ctl.can_undo()


def test_the_m_key_does_not_mute_a_clip(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    tl = w.timeline
    tl.set_zoom(40.0, 0)
    QApplication.processEvents()
    pos = clip_point(w, 0)
    tl._pointer = QPointF(pos)
    assert tl._lane_hit(tl._pointer)[0] == 'clip'
    QTest.keyClick(tl, Qt.Key_M)
    assert not any(c.muted for t in ctl.ws.tracks for c in t.clips)


def test_clip_cursors_are_not_shown_for_clip_gestures(mirrored):
    tl = mirrored.win.timeline
    tl.set_zoom(40.0, 0)
    QApplication.processEvents()
    pos = QPointF(clip_point(mirrored.win, 0))
    tl._update_cursor(pos, Qt.AltModifier)
    assert tl.viewport().cursor().shape() not in (Qt.SizeAllCursor,)
    tl._update_cursor(pos, Qt.ControlModifier)
    assert tl._split_preview is None


def test_import_paths_and_second_launch_hand_off_are_refused(mirrored, tmp_path):
    w, ctl = mirrored.win, mirrored.ctl
    before = state(ctl.ws)
    extra = tmp_path / 'Extra.mid'
    extra.write_bytes(song(Pad=50))
    w.import_paths([str(extra)])
    assert state(ctl.ws) == before and mirrored.status() == 'Mirroring: unmirror to import'


def drop_mime(path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def test_a_file_drag_and_drop_on_the_window_is_refused(mirrored, tmp_path):
    w, ctl = mirrored.win, mirrored.ctl
    before = state(ctl.ws)
    extra = tmp_path / 'Extra.mid'
    extra.write_bytes(song(Pad=50))
    mime = drop_mime(extra)
    enter = QDragEnterEvent(QPoint(300, 300), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    enter.setAccepted(True)
    w.dragEnterEvent(enter)
    assert not enter.isAccepted() and not w.overlay.isVisible()
    assert not w.timeline._external_drag
    drop = QDropEvent(QPointF(300, 300), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    drop.setAccepted(True)
    w.dropEvent(drop)
    assert not drop.isAccepted() and state(ctl.ws) == before
    assert mirrored.status() == 'Mirroring: unmirror to import'


# -- allowed -----------------------------------------------------------------------

def test_ranges_toggles_locks_mute_solo_and_the_sources_solo_still_work(mirrored):
    ctl = mirrored.ctl
    bass, keys = ctl.ws.tracks
    r = ctl.add_range(F(0), F(4))
    ctl.update_range(r.id, F(1), F(5), name='Hook')
    assert (r.start, r.end, r.name) == (F(1), F(5), 'Hook')
    ctl.set_range_tracks(r.id, True)
    ctl.set_range_track_included(r.id, keys.id, False)
    assert r.track_locked and r.excluded == {keys.id}
    ctl.set_range_tracks(r.id, False)
    assert r.excluded == {bass.id, keys.id}
    ctl.set_range_tracks(r.id, None)
    assert not r.track_locked
    ctl.set_mute(bass.id, True)
    assert bass.muted and r.excluded == {bass.id}
    ctl.clear_mutes()
    ctl.toggle_solo(keys.id, exclusive=True)
    assert keys.soloed
    ctl.clear_solos()
    ctl.solo_source_tracks(ctl.ws.sources[0].id)
    assert bass.soloed and keys.soloed
    ctl.clear_solos()
    ctl.select_range(r.id)
    ctl.delete_range(r.id)
    assert ctl.ws.ranges == []
    ctl.add_range(F(0), F(1))
    ctl.clear_ranges()
    assert ctl.ws.ranges == []
    ctl.set_controller_show(None)
    ctl.set_export_mode(ExportMode.SEPARATE)
    ctl.set_trim(True)
    assert not ctl.can_undo()


def export_blobs(ctl):
    return [to_bytes(x.midi) for x in ctl.build_exports()]


def test_export_bytes_and_drag_out_are_identical_to_a_normal_workspace(mirrored, tmp_path, monkeypatch):
    w, ctl = mirrored.win, mirrored.ctl
    r = ctl.add_range(F(0), F(2))
    ctl.set_export_mode(ExportMode.PRESERVE)
    from midi_interchange.interchange import drag_export

    def run(label):
        out = tmp_path / label
        out.mkdir()
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out / 'saved.mid'), ''))
        w.save_midi()
        monkeypatch.setattr(drag_export, '_DIR', str(out / 'drag'))
        dragged = []
        monkeypatch.setattr(QDrag, 'exec', lambda self, *a: dragged.extend(
            u.toLocalFile() for u in self.mimeData().urls()) or Qt.CopyAction)
        start_file_drag(w.export_panel, ctl, None, pytest.fail, lambda paths: None)
        return ([p.read_bytes() for p in sorted(out.glob('*.mid'))], [Path(p).read_bytes() for p in sorted(dragged)])
    mirroring = run('mirroring')
    assert mirroring[0] and mirroring[1] and not ctl.file_drag_active
    normal = Controller()                                     # a normal workspace: the same file, the same range
    normal.import_payloads([Payload('Song.mid', mirrored.path.read_bytes())])
    normal.add_range(F(0), F(2))
    normal.set_export_mode(ExportMode.PRESERVE)
    assert export_blobs(ctl) == export_blobs(normal)
    w.unmirror()
    unmirrored = run('unmirrored')
    assert unmirrored == mirroring


def test_save_this_track_still_works(mirrored, tmp_path, monkeypatch):
    out = tmp_path / 'one.mid'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(out), ''))
    mirrored.win.save_midi([mirrored.ctl.ws.tracks[0].id])
    assert out.exists() and out.stat().st_size > 0


# -- unmirror ----------------------------------------------------------------------

def test_unmirror_keeps_the_workspace_clears_history_restores_editing_and_the_cue(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    r = ctl.add_range(F(0), F(2))
    ctl.set_mute(ctl.ws.tracks[0].id, True)
    mirrored.saved(song(Bass=40, Keys=60, Lead=70))
    before = state(ctl.ws)
    watcher = mirrored.watcher
    w.unmirror()
    assert not ctl.mirroring and state(ctl.ws) == before
    assert not ctl.can_undo() and not ctl.can_redo()
    assert not w.a_undo.isEnabled() and not w.a_redo.isEnabled()
    for a in (w.a_new, w.a_open, w.a_mirror):
        assert a.isEnabled()
    assert not w.a_unmirror.isEnabled()
    assert not w.mirror_banner.isVisible() and not w.mirror_frame.isVisible()
    assert w.windowTitle() == 'MIDI Interchange' and w._mirror_watcher is None
    assert w.main_toolbar.widgetForAction(w.a_mirror).styleSheet() == ''
    assert 'Unmirrored Song.mid' in mirrored.status()
    ctl.rename_track(ctl.ws.tracks[0].id, 'Renamed')           # editing works again, with undo
    assert ctl.ws.tracks[0].name == 'Renamed' and ctl.can_undo()
    ctl.undo()
    assert ctl.ws.tracks[0].name == 'Bass'
    assert not w.track_panel.header(ctl.ws.tracks[0].id).name_edit.isReadOnly()
    assert w.track_panel.header(ctl.ws.tracks[0].id).remove_btn.isEnabled()
    # later file changes are ignored
    snapshot = state(ctl.ws)
    save_replace(mirrored.path, song(Pad=50))
    advance(watcher, mirrored.clock, 5)
    QApplication.processEvents()
    assert state(ctl.ws) == snapshot


def test_the_unmirror_button_and_menu_action_unmirror(mirrored):
    mirrored.win.unmirror_btn.click()
    assert not mirrored.ctl.mirroring
    mirrored.win.start_mirror(str(mirrored.path), clock=FakeClock(), executor=Inline())
    mirrored.win._mirror_watcher._timer.stop()
    mirrored.win.a_unmirror.trigger()
    assert not mirrored.ctl.mirroring


def test_unmirror_applies_a_read_that_was_waiting_for_nothing(mirrored):
    tl = mirrored.win.timeline
    tl._external_drag = True
    mirrored.saved(song(Bass=40, Keys=60, Lead=70))
    tl._external_drag = False
    mirrored.win.unmirror()
    QApplication.processEvents()
    assert [t.name for t in mirrored.ctl.ws.tracks] == ['Bass', 'Keys']     # the waiting read is dropped


def test_mirroring_can_start_again_after_unmirror(mirrored):
    w = mirrored.win
    w.unmirror()
    w._confirm_mirror_replace = lambda: True
    assert w.start_mirror(str(mirrored.path), clock=FakeClock(), executor=Inline())
    w._mirror_watcher._timer.stop()
    assert w.ctl.mirroring and w.windowTitle().endswith('Song.mid')


# -- session -----------------------------------------------------------------------

def test_a_session_captured_while_mirroring_restores_as_a_normal_workspace(mirrored, tmp_path):
    w, ctl = mirrored.win, mirrored.ctl
    r = ctl.add_range(F(0), F(2))
    ctl.set_range_tracks(r.id, True)
    ctl.set_mute(ctl.ws.tracks[1].id, True)
    sess = capture(w)
    assert set(sess.settings) == set(capture_keys_normal(w))               # no new session field
    assert 'mirror' not in repr(sess.settings).lower()
    ids = [t.id for t in ctl.ws.tracks]
    ranges = [(x.id, x.start, x.end, sorted(x.excluded), x.track_locked) for x in ctl.ws.ranges]
    w.unmirror()
    ctl.new_document()
    assert ctl.ws.tracks == []
    apply_session(w, sess)
    assert not ctl.mirroring and not w.mirror_banner.isVisible()
    assert [t.id for t in ctl.ws.tracks] == ids
    assert [(x.id, x.start, x.end, sorted(x.excluded), x.track_locked) for x in ctl.ws.ranges] == ranges
    assert ctl.ws.tracks[1].muted
    ctl.rename_track(ctl.ws.tracks[0].id, 'Edited')
    assert ctl.ws.tracks[0].name == 'Edited'


def capture_keys_normal(w):
    return capture(w).settings.keys()


def test_a_crash_while_mirroring_restores_the_last_checkpoint_as_a_normal_workspace(mirrored, tmp_path):
    w, ctl = mirrored.win, mirrored.ctl
    store = SessionStore(tmp_path / 'session')
    store.begin_run()
    store.save(capture(w))                                          # the last periodic save, taken while mirroring
    mirrored.saved(song(Bass=40, Keys=60, Lead=70, Pad=72))          # then more re-imports, never saved
    assert store.begin_run() is True                                # the next launch: the marker was left behind
    restored = SessionStore(tmp_path / 'session').load()
    w.unmirror()
    ctl.new_document()
    apply_session(w, restored)
    assert not ctl.mirroring and [t.name for t in ctl.ws.tracks] == ['Bass', 'Keys']
    assert w.windowTitle() == 'MIDI Interchange'
    assert not ctl.can_undo()


def test_closing_the_window_stops_the_watch(win, mid, monkeypatch):
    monkeypatch.setattr(win, '_confirm_mirror_replace', lambda: True)
    assert win.start_mirror(str(mid), clock=FakeClock(), executor=Inline())
    watcher = win._mirror_watcher
    assert watcher._timer.isActive()
    win.close()
    assert win._mirror_watcher is None
    win.ctl.leave_mirror()


# ------------------------------------------- remembering the file's mute and solo (plan refinement)

def file_result(muted=(), soloed=(), **parts):
    """A re-import whose file saved the named tracks muted or soloed (a reader that keeps that state)."""
    r = result_of(song(**parts), preserve=True)
    for t in r.tracks:
        t.muted, t.soloed = t.name in muted, t.name in soloed
    return r


def mirroring_ctl(**kw):
    ctl = Controller()
    ctl.enter_mirror(file_result(**kw))
    return ctl


def test_a_track_you_unmuted_stays_unmuted_across_a_save(app):
    ctl = mirroring_ctl(muted=('Bass',), Bass=40, Keys=60)
    bass = by_name(ctl.ws, 'Bass')
    assert bass.muted
    ctl.set_mute(bass.id, False)
    ctl.apply_mirror(file_result(muted=('Bass',), Bass=40, Keys=60))          # the file still has it muted
    assert not by_name(ctl.ws, 'Bass').muted


def test_a_track_you_did_not_touch_follows_the_file(app):
    ctl = mirroring_ctl(muted=('Bass',), Bass=40, Keys=60)
    ctl.apply_mirror(file_result(muted=('Keys',), Bass=40, Keys=60))
    assert (by_name(ctl.ws, 'Bass').muted, by_name(ctl.ws, 'Keys').muted) == (False, True)


def test_a_track_you_muted_keeps_it_until_synced(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    ctl.set_mute(by_name(ctl.ws, 'Keys').id, True)
    ctl.apply_mirror(file_result(Bass=40, Keys=60))
    assert by_name(ctl.ws, 'Keys').muted
    assert ctl.ms_differs() and ctl.ms_differs(by_name(ctl.ws, 'Keys').id) and not ctl.ms_differs(by_name(ctl.ws, 'Bass').id)


def test_sync_all_puts_every_track_back_to_the_file(app):
    ctl = mirroring_ctl(soloed=('Keys',), Bass=40, Keys=60)
    ctl.toggle_solo(by_name(ctl.ws, 'Keys').id)                    # solo off in the app
    ctl.set_mute(by_name(ctl.ws, 'Bass').id, True)
    assert ctl.ms_differs()
    ctl.sync_mutes()
    assert {t.name: (t.muted, t.soloed) for t in ctl.ws.tracks} == {'Bass': (False, False), 'Keys': (False, True)}
    assert not ctl.ms_differs()


def test_sync_one_leaves_the_other_tracks_alone(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    bass, keys = by_name(ctl.ws, 'Bass'), by_name(ctl.ws, 'Keys')
    ctl.set_mute(bass.id, True)
    ctl.set_mute(keys.id, True)
    ctl.sync_mutes(bass.id)
    assert not bass.muted and keys.muted and ctl.ms_differs() and not ctl.ms_differs(bass.id)


def test_sync_makes_no_undo_step_and_follows_ranges(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    ctl.set_mute(by_name(ctl.ws, 'Bass').id, True)
    ctl.sync_mutes()
    assert not ctl.can_undo() and not ctl.can_redo()
    assert all(not r.excluded for r in ctl.ws.ranges)


def test_new_tracks_take_the_file_state_and_are_not_marked(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    ctl.apply_mirror(file_result(muted=('Lead',), Bass=40, Keys=60, Lead=70))
    lead = by_name(ctl.ws, 'Lead')
    assert lead.muted and not ctl.ms_differs(lead.id)


def test_unmirror_forgets_the_remembered_state(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    ctl.set_mute(by_name(ctl.ws, 'Bass').id, True)
    ctl.leave_mirror()
    assert not ctl.ms_differs() and by_name(ctl.ws, 'Bass').muted


def test_the_marker_the_tooltip_and_the_menu_item(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    bass = by_name(ctl.ws, 'Bass')
    h = w.track_panel.header(bass.id)
    assert not w.a_sync_mutes.isEnabled() and 'Differs' not in h.mute_btn.toolTip()
    assert theme.MIRROR.name() not in h.mute_btn.styleSheet()
    h.mute_btn.click()
    QApplication.processEvents()
    assert w.a_sync_mutes.isEnabled()
    assert theme.MIRROR.name() in h.mute_btn.styleSheet() and theme.MIRROR.name() in h.solo_btn.styleSheet()
    assert 'Differs from the file: here it is muted, the file saved it not muted or soloed' in h.mute_btn.toolTip()
    other = w.track_panel.header(by_name(ctl.ws, 'Keys').id)
    assert theme.MIRROR.name() not in other.mute_btn.styleSheet()
    w.a_sync_mutes.trigger()
    QApplication.processEvents()
    assert not bass.muted and not w.a_sync_mutes.isEnabled()
    assert theme.MIRROR.name() not in h.mute_btn.styleSheet()


def test_the_track_menu_offers_follow_file_only_when_it_differs(mirrored):
    w, ctl = mirrored.win, mirrored.ctl
    bass = by_name(ctl.ws, 'Bass')
    menu = main_window.QMenu()
    w._add_track_actions(menu, bass.id)
    follow = next(a for a in menu.actions() if a.text() == "Follow File's Mute/Solo")
    assert not follow.isEnabled()
    ctl.set_mute(bass.id, True)
    menu = main_window.QMenu()
    w._add_track_actions(menu, bass.id)
    follow = next(a for a in menu.actions() if a.text() == "Follow File's Mute/Solo")
    assert follow.isEnabled()
    follow.trigger()
    assert not bass.muted


def test_the_menu_item_is_greyed_outside_mirroring(win):
    assert not win.a_sync_mutes.isEnabled()
    win.ctl.set_mute(win.ctl.ws.tracks[0].id, True)
    assert not win.a_sync_mutes.isEnabled()


# ------------------------------------------------------ diagnostics (the log of what the watcher saw)

def diag_lines(watcher):
    lines = []
    watcher.diag.connect(lambda text, notable: lines.append((text, notable)))
    return lines


def moved_song(start):
    """One track, one clip whose note starts at `start` beats."""
    return smf([conductor(BEAT), track(note(0, 40, start * BEAT, 4 * BEAT), 'Bass')])


def test_the_log_shows_a_save_from_the_change_to_the_read_and_names_the_moved_clip(tmp_path):
    p = tmp_path / 'Song.mid'
    p.write_bytes(moved_song(0))
    w, clock, ev = watch(p)
    lines = diag_lines(w)
    save_in_place(p, moved_song(4))
    advance(w, clock, 1.5)
    text = [t for t, _ in lines]
    assert any('changed on disk: size' in t and 'modified' in t and 'inode' in t for t in text)
    assert any('reading (still for' in t for t in text)
    read = next(t for t in text if 'read ok: NEW bytes' in t)
    assert 'Bass:' in read and ' -> ' in read, read          # which track's clips moved, before and after
    assert all(t[:2].isdigit() and t[8] == '.' for t in text)  # wall-clock stamped HH:MM:SS.mmm
    assert [n for t, n in lines if 'changed on disk' in t] == [True]       # worth the status bar


def test_the_log_says_when_a_save_changed_no_bytes(tmp_path):
    p = tmp_path / 'Song.mid'
    p.write_bytes(moved_song(0))
    w, clock, ev = watch(p)
    lines = diag_lines(w)
    os.utime(p, ns=(1_700_000_000 * 10**9, 1_700_000_000 * 10**9))        # a touch, as Reason sometimes does
    advance(w, clock, 1.5)
    assert any('the same as the last import, nothing to do' in t and 'no clip positions changed' in t for t, _ in lines)


def test_the_log_says_when_a_read_was_discarded_or_failed(tmp_path):
    p = tmp_path / 'Song.mid'
    p.write_bytes(moved_song(0))
    manual = Manual()
    w, clock, ev = watch(p, manual)
    lines = diag_lines(w)
    save_in_place(p, moved_song(4))
    advance(w, clock, 1.0)                                   # the read is queued but not run
    save_in_place(p, moved_song(8))                          # saved again during the read
    advance(w, clock, 0.25)
    manual.run()
    advance(w, clock, 0.25)
    assert any('read discarded: saved again during the read' in t for t, _ in lines)
    bad = tmp_path / 'Bad.mid'
    bad.write_bytes(b'nope' * 20)
    w2, clock2, ev2 = watch(p)
    lines2 = diag_lines(w2)
    save_in_place(p, b'nope' * 20)
    advance(w2, clock2, 1.5)
    assert any('read FAILED (attempt 1)' in t and n for t, n in lines2)


def test_the_window_writes_the_log_file_and_offers_it(win, mid, monkeypatch, tmp_path):
    monkeypatch.setattr(win, '_confirm_mirror_replace', lambda: True)
    log = tmp_path / 'logs' / 'mirror-log.txt'
    assert not win.a_mirror_log.isEnabled()
    clock = FakeClock()
    assert win.start_mirror(str(mid), clock=clock, executor=Inline(), log_path=str(log))
    win._mirror_watcher._timer.stop()
    try:
        assert win.a_mirror_log.isEnabled()
        save_in_place(mid, song(Bass=40, Keys=60, Lead=70))
        advance(win._mirror_watcher, clock, 1.5)
        QApplication.processEvents()
        text = log.read_text(encoding='utf-8')
        assert str(mid) in text.splitlines()[0]
        for expected in ('baseline:', 'changed on disk:', 'reading (', 'read ok: NEW bytes', 'applied to the timeline: 3 tracks'):
            assert expected in text, expected
    finally:
        win.unmirror()
    assert 'unmirrored' in log.read_text(encoding='utf-8')
    assert win.a_mirror_log.isEnabled()                       # the log stays available after unmirroring


def test_a_read_that_waits_for_a_gesture_says_so_once(mirrored, tmp_path, monkeypatch):
    w = mirrored.win
    log = tmp_path / 'mirror-log.txt'
    w._open_mirror_log(str(log))
    monkeypatch.setattr(type(w.timeline), 'gesture_active', property(lambda self: True))
    w._mirror_pending = file_result(Bass=40, Keys=60)
    w._apply_mirror_pending()
    w._apply_mirror_pending()
    text = log.read_text(encoding='utf-8')
    assert text.count('import waiting: a gesture is in progress') == 1
    assert 'Mirror: import waiting' in w.statusBar().currentMessage()
    w._mirror_pending = None
    w._close_mirror_log()


def test_a_tracks_controller_display_can_be_set_while_mirroring_and_survives_a_save(app):
    ctl = mirroring_ctl(Bass=40, Keys=60)
    bass = by_name(ctl.ws, 'Bass')
    ctl.set_track_controller(bass.id, 'pb')                  # a display choice, not an edit
    assert bass.controller == 'pb'
    assert not ctl._undo                                     # and no undo step
    ctl.apply_mirror(file_result(Bass=40, Keys=60))
    assert by_name(ctl.ws, 'Bass').controller == 'pb'
