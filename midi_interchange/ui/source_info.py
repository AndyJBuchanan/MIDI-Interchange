"""Track ▸ Source Info: the track, its clips, and where each clip came from."""
from __future__ import annotations

import os
from math import ceil

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLayout, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout,
                               QWidget)

from ..core.document import Source, Track, Workspace
from ..core.document import msg_channels
from ..core.events import is_note_on
from ..core.export_smf import visible_msgs


def _channels(chs) -> str:
    return ", ".join(str(c + 1) for c in sorted(chs)) or "—"


class _ValueText(QTextEdit):
    """Selectable plain text that wraps long tokens and takes its full height.

    Only the enclosing details pane scrolls; individual values never hide lines.
    """
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setStyleSheet("QTextEdit { background: transparent; border: none; }")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self.setPlainText(text)
        self._fit_height()

    def _fit_height(self, *_args) -> None:
        self.setFixedHeight(ceil(self.document().size().height()) + 2 * self.frameWidth())

    def minimumSizeHint(self) -> QSize:
        # QTextEdit's own size hints impose a fixed width floor that
        # setMinimumWidth(0) does not override, since QFormLayout sizes
        # "AllNonFixedFieldsGrow" fields from sizeHint()/minimumSizeHint(),
        # not the widget's minimumSize(). Without this, the details pane
        # grows a horizontal scrollbar whenever that floor exceeds the
        # viewport (font- and platform-dependent).
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(0, super().sizeHint().height())


def _value(text: str) -> _ValueText:
    return _ValueText(text)


class _Label(QLabel):
    """A wrapping label whose column width is capped.

    QFormLayout gives the label column its full one-line sizeHint whenever
    the dialog is wide enough to fit that *plus* the field column's own
    (here: zero) minimum — it only shrinks labels once space runs out
    entirely. That starves the field column on narrow dialogs/large fonts,
    since "enough room" for a one-line label still leaves little left over.
    Capping the width here forces every label to wrap at the same column
    width regardless of how much space is technically available.
    """
    MAX_WIDTH = 150

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setWordWrap(True)

    def sizeHint(self) -> QSize:
        width = min(super().sizeHint().width(), self.MAX_WIDTH)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def _label(text: str) -> QLabel:
    return _Label(text)


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
        f.addRow("Events:", _value(str(sum(len(visible_msgs(c)) for c in track.clips))))
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
            msgs = visible_msgs(c)               # inside the clip's trims
            chs = msg_channels(msgs)
            notes = sum(1 for m in msgs if is_note_on(m))
            cells = [str(row + 1), tm.format_bbt(c.start), tm.format_bbt(c.end), _channels(chs),
                     str(notes), src.name if src else "—"]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if col < 5:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, it)
            self._clip_source.append(self.sources.index(src) if src in self.sources else -1)
        self.table.setMinimumHeight(self.table.horizontalHeader().height()
                                    + 2 * self.table.verticalHeader().defaultSectionSize())
        self.table.itemSelectionChanged.connect(self._clip_selected)
        cl.addWidget(self.table)

        # -- sources: list + details
        src_box = QGroupBox("Sources")
        sl = QHBoxLayout(src_box)
        self.pane = SourcesPane(ws, self.sources)
        self.src_list = self.pane.src_list
        self.detail_host = self.pane.detail_host
        self.detail_scroll = self.pane.detail_scroll
        sl.addWidget(self.pane)

        self.sections = QSplitter(Qt.Vertical)
        self.sections.setChildrenCollapsible(False)
        self.sections.addWidget(clips_box)
        self.sections.addWidget(src_box)
        self.sections.setSizes([180, 300])

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        lay = QVBoxLayout(self)
        lay.addWidget(summary)
        lay.addWidget(self.sections, 1)
        lay.addWidget(buttons)

    def _clip_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if rows:
            idx = self._clip_source[rows.pop()]
            if idx >= 0:
                self.src_list.setCurrentRow(idx)


class SourcesPane(QWidget):
    """A list of sources beside the details of the selected one.

    Shared by the per-track Source Info dialog and the session Sources dialog.
    With `show_usage`, each source's details also say which tracks its clips are on.
    """
    def __init__(self, ws: Workspace, sources: list[Source], show_usage: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.ws = ws
        self.sources = sources
        self.show_usage = show_usage
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.src_list = QListWidget()
        for src in sources:
            QListWidgetItem(src.name, self.src_list)
        self.src_list.currentRowChanged.connect(self._show_source)
        split.addWidget(self.src_list)
        self.detail_host = QWidget()
        self.detail = QFormLayout(self.detail_host)
        self.detail.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.detail.setFormAlignment(Qt.AlignTop)
        self.detail.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.detail.setContentsMargins(4, 4, 4, 4)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail_scroll.setWidget(self.detail_host)
        split.addWidget(self.detail_scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 620])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        if sources:
            self.src_list.setCurrentRow(0)

    def current_source(self) -> Source | None:
        row = self.src_list.currentRow()
        return self.sources[row] if 0 <= row < len(self.sources) else None

    def source_tracks(self, source_id: str) -> list[tuple[Track, int]]:
        """The tracks holding clips from the source, with how many clips each."""
        out = []
        for t in self.ws.tracks:
            n = sum(1 for c in t.clips if c.source_id == source_id)
            if n:
                out.append((t, n))
        return out

    def usage(self, source_id: str) -> str:
        rows = [f"{t.name}: {n} clip{'s' if n != 1 else ''}" for t, n in self.source_tracks(source_id)]
        if rows:
            return "\n".join(rows)
        return "No clips" + (" (kept for its tempo map)" if self.ws.tempo_source_id == source_id else "")

    def _show_source(self, row: int) -> None:
        self.detail_scroll.verticalScrollBar().setValue(0)
        while self.detail.rowCount():
            self.detail.removeRow(0)
        if not 0 <= row < len(self.sources):
            return
        s = self.sources[row]
        self.detail.addRow(_label("Name:"), _value(s.name))
        if s.path:
            self.detail.addRow(_label("Path:"), _value(s.path))
            # A spanning row (not a field alongside the path text) so the
            # button's own intrinsic width never becomes the shared field
            # column's minimum width — that forced a horizontal scrollbar on
            # fonts/platforms where "Show in Folder" is wider than the path
            # column would otherwise need to be.
            reveal = QPushButton("Show in Folder")
            folder = os.path.dirname(s.path)
            reveal.setEnabled(os.path.isdir(folder))
            reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            self.detail.addRow(reveal)
        else:
            self.detail.addRow(_label("Path:"), _value("— (dropped data, no file)"))
        self.detail.addRow(_label("Application:"), _value(s.app or "unknown"))
        self.detail.addRow(_label("File:"), _value(s.file_summary))
        self.detail.addRow(_label("Imported:"), _value(f"{s.imported_at:%Y-%m-%d %H:%M:%S}"))
        if self.show_usage:
            self.detail.addRow(_label("Used by:"), _value(self.usage(s.id)))
        if s.display_offset_note:
            self.detail.addRow(_label("Display:"), _value(s.display_offset_note))
        if s.track_names:
            self.detail.addRow(_label("Original tracks:"), _value("\n".join(
                f"{i + 1}. {n or '(unnamed)'}" for i, n in enumerate(s.track_names))))
        if not s.tempo_map.is_empty:
            t = s.tempo_map.effective_tempos()[0]
            ts = s.tempo_map.effective_timesigs()[0]
            tempo = (f"{t.bpm:.2f} BPM, {ts.numerator}/{ts.denominator}  "
                     f"({len(s.tempo_map.tempos)} tempo, {len(s.tempo_map.timesigs)} time-signature events)")
            if self.ws.tempo_source_id == s.id:
                tempo += "\nThis is the workspace tempo map."
            self.detail.addRow(_label("Tempo:"), _value(tempo))
        if s.warnings:
            self.detail.addRow(_label("Warnings:"), _value("\n".join(f"⚠ {w}" for w in s.warnings)))


class SourcesDialog(QDialog):
    """Every source in the workspace, with the details Source Info shows per track.

    **Solo all source tracks** solos exactly the tracks the selected source feeds and
    closes the dialog; Close (or Esc) changes nothing.
    """
    def __init__(self, ws: Workspace, ctl, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.setModal(True)
        self.setWindowTitle(f"Sources — {len(ws.sources)} in this session")
        self.resize(860, 520)
        self.pane = SourcesPane(ws, list(ws.sources), show_usage=True)
        self.src_list = self.pane.src_list
        self.detail_scroll = self.pane.detail_scroll
        self.detail_host = self.pane.detail_host

        self.buttons = QDialogButtonBox()
        self.solo_btn = self.buttons.addButton("Solo all source tracks", QDialogButtonBox.ActionRole)
        self.solo_btn.setToolTip("Solo exactly the tracks this source's clips are on, and close")
        self.solo_btn.clicked.connect(self._solo)
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.close_btn.setDefault(True)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        if ws.sources:
            lay.addWidget(self.pane, 1)
        else:
            self.empty_label = QLabel("Nothing imported yet.")
            self.empty_label.setAlignment(Qt.AlignCenter)
            lay.addWidget(self.empty_label, 1)
        lay.addWidget(self.buttons)
        self.src_list.currentRowChanged.connect(self._update_solo)
        self._update_solo()

    def _update_solo(self, *_args) -> None:
        src = self.pane.current_source()
        self.solo_btn.setEnabled(src is not None and bool(self.pane.source_tracks(src.id)))

    def _solo(self) -> None:
        src = self.pane.current_source()
        if src is not None:
            self.ctl.solo_source_tracks(src.id)
        self.accept()
