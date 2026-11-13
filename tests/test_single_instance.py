"""Real process lock/socket tests, isolated from normal per-user app storage."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from midi_interchange.single_instance import InstanceError, SingleInstance
from test_ui_assembly import app

ROOT = Path(__file__).parents[1]
OWNER = r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication,QTimer
from midi_interchange.single_instance import SingleInstance
app=QCoreApplication([])
root=Path(sys.argv[1])
owner=SingleInstance(root)
assert owner.acquire()
(root/'ready').write_text('yes')
def receive(paths):
    with (root/'received').open('a', encoding='utf8') as f:
        f.write(json.dumps(paths)+'\n')
QTimer.singleShot(int(sys.argv[2]),lambda: owner.set_handler(receive))
QTimer.singleShot(15000, app.quit)
try:
    app.exec()
finally:
    owner.close()
'''
CLIENT = r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from midi_interchange.single_instance import SingleInstance
app=QCoreApplication([])
client=SingleInstance(Path(sys.argv[1]))
assert not client.acquire()
client.handoff(json.loads(sys.argv[2]), request_id=sys.argv[3], timeout_ms=3000)
'''


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail('Subprocess did not become ready')
        time.sleep(0.01)


@pytest.fixture
def owner(tmp_path):
    processes = []

    def start(delay=0):
        p = subprocess.Popen([sys.executable, '-c', OWNER, str(tmp_path), str(delay)],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append(p)
        wait_for(lambda: (tmp_path / 'ready').exists() or p.poll() is not None)
        assert p.poll() is None, p.communicate()
        return p
    yield start
    for p in processes:
        if p.poll() is None:
            p.kill()
        p.communicate(timeout=5)


def client(tmp_path, paths, rid):
    result = subprocess.run([sys.executable, '-c', CLIENT, str(tmp_path), json.dumps(paths), rid],
                            cwd=ROOT, capture_output=True, timeout=8)
    assert result.returncode == 0, result.stderr.decode()


def received(tmp_path):
    path = tmp_path / 'received'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_handoff_queues_until_ready_and_deduplicates_request(owner, tmp_path):
    owner(1500)
    paths = [str(tmp_path / 'one file.mid'), str(tmp_path / '歌曲.mid')]
    client(tmp_path, paths, 'request-one')
    assert not received(tmp_path)
    client(tmp_path, paths, 'request-one')
    client(tmp_path, [], 'raise-window')
    wait_for(lambda: len(received(tmp_path)) == 2)
    assert received(tmp_path) == [paths, []]
    client(tmp_path, ['later.mid'], 'request-two')
    wait_for(lambda: len(received(tmp_path)) == 3)
    assert received(tmp_path)[2] == ['later.mid']


def test_dead_owner_lock_and_socket_are_recovered(owner, tmp_path, app):
    process = owner()
    process.kill()
    process.communicate(timeout=5)
    next_owner = SingleInstance(tmp_path)
    try:
        assert next_owner.acquire()
        assert next_owner.server.isListening()
    finally:
        next_owner.close()


def test_handoff_failure_is_explicit(tmp_path, app):
    instance = SingleInstance(tmp_path)
    with pytest.raises(InstanceError, match='did not accept'):
        instance.handoff(['do not silently lose.mid'], timeout_ms=100)


def test_nonowner_cannot_remove_live_socket(owner, tmp_path, app):
    owner()
    secondary = SingleInstance(tmp_path)
    assert not secondary.acquire()
    secondary.close()
    client(tmp_path, ['still-listening.mid'], 'after-secondary-close')
    wait_for(lambda: bool(received(tmp_path)))


def test_primary_rejects_handoff_while_closing(tmp_path, app):
    primary = SingleInstance(tmp_path)
    assert primary.acquire()
    primary.closing = True
    p = subprocess.Popen([sys.executable, '-c', CLIENT, str(tmp_path), '["closing.mid"]', 'close'],
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while p.poll() is None and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.001)
        _, error = p.communicate(timeout=2)
        assert p.returncode != 0
        assert b'did not acknowledge' in error
        assert not primary.has_pending
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate()
        primary.close()

ENTRYPOINT = r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QSettings,QStandardPaths,QTimer
import main
root=Path(sys.argv.pop(1))
QStandardPaths.writableLocation=lambda _kind: str(root)
original=main.MainWindow
main.prune_old=lambda: None  # integration test must not touch the user's drag temp files
main.QMessageBox.warning=lambda *args: None
main.QMessageBox.critical=lambda *args: (_ for _ in ()).throw(AssertionError(args[-1]))
def window():
    win=original()
    win.settings=QSettings(str(root/'settings.ini'),QSettings.IniFormat)
    def finish():
        (root/'track-names.json').write_text(json.dumps([t.name for t in win.ctl.ws.tracks]))
        (root/'undo.json').write_text(json.dumps(win.ctl.can_undo()))
        win.close()
    (root/'window-ready').write_text('ready')
    QTimer.singleShot(1000, finish)
    return win
main.MainWindow=window
sys.exit(main.main())
'''


def test_real_entrypoint_restores_before_additive_import_and_closes_cleanly(tmp_path):
    from helpers import note, smf, track
    from midi_interchange.core.session import SessionStore
    first = tmp_path / 'first clip.mid'
    second = tmp_path / 'second clip.mid'
    first.write_bytes(smf([track(note(0, 60, 0, 960), 'First')]))
    second.write_bytes(smf([track(note(1, 48, 0, 960), 'Second')]))
    state = tmp_path / 'state'
    state.mkdir()

    def run(paths):
        return subprocess.run([sys.executable, '-c', ENTRYPOINT, str(state), *map(str, paths)],
                              cwd=ROOT, capture_output=True, timeout=10)
    result = run([first])
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads((state / 'track-names.json').read_text()) == ['First']
    assert not (state / 'session.running').exists()
    first.unlink()  # restoration must use saved source/event data
    result = run([])
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads((state / 'track-names.json').read_text()) == ['First']
    assert json.loads((state / 'undo.json').read_text()) is False
    result = run([second])
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads((state / 'track-names.json').read_text()) == ['First', 'Second']
    assert len(SessionStore(state).load().workspace['tracks']) == 2
    assert not (state / 'session.running').exists()
