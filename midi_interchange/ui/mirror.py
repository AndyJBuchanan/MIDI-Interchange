"""Mirror mode: watch one file and re-read it when it has been saved (docs/plans/mirror-mode.md).

Polling, not QFileSystemWatcher: a save by temp file and rename drops a file watch,
and one os.stat four times a second costs nothing. The signature (inode, size, mtime)
catches both ways the DAWs save (Cubase replaces the file, Reason writes in place).
A change is read only once it has stayed the same for SETTLE seconds, on a worker
thread; the result is applied on the main thread, from poll().
"""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from ..interchange.readers import payload_from_path, read_payload

POLL_MS = 250            # poll interval
SETTLE = 0.5             # seconds the signature must stay the same before a read
RETRY_AFTER = 2.0        # seconds before retrying a failed read
MAX_RETRIES = 3          # retries while the signature stays the same
MISSING_AFTER = 3.0      # seconds gone before "not found; waiting"

Signature = tuple[int, int, int]


def file_signature(path: str) -> Signature:
    st = os.stat(path)
    return (st.st_ino, st.st_size, st.st_mtime_ns)


class _ChangedWhileReading(Exception):
    pass


@dataclass
class Snapshot:
    signature: Signature     # of the file before it was read
    digest: str              # SHA-256 of its bytes
    result: object           # the reader's ImportResult


def _file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_snapshot(path: str) -> Snapshot:
    """Read-only: stat, hash and parse the file. Raises if it changed while being read."""
    before = file_signature(path)
    digest = _file_digest(path)
    result = read_payload(payload_from_path(path))
    if file_signature(path) != before:
        raise _ChangedWhileReading()
    return Snapshot(before, digest, result)


class _InlineExecutor:
    """Runs the read on the calling thread (tests)."""

    def submit(self, fn, *args) -> Future:
        f: Future = Future()
        try:
            f.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001
            f.set_exception(exc)
        return f


class MirrorWatcher(QObject):
    imported = Signal(object)     # a new ImportResult whose bytes differ from the last imported
    unchanged = Signal()          # the file was saved again with identical bytes
    failed = Signal(str)          # a read failed: the reason (see .retrying)
    missingChanged = Signal(bool)

    def __init__(self, path: str, clock=time.monotonic, executor=None, reader=read_snapshot,
                 parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.clock = clock
        self._own_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="mirror")
        self._reader = reader
        self.applied_sig: Signature | None = None
        self.applied_digest: str | None = None
        self.obs_sig: Signature | None = None     # the latest signature seen (None: file missing)
        self.obs_since = 0.0
        self.generation = 0
        self.missing = False
        self.retrying = False
        self.read_count = 0
        self._missing_since: float | None = None
        self._future: Future | None = None
        self._future_generation = 0
        self._fail_count = 0
        self._next_retry = 0.0
        self._stopped = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    # -- control -----------------------------------------------------------
    def set_baseline(self, snapshot: Snapshot) -> None:
        """The import already applied (the first one): changes are measured from it."""
        self.applied_sig, self.applied_digest = snapshot.signature, snapshot.digest
        self.obs_sig, self.obs_since = snapshot.signature, self.clock()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()
        self._future = None
        if self._own_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # -- one poll ----------------------------------------------------------
    def poll(self) -> None:
        if self._stopped:
            return
        now = self.clock()
        try:
            sig: Signature | None = file_signature(self.path)
        except OSError:
            sig = None
        if sig is None:
            if self._missing_since is None:
                self._missing_since = now
            if not self.missing and now - self._missing_since > MISSING_AFTER:
                self.missing = True
                self.missingChanged.emit(True)
        else:
            self._missing_since = None
            if self.missing:
                self.missing = False
                self.missingChanged.emit(False)
        if sig != self.obs_sig:
            self.obs_sig, self.obs_since = sig, now
            self.generation += 1
            self._fail_count = 0
            self.retrying = False
        self._collect(now)
        if self._ready_to_read(now):
            self._future_generation = self.generation
            self.read_count += 1
            self._future = self._executor.submit(self._reader, self.path)
            self._collect(now)       # a synchronous executor is already done

    def _ready_to_read(self, now: float) -> bool:
        if self._future is not None or self.obs_sig is None or self.obs_sig == self.applied_sig:
            return False
        if now - self.obs_since < SETTLE:
            return False
        return self._fail_count == 0 or (self._fail_count <= MAX_RETRIES and now >= self._next_retry)

    def _collect(self, now: float) -> None:
        fut = self._future
        if fut is None or not fut.done():
            return
        self._future = None
        stale = self._future_generation != self.generation
        try:
            snap = fut.result()
        except _ChangedWhileReading:
            return                      # the file moved on: the next poll reads it once it settles
        except Exception as exc:        # noqa: BLE001 - a bad read must never end the watch
            if stale:
                return
            self._fail_count += 1
            self._next_retry = now + RETRY_AFTER
            self.retrying = self._fail_count <= MAX_RETRIES
            self.failed.emit(str(exc) or type(exc).__name__)
            return
        if stale:
            return                      # saved again during the read: discard, read again after it settles
        self._fail_count = 0
        self.retrying = False
        self.applied_sig = snap.signature
        if snap.digest == self.applied_digest:
            self.unchanged.emit()
            return
        self.applied_digest = snap.digest
        self.imported.emit(snap.result)
