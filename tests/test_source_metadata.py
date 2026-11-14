"""Source provenance survives transport unwrapping, undo and the information UI."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QTextEdit

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
    assert source.file_summary in [value.toPlainText() for value in dialog.findChildren(QTextEdit)]
    dialog.close()


@pytest.mark.parametrize('width, font_size', [(640, 10), (640, 16), (900, 16)])
def test_source_details_wrap_and_scroll_without_clipping(app, width, font_size):
    controller = Controller()
    controller.import_payloads([Payload('lead.mid', smf([track(note(0, 60, 0, 480), 'Lead')]))])
    source = replace(controller.ws.sources[0],
                     path='/folder/' + 'unbroken_segment_' * 45 + '/<input>.mid',
                     track_names=tuple(f'Track {i} ' + 'long name ' * 5 for i in range(40)),
                     warnings=('Warning: ' + 'details ' * 80, 'Final warning'))
    other = replace(source, id='second-source', name='second.mid')
    controller.ws.sources = [source, other]
    track_ = controller.ws.tracks[0]
    track_.clips.append(replace(track_.clips[0], id='second-clip', source_id=other.id))
    dialog = SourceInfoDialog(controller.ws, track_)
    font = dialog.font()
    font.setPointSize(font_size)
    dialog.setFont(font)
    dialog.resize(width, 600)
    dialog.show()
    QTest.qWait(30)
    try:
        scroll = dialog.detail_scroll
        assert scroll.verticalScrollBar().maximum() > 0
        assert scroll.horizontalScrollBar().maximum() == 0
        values = dialog.detail_host.findChildren(QTextEdit)
        path = next(value for value in values if value.toPlainText() == source.path)
        assert path.document().size().height() > path.fontMetrics().height() * 2
        path.selectAll()
        assert path.textCursor().selectedText() == source.path
        for value in values:
            assert value.viewport().height() + 1 >= value.document().size().height()
            assert value.document().idealWidth() <= value.viewport().width() + 1
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        QTest.qWait(10)
        warning = next(value for value in values if value.toPlainText().endswith('Final warning'))
        bottom = warning.mapTo(scroll.viewport(), warning.rect().bottomLeft())
        assert 0 <= bottom.y() <= scroll.viewport().height()
        close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
        assert close.isVisibleTo(dialog)
        assert dialog.sections.orientation() == Qt.Vertical
        old_sizes = dialog.sections.sizes()
        dialog.sections.setSizes([old_sizes[0] + 40, old_sizes[1] - 40])
        QTest.qWait(10)
        assert dialog.sections.sizes()[0] > old_sizes[0]
        dialog.src_list.setCurrentRow(1)
        QTest.qWait(20)
        assert scroll.verticalScrollBar().value() == 0
    finally:
        dialog.close()
