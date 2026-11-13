"""Persistent workspace fidelity, hostile-file recovery and application lifecycle."""
import json
import threading
import time
from dataclasses import fields
from fractions import Fraction as F
from pathlib import Path

import mido
import pytest
from mido.midifiles.meta import UnknownMetaMessage
from PySide6.QtCore import QEvent, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from helpers import conductor, load, note, smf, to_bytes, track
from test_ui_assembly import app
from midi_interchange.core.document import Workspace
from midi_interchange.core.export_smf import ExportMode, ExportOptions, build_exports
from midi_interchange.core.ranges import Range
from midi_interchange.core.import_smf import import_smf_bytes
from midi_interchange.core.session import RECORDS, SCHEMA_VERSION, Session, SessionStore, decode, encode
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui.main_window import MainWindow
from midi_interchange.ui.session import (PERSISTENCE_SETTING, SessionLifecycle, apply_session,
                                        capture)


def rich_workspace(tmp_path):
    data = smf([conductor(960, tempos=((0, 103), (1500, 117)), sigs=((0, 7, 8),)),
                track([*note(2, 60, 1, 3000),
                       (2, mido.Message('control_change', channel=2, control=11, value=90)),
                       (3, mido.Message('program_change', channel=2, program=27)),
                       (4, mido.Message('sysex', data=(0, 1, 127))),
                       (5, mido.MetaMessage('lyrics', text='caf\xe9')),
                       (6, UnknownMetaMessage(0x71, data=(0, 255, 23)))], 'Lead')], ppq=960)
    path = tmp_path / 'original.mid'
    path.write_bytes(data)
    ws = Workspace()
    ws.add_import(*import_smf_bytes(data, path.name, path=str(path), app="Cubase"))
    ws.add_import(*import_smf_bytes(
        smf([track(note(8, 48, 0, 960), 'Bass')]), 'bass.mid'))
    a, b = ws.tracks
    ws.duplicate_clip(a.clips[0].id, F(5))
    a.clips[0].trim_start, a.clips[0].trim_end = F(1, 3), F(2)
    a.clips[0].set_start(F(0))  # negative full offset is legitimate after trimming
    a.name, a.color, a.muted, a.soloed, a.export_channel = 'Vocal', '#123456', True, True, 10
    a.auto_trim = True
    b.muted = True
    ws.ranges = [Range(F(0), F(2), 'Verse'), Range(F(4), F(9), '', excluded={a.id}, track_locked=True)]
    ws.sync_ranges()
    path.unlink()
    return ws


def roundtrip(session):
    return decode(json.loads(json.dumps(encode(session))))


def export_bytes(ws, mode):
    return [(r.label, to_bytes(r.midi)) for r in build_exports(ws, ExportOptions(mode=mode))]


def test_explicit_schema_covers_all_persisted_model_fields():
    # A future model field must trigger a schema/compatibility decision.
    for cls, names in RECORDS.items():
        assert set(names.split()) == {f.name for f in fields(cls)}
    assert set(Workspace().snapshot()) == {f.name for f in fields(Workspace) if not f.name.startswith('_')}


def test_roundtrip_exact_data_relationships_and_every_export_mode(tmp_path):
    ws = rich_workspace(tmp_path)
    session = Session(ws.snapshot(), {})
    saved = roundtrip(session)
    assert encode(saved) == encode(session)
    restored = Workspace()
    restored.restore(saved.workspace)
    assert restored.tracks[0].clips[0].events is restored.tracks[0].clips[1].events
    assert restored.tracks[0].muted and restored.tracks[0].soloed
    for mode in ExportMode:
        assert export_bytes(ws, mode) == export_bytes(restored, mode)


def test_real_cubase_lyric_fixture(tmp_path):
    data = (Path(__file__).parents[1] / 'samples/non-synthetic/verse 1.mid').read_bytes()
    ws = load(data)
    restored = Workspace()
    restored.restore(roundtrip(Session(ws.snapshot(), {})).workspace)
    assert any(e.type == 'lyrics' for t in restored.tracks for c in t.clips for e in c.events)
    assert export_bytes(ws, ExportMode.WHOLE) == export_bytes(restored, ExportMode.WHOLE)


def test_app_version_is_provenance_schema_is_compatibility_gate(tmp_path):
    data = encode(Session(rich_workspace(tmp_path).snapshot(), {}))
    data['app_version'] = '999.0.0'
    decode(data)
    for version in (0, SCHEMA_VERSION + 1, '1', True, None):
        data['schema_version'] = version
        with pytest.raises(ValueError, match='schema'):
            decode(data)


@pytest.mark.parametrize('damage', [
    lambda d: d['workspace']['tracks'][0]['data'].__setitem__('muted', 'false'),
    lambda d: d['workspace']['tracks'][0]['data'].__setitem__('export_channel', 17),
    lambda d: d['workspace']['tracks'][0]['data'].__setitem__('color', 'invalid'),
    lambda d: d['workspace']['tracks'][1]['data'].__setitem__('id', d['workspace']['tracks'][0]['data']['id']),
    lambda d: d['workspace'].__setitem__('tempo_source_id', 'missing'),
    lambda d: d['workspace']['tracks'][0]['data']['clips'][0]['data'].__setitem__('source_id', 'missing'),
    lambda d: d['workspace']['tracks'][0]['data']['clips'][0]['data'].__setitem__('events', -1),
    lambda d: d['workspace']['tracks'][0]['data']['clips'][0]['data']['trim_end']['data'].__setitem__(1, 0),
    lambda d: d['events'][0][0]['data']['msg']['data'].__setitem__(1, [0x90, 255, 0]),
    lambda d: d['events'][0][0]['data'].__setitem__('seq', -1),
    lambda d: d['workspace']['tempo_map']['data']['timesigs'][0]['data'].__setitem__('numerator', 0),
    lambda d: d['workspace']['tempo_map']['data']['tempos'][0]['data'].__setitem__('us_per_beat', 0),
    lambda d: d['workspace']['ranges'][0]['data'].__setitem__('excluded', []),
])
def test_malformed_parseable_workspace_rejected(tmp_path, damage):
    data = encode(Session(rich_workspace(tmp_path).snapshot(), {}))
    damage(data)
    with pytest.raises((ValueError, TypeError, KeyError, IndexError)):
        decode(data)


def test_atomic_failed_write_preserves_checkpoint_and_cleans_temp(tmp_path, monkeypatch):
    store = SessionStore(tmp_path)
    session = Session(Workspace().snapshot(), {})
    store.save(session)
    before = store.path.read_bytes()
    monkeypatch.setattr('midi_interchange.core.session.os.replace', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        store.save(Session(rich_workspace(tmp_path).snapshot(), {}))
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob('.session-*.tmp'))


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow()
    win.settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    win.deleteLater()
    QApplication.processEvents()


def pump_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            pytest.fail('Timed out')
        time.sleep(0.001)


@pytest.fixture
def lifecycle(window, tmp_path):
    managers = []

    def make(*, enabled=None, clock=None, start=True, ready=lambda: None):
        if enabled is not None:
            window.settings.setValue(PERSISTENCE_SETTING, enabled)
        notes = []
        manager = SessionLifecycle(QApplication.instance(), window, tmp_path / 'state',
                                   clock=clock or time.monotonic, notice=notes.append,
                                   close_failure=lambda error: 'cancel')
        manager.notes = notes
        managers.append(manager)
        if start:
            manager.start(ready)
            pump_until(lambda: not manager.restoring)
            manager._timer.stop()  # deterministic tests drive tick explicitly
        return manager
    yield make
    for manager in managers:
        manager.allow_close = True
        manager.stop()
        manager.deleteLater()


def finish_write(manager):
    pump_until(lambda: manager._future is not None and manager._future.done())
    manager.tick()


def test_settings_view_and_fresh_undo_then_new(window, lifecycle, tmp_path):
    ws = rich_workspace(tmp_path)
    window.ctl.restore_session(ws.snapshot(), ws.ranges[1].id)
    QApplication.processEvents()
    window.ctl.set_export_mode(ExportMode.SEPARATE)
    window.ctl.set_trim(True)
    window.snap_combo.setCurrentIndex(4)
    window.timeline.set_lane_height(180)
    window.timeline.set_zoom(1600)
    window.timeline.horizontalScrollBar().setValue(1500)
    window.ctl.checkpoint()
    expected = capture(window)
    manager = lifecycle(start=False)
    manager.store.save(expected)
    window.ctl.new_document()
    manager.start()
    pump_until(lambda: not manager.restoring)
    assert encode(capture(window)) == encode(expected)
    assert not window.ctl.can_undo() and not window.ctl.can_redo()
    window.ctl.new_document()
    manager.request_close()
    pump_until(lambda: manager.allow_close)
    assert not manager.store.load().workspace['tracks']
    assert not manager.store.marker.exists()


@pytest.mark.parametrize('key,value', [('zoom', float('nan')), ('zoom', float('inf')),
                                      ('lane_height', -1), ('export_mode', 'broken'),
                                      ('trim', 1), ('snap', True), ('selected_range_id', 'absent'),
                                      ('vertical_scroll', 2**40)])
def test_bad_settings_rejected_before_model_applied(window, key, value):
    session = capture(window)
    session.settings[key] = value
    with pytest.raises((ValueError, TypeError)):
        apply_session(window, session)
    assert not window.ctl.ws.tracks


@pytest.mark.parametrize("bad", [b'{"schema_version": 888}', b'{"schema_version":', b"not JSON"])
def test_recovery_preserves_bad_file_and_releases_normal_imports(window, lifecycle, bad):
    manager = lifecycle(start=False)
    manager.store.directory.mkdir()
    manager.store.path.write_bytes(bad)
    raw = smf([track(note(0, 60, 0, 960), 'After recovery')])
    manager.start(lambda: window.ctl.import_payloads([Payload('new.mid', raw)]))
    pump_until(lambda: not manager.restoring)
    assert len(window.ctl.ws.tracks) == 1
    assert manager.notes and 'empty workspace' in manager.notes[0]
    assert next(manager.store.directory.glob('session-rejected-*')).read_bytes() == bad
    manager._submit()
    finish_write(manager)
    assert len(manager.store.load().workspace['tracks']) == 1


def test_apply_failure_discards_partial_workspace(window, lifecycle, tmp_path, monkeypatch):
    manager = lifecycle(start=False)
    session = Session(rich_workspace(tmp_path).snapshot(), capture(window).settings)
    manager.store.save(session)
    original = window.timeline.set_zoom
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError('view failure after model restore')
        return original(*args, **kwargs)
    monkeypatch.setattr(window.timeline, 'set_zoom', fail_once)
    manager.start()
    pump_until(lambda: not manager.restoring)
    assert not window.ctl.ws.tracks
    assert not window.ctl.can_undo()
    assert manager.notes and list(manager.store.directory.glob('session-rejected-*'))


def test_disabled_leaves_all_session_files_untouched(window, lifecycle, tmp_path):
    manager = lifecycle(enabled=False, start=False)
    session = Session(rich_workspace(tmp_path).snapshot(), capture(window).settings)
    manager.store.save(session)
    manager.store.begin_run()
    before = {p.name: p.read_bytes() for p in manager.store.directory.iterdir()}
    manager.start()
    pump_until(lambda: not manager.restoring)
    manager.mark_dirty()
    manager.tick()
    assert not window.ctl.ws.tracks
    assert manager._executor is None
    assert window.close()
    assert before == {p.name: p.read_bytes() for p in manager.store.directory.iterdir()}
    manager.stop()
    enabled = lifecycle(enabled=True)
    assert len(window.ctl.ws.tracks) == 2
    assert any('did not close cleanly' in n for n in enabled.notes)


def test_cadence_activity_gestures_and_dirty_generations(window, lifecycle, monkeypatch):
    now = [0.0]
    manager = lifecycle(clock=lambda: now[0])
    assert manager.enabled
    now[0] = 119
    manager.tick()
    assert manager._future is None
    manager.last_input = 110
    now[0] = 120
    manager.tick()
    assert manager._future is None
    for kind in ('timeline', 'native', 'dialog'):
        window.timeline._external_drag = kind == 'timeline'
        window.ctl.file_drag_active = kind == 'native'
        dialog = QDialog(window) if kind == 'dialog' else None
        if dialog:
            dialog.setModal(True)
            dialog.show()
        now[0] += 20
        manager.tick()
        assert manager._future is None
        if dialog:
            dialog.close()
        window.timeline._external_drag = window.ctl.file_drag_active = False
    now[0] += 14
    manager.tick()
    assert manager._future is None
    entered, release = threading.Event(), threading.Event()
    original = manager.store.save
    worker_threads = []

    def slow_save(snapshot):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        original(snapshot)
    monkeypatch.setattr(manager.store, 'save', slow_save)
    now[0] += 1
    manager.tick()
    assert entered.wait(2)
    manager.mark_dirty()  # edits during write must stay dirty
    future = manager._future
    now[0] += 200
    manager.tick()
    assert manager._future is future
    release.set()
    finish_write(manager)
    assert manager.generation > manager.saved_generation
    assert worker_threads == [manager._executor.submit(threading.get_ident).result()]
    assert worker_threads[0] != threading.get_ident()
    now[0] += 119
    manager.tick()
    assert manager._future is None
    now[0] += 1
    manager.tick()
    finish_write(manager)
    assert manager.generation == manager.saved_generation


def test_undo_settings_view_and_input_notifications_mark_state(window, lifecycle):
    manager = lifecycle()
    changes = [lambda: window.ctl.import_payloads([Payload('x.mid', smf([track(note(0, 60, 0, 960))]))]),
               window.ctl.undo, window.ctl.redo,
               lambda: window.ctl.set_trim(True), lambda: window.snap_combo.setCurrentIndex(0),
               lambda: window.timeline.set_zoom(100), lambda: window.timeline.set_lane_height(100)]
    for change in changes:
        before = manager.generation
        change()
        assert manager.generation > before
    before = manager.last_input
    manager.eventFilter(window, QEvent(QEvent.MouseMove))
    assert manager.last_input >= before


def test_close_waits_for_older_write_then_saves_latest(window, lifecycle, monkeypatch):
    manager = lifecycle()
    entered, release = threading.Event(), threading.Event()
    original = manager.store.save
    saved = []

    def slow(snapshot):
        if not saved:
            entered.set()
            assert release.wait(5)
        saved.append(len(snapshot.workspace['tracks']))
        original(snapshot)
    monkeypatch.setattr(manager.store, 'save', slow)
    manager._submit()
    assert entered.wait(2)
    window.ctl.import_payloads([Payload('later.mid', smf([track(note(0, 60, 0, 960))]))])
    assert not window.close()
    assert window.isVisible() and manager.closing
    release.set()
    finish_write(manager)
    finish_write(manager)
    assert manager.allow_close and not window.isVisible()
    assert saved == [0, 1]
    assert len(manager.store.load().workspace['tracks']) == 1


def test_periodic_failure_throttled_and_exit_requires_choice(window, lifecycle, monkeypatch):
    now = [0.0]
    manager = lifecycle(clock=lambda: now[0])
    manager.store.save(capture(window))
    before = manager.store.path.read_bytes()
    original = manager.store.save
    monkeypatch.setattr(manager.store, 'save', lambda s: (_ for _ in ()).throw(OSError('full')))
    now[0] = 120
    manager.tick()
    finish_write(manager)
    assert manager.generation > manager.saved_generation
    assert manager.store.path.read_bytes() == before
    assert 'full' in window.statusBar().currentMessage()
    manager.tick()
    assert manager._future is None
    choices = []
    manager.close_failure = lambda err: choices.append(err) or 'cancel'
    window.close()
    finish_write(manager)
    assert choices == ['full'] and not manager.closing and window.isVisible()
    monkeypatch.setattr(manager.store, 'save', original)
    window.close()
    finish_write(manager)
    assert manager.allow_close and not manager.store.marker.exists()


def test_large_checkpoint_leaves_event_loop_running(window, lifecycle):
    # A substantial event list is encoded only by the worker. GUI timers continue
    # while it runs, and a source edit is kept dirty for the next checkpoint.
    raw = smf([track([ev for i in range(15000) for ev in note(0, 60, i * 20, 10)])])
    window.ctl.import_payloads([Payload('large.mid', raw)])
    manager = lifecycle()
    pulses = []
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: pulses.append(time.monotonic()))
    timer.start()
    manager._submit()
    manager.mark_dirty()
    finish_write(manager)
    timer.stop()
    assert len(pulses) >= 2
    assert manager.generation > manager.saved_generation


def test_failed_preservation_never_overwrites_rejected_session(window, lifecycle, monkeypatch):
    manager = lifecycle(start=False)
    manager.store.directory.mkdir()
    bad = b'old unsupported session'
    manager.store.path.write_bytes(bad)
    original = manager.store.preserve_rejected
    monkeypatch.setattr(manager.store, 'preserve_rejected', lambda: (_ for _ in ()).throw(OSError('read only')))
    manager.start()
    pump_until(lambda: not manager.restoring)
    manager._submit()
    finish_write(manager)
    assert manager.store.path.read_bytes() == bad
    assert manager.saved_generation < manager.generation
    monkeypatch.setattr(manager.store, 'preserve_rejected', original)
    manager._submit()
    finish_write(manager)
    assert next(manager.store.directory.glob('session-rejected-*')).read_bytes() == bad
    assert manager.store.load() is not None


def test_exit_without_save_retains_last_checkpoint_and_unclean_marker(window, lifecycle, monkeypatch):
    manager = lifecycle()
    manager.store.save(capture(window))
    before = manager.store.path.read_bytes()
    monkeypatch.setattr(manager.store, 'save', lambda s: (_ for _ in ()).throw(OSError('full')))
    manager.close_failure = lambda error: 'discard'
    window.close()
    finish_write(manager)
    assert manager.allow_close
    assert manager.store.path.read_bytes() == before
    assert manager.store.marker.exists()


def test_pending_text_edit_committed_on_exit(window, lifecycle):
    manager = lifecycle()
    r = window.ctl.add_range(F(0), F(4))
    ed = window.export_panel.name_edit
    ed.setFocus()
    ed.setText('Final edit')
    assert r.name != 'Final edit'
    window.close()
    finish_write(manager)
    assert manager.store.load().workspace['ranges'][0].name == 'Final edit'


def test_unreadable_session_recovers(window, lifecycle, monkeypatch):
    manager = lifecycle(start=False)
    monkeypatch.setattr(manager.store, 'load', lambda: (_ for _ in ()).throw(OSError('unreadable')))
    manager.start()
    pump_until(lambda: not manager.restoring)
    assert manager.notes and not window.ctl.ws.tracks


def test_snapshot_detached_from_later_edits(window, lifecycle, tmp_path):
    ws = rich_workspace(tmp_path)
    window.ctl.restore_session(ws.snapshot(), ws.ranges[0].id)
    before = capture(window)
    encoded = encode(before)
    window.ctl.ws.tracks[0].name = 'Later'
    window.ctl.ws.tracks[0].clips[0].offset = F(100)
    window.ctl.ws.ranges[1].excluded.clear()
    window.ctl.ws.tracks.reverse()
    assert encode(before) == encoded
