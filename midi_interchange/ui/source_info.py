"""Track ▸ Source Info: the track, its clips, and where each clip came from."""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..core.document import Source, Track, Workspace
from ..core.events import is_note_on


def _channels(chs) -> str:
    return ", ".join(str(c + 1) for c in sorted(chs)) or "—"


def _value(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lab.setWordWrap(True)
    return lab


class SourceInfoDialog(QDialog):
    def __init__(self, ws: Workspace, track: Track, parent=None) -> None:
        super().__init__(parent)
        self.ws = ws
        self.setWindowTitle(f"Source Info — {track.name}")
        self.resize(860, 680)
        self.sources: list[Source] = [s for s in (ws.source(sid) for sid in track.source_ids()) if s]
        tm = ws.tempo_map

        # -- track summary
        summary = QGroupBox("Track")
        f = QFormLayout(summary)
        f.addRow("Name:", _value(track.name))
        if track.original_name and track.original_name != track.name:
            f.addRow("Original name:", _value(track.original_name))
        f.addRow("Clips:", _value(f"{len(track.clips)} from {len(self.sources)} source(s)"))
        f.addRow("Channels:", _value(_channels(track.channels)))
        f.addRow("Events:", _value(str(sum(len(c.events) for c in track.clips))))
        if track.overlaps():
            f.addRow("Overlaps:", _value(f"{len(track.overlaps())} (notes are merged on export)"))

        # -- clips table
        clips_box = QGroupBox("Clips")
        cl = QVBoxLayout(clips_box)
        self.table = QTableWidget(len(track.clips), 6)
        self.table.setHorizontalHeaderLabels(["#", "Start", "End", "Channels", "Notes", "Source"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        for i in range(5):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self._clip_source: list[int] = []
        for row, c in enumerate(track.clips):
            src = ws.source(c.source_id)
            chs = {e.channel for e in c.events if e.channel is not None}
            notes = sum(1 for e in c.events if is_note_on(e.msg))
            cells = [str(row + 1), tm.format_bbt(c.start), tm.format_bbt(c.end), _channels(chs),
                     str(notes), src.name if src else "—"]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if col < 5:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, it)
            self._clip_source.append(self.sources.index(src) if src in self.sources else -1)
        self.table.setMinimumHeight(self.table.horizontalHeader().height()
                                    + 6 * self.table.verticalHeader().defaultSectionSize())
        self.table.itemSelectionChanged.connect(self._clip_selected)
        cl.addWidget(self.table)

        # -- sources: list + details
        src_box = QGroupBox("Sources")
        sl = QHBoxLayout(src_box)
        split = QSplitter(Qt.Horizontal)
        self.src_list = QListWidget()
        for s in self.sources:
            QListWidgetItem(s.name, self.src_list)
        self.src_list.currentRowChanged.connect(self._show_source)
        split.addWidget(self.src_list)
        self.detail_host = QWidget()
        self.detail = QFormLayout(self.detail_host)
        self.detail.setLabelAlignment(Qt.AlignRight)
        split.addWidget(self.detail_host)
        split.setSizes([220, 620])
        sl.addWidget(split)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        lay = QVBoxLayout(self)
        lay.addWidget(summary)
        lay.addWidget(clips_box, 1)
        lay.addWidget(src_box, 1)
        lay.addWidget(buttons)
        if self.sources:
            self.src_list.setCurrentRow(0)

    def _clip_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if rows:
            idx = self._clip_source[rows.pop()]
            if idx >= 0:
                self.src_list.setCurrentRow(idx)

    def _show_source(self, row: int) -> None:
        while self.detail.rowCount():
            self.detail.removeRow(0)
        if not 0 <= row < len(self.sources):
            return
        s = self.sources[row]
        self.detail.addRow("Name:", _value(s.name))
        if s.path:
            path_row = QHBoxLayout()
            path_row.addWidget(_value(s.path), 1)
            reveal = QPushButton("Show in Folder")
            folder = os.path.dirname(s.path)
            reveal.setEnabled(os.path.isdir(folder))
            reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            path_row.addWidget(reveal)
            self.detail.addRow("Path:", path_row)
        else:
            self.detail.addRow("Path:", _value("— (dropped data, no file)"))
        self.detail.addRow("Application:", _value(s.app or "unknown"))
        self.detail.addRow("File:", _value(f"SMF format {s.smf_format} · {s.ppq} PPQ · {len(s.raw):,} bytes"))
        self.detail.addRow("Imported:", _value(f"{s.imported_at:%Y-%m-%d %H:%M:%S}"))
        if s.track_names:
            self.detail.addRow("Original tracks:", _value("\n".join(
                f"{i + 1}. {n or '(unnamed)'}" for i, n in enumerate(s.track_names))))
        if not s.tempo_map.is_empty:
            t = s.tempo_map.effective_tempos()[0]
            ts = s.tempo_map.effective_timesigs()[0]
            tempo = (f"{t.bpm:.2f} BPM, {ts.numerator}/{ts.denominator}  "
                     f"({len(s.tempo_map.tempos)} tempo, {len(s.tempo_map.timesigs)} time-signature events)")
            if self.ws.tempo_source_id == s.id:
                tempo += "\nThis is the workspace tempo map."
            self.detail.addRow("Tempo:", _value(tempo))
        if s.warnings:
            self.detail.addRow("Warnings:", _value("\n".join(f"⚠ {w}" for w in s.warnings)))
