"""Per-user application ownership and acknowledged local file-open requests."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_REQUEST_BYTES = 1024 * 1024


class InstanceError(RuntimeError):
    pass


class SingleInstance(QObject):
    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(directory / 'instance.lock'))
        # Only dead process detection may reclaim ownership, never elapsed time.
        self.lock.setStaleLockTime(0)
        self.name = 'midi-interchange-' + hashlib.sha256(str(directory).encode()).hexdigest()[:24]
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self.primary = False
        self.closing = False
        self._buffers = {}
        self._seen = set()
        self._pending = []
        self._handler = None
        self._draining = False

    def acquire(self) -> bool:
        self.primary = self.lock.tryLock(0)
        if self.primary:
            # Safe only while holding the ownership lock (also clears crash debris).
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                self.primary = False
                raise InstanceError(self.server.errorString())
        elif self.lock.error() != QLockFile.LockFailedError:
            raise InstanceError('Cannot acquire the application lock')
        return self.primary

    def handoff(self, paths: list[str], *, timeout_ms=30000, request_id=None) -> None:
        """Secondary process only. Acknowledgment means queued by the primary."""
        request_id = request_id or uuid.uuid4().hex
        payload = json.dumps({'id': request_id, 'paths': paths}).encode() + b'\n'
        if len(payload) > MAX_REQUEST_BYTES:
            raise InstanceError('Too many file paths in one launch')
        deadline = time.monotonic() + timeout_ms / 1000
        socket = QLocalSocket()
        # Owner may have acquired its lock just before starting its server.
        while time.monotonic() < deadline:
            socket.connectToServer(self.name)
            if socket.waitForConnected(min(250, timeout_ms)):
                break
            socket.abort()
            time.sleep(0.05)
        else:
            raise InstanceError('The running app did not accept the file-open request')
        try:
            socket.write(payload)
            if socket.bytesToWrite() and not socket.waitForBytesWritten(max(1, int((deadline - time.monotonic()) * 1000))):
                raise InstanceError('Could not send files to the running app')
            reply = bytearray()
            while b'\n' not in reply and time.monotonic() < deadline:
                if socket.bytesAvailable() or socket.waitForReadyRead(max(1, int((deadline - time.monotonic()) * 1000))):
                    reply.extend(bytes(socket.readAll()))
                else:
                    break
            if bytes(reply) != (request_id + '\n').encode():
                raise InstanceError('The running app did not acknowledge the request; files were not confirmed imported')
        finally:
            socket.abort()

    def _connected(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._discard(s))
            # Bound abandoned/incomplete client lifetime as well as message size.
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(30000)
            self._read(socket)

    def _discard(self, socket):
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _read(self, socket):
        buf = self._buffers.get(socket)
        if buf is None:
            return
        buf.extend(bytes(socket.readAll()))
        if len(buf) > MAX_REQUEST_BYTES or self.closing:
            socket.abort()
            return
        if b'\n' not in buf:
            return
        try:
            request = json.loads(bytes(buf))
            rid, paths = request['id'], request['paths']
            if (type(rid) is not str or not rid or len(rid) > 128
                    or type(paths) is not list or any(type(p) is not str or '\0' in p for p in paths)):
                raise ValueError('Invalid request')
        except (ValueError, KeyError, TypeError, RecursionError):
            socket.abort()
            return
        self._buffers.pop(socket, None)
        if rid not in self._seen:
            self._seen.add(rid)
            self.enqueue(paths)
        socket.write((rid + '\n').encode())
        socket.disconnectFromServer()

    def enqueue(self, paths: list[str]) -> None:
        self._pending.append(list(paths))
        QTimer.singleShot(0, self._drain)

    def set_handler(self, handler):
        self._handler = handler
        QTimer.singleShot(0, self._drain)

    def _drain(self):
        if self._handler is None or self._draining or self.closing:
            return
        self._draining = True
        try:
            while self._pending and not self.closing:
                self._handler(self._pending.pop(0))
        finally:
            self._draining = False

    @property
    def has_pending(self):
        return bool(self._pending) or self._draining

    def close(self):
        self.closing = True
        self.server.close()
        for socket in list(self._buffers):
            socket.abort()
        if self.primary:
            self.lock.unlock()
            self.primary = False
