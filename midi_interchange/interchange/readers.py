"""Shared import registry used by Open, file drops and MIME MIDI payloads."""
from dataclasses import dataclass
from typing import Callable
import os

from ..core.import_smf import import_smf_bytes, ImportError_
from ..core.import_dawproject import import_dawproject
from .payload import Payload
from ..core.import_result import ImportResult

MAX_FILE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Reader:
    label: str
    extensions: tuple[str, ...]
    detect: Callable[[Payload], bool]
    read: Callable
    path_backed: bool = False
    preserve_track_state: bool = False


def _midi(p):
    data = p.data
    if data.startswith(b'RIFF') and data[8:12] == b'RMID':
        idx = data.find(b'MThd')
        if idx < 0:
            raise ImportError_('RIFF MIDI has no MIDI data chunk')
        data = data[idx:]
    return import_smf_bytes(data, p.name, path=p.path, app=p.app, byte_size=p.byte_size)


READERS = (
    Reader('MIDI files', ('.mid', '.midi', '.smf', '.kar', '.rmi'),
           lambda p: p.data.startswith(b'MThd') or (p.data.startswith(b'RIFF') and p.data[8:12] == b'RMID'), _midi),
    Reader('DAWproject files', ('.dawproject',),
           lambda p: os.path.splitext(p.path or p.name)[1].lower() == '.dawproject',
           lambda p: import_dawproject(p.path, p.name, p.data, byte_size=p.byte_size), path_backed=True, preserve_track_state=True),
)
EXTENSIONS = {ext for reader in READERS for ext in reader.extensions}
FILE_FILTER = 'Supported imports (' + ' '.join('*'+e for r in READERS for e in r.extensions) + ');;' + ';;'.join(
    r.label + ' (' + ' '.join('*'+e for e in r.extensions) + ')' for r in READERS) + ';;All files (*)'


def read_payload(p: Payload):
    for reader in READERS:
        if reader.detect(p):
            return ImportResult(*reader.read(p), preserve_track_state=reader.preserve_track_state)
    raise ImportError_('Not a supported MIDI or project file')


def payload_from_path(path: str) -> Payload:
    """Path-backed projects avoid loading embedded media into memory."""
    size = os.path.getsize(path)
    if any(r.path_backed and os.path.splitext(path)[1].lower() in r.extensions for r in READERS):
        return Payload(os.path.basename(path), b'', path=path, byte_size=size)
    if size > MAX_FILE_BYTES:
        raise ImportError_('MIDI file exceeds the 64 MB limit')
    with open(path, 'rb') as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ImportError_('MIDI file exceeds the 64 MB limit')
    p = Payload(os.path.basename(path), data, path=path, byte_size=len(data))
    if not any(reader.detect(p) for reader in READERS):
        raise ImportError_('Not a supported MIDI or project file')
    return p
