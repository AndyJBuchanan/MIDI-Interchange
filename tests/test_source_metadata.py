"""Source provenance survives transport unwrapping, undo and the information UI."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QLabel

from helpers import note, smf, track
from test_ui_assembly import app
from midi_interchange.interchange.drag_import import extract_payloads
from midi_interchange.interchange.payload import Payload
from midi_interchange.ui.controller import Controller
from midi_interchange.ui.source_info import SourceInfoDialog


@pytest.mark.parametrize('transport', ['file', 'folder', 'rmid', 'mime'])
def test_input_size_preserved_through_transport_and_undo(app, tmp_path, transport):
    midi = smf([track(note(0, 60, 0, 480), 'Lead')])
    mime = QMimeData()
    if transport == 'mime':
        original = b'wrapper:' + midi
        mime.setData('audio/midi', original)
    else:
        original = midi
        if transport == 'rmid':
            chunk = b'data' + len(midi).to_bytes(4, 'little') + midi
            if len(midi) % 2:
                chunk += b'\x00'
            original = b'RIFF' + (len(chunk) + 4).to_bytes(4, 'little') + b'RMID' + chunk
        path = tmp_path / ('lead.rmi' if transport == 'rmid' else 'lead.mid')
        path.write_bytes(original)
        mime.setUrls([QUrl.fromLocalFile(str(tmp_path if transport == 'folder' else path))])
    payloads, diagnostics = extract_payloads(mime)
    assert not diagnostics and len(payloads) == 1
    controller = Controller()
    assert controller.import_payloads(payloads) == []
    source = controller.ws.sources[0]
    assert source.byte_size == len(original) and source.raw == b''
    assert source.track_names == ('Lead',)
    controller.undo()
    assert controller.ws.sources == []
    controller.redo()
    assert controller.ws.sources == [source]
    assert controller.ws.tracks[0].clips[0].events


@pytest.mark.parametrize('size', [12345, None])
def test_source_information_uses_metadata_independently_of_raw(app, size):
    controller = Controller()
    controller.import_payloads([Payload('lead.mid', smf([track(note(0, 60, 0, 480), 'Lead')]))])
    source = replace(controller.ws.sources[0], byte_size=size)
    controller.ws.sources = [source]
    dialog = SourceInfoDialog(controller.ws, controller.ws.tracks[0])
    expected = '12,345 bytes' if size is not None else 'size unknown'
    assert source.raw == b''
    assert expected in source.describe()
    assert source.file_summary in [label.text() for label in dialog.findChildren(QLabel)]
    dialog.close()
