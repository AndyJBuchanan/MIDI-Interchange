"""Bottom export panel: range editor, export mode, drag-out tile, save button."""
from __future__ import annotations

import sys

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..core.export_smf import ExportMode
from ..core.names import range_label
from ..interchange.drag_export import write_temp
from . import theme
from .controller import Controller

MODE_LABELS = [
    (ExportMode.WHOLE, "Whole workspace"),
    (ExportMode.PRESERVE, "Ranges · keep positions"),
    (ExportMode.REBASE, "Ranges · rebase & concatenate"),
    (ExportMode.SEPARATE, "Ranges · separate files"),
]


class DragTile(QFrame):
    """Drag source producing MIDI file(s) for the current export settings."""
    dragFailed = Signal(str)
    dragDone = Signal(list)

    def __init__(self, ctl: Controller, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self._press: QPoint | None = None
        self.setFixedSize(230, 46)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag into a DAW, Finder/Explorer or any app that accepts MIDI files")
        self.subtitle = ""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = bool(self.ctl.export_tracks())
        col = theme.ACCENT if enabled else theme.DISABLED
        fill = QColor(col)
        fill.setAlpha(40)
        p.setPen(col)
        p.setBrush(fill)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        f = self.font()
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.TEXT if enabled else theme.TEXT_DIM)
        p.drawText(self.rect().adjusted(10, 5, -8, -22), Qt.AlignLeft | Qt.AlignVCenter, "⇱  Drag MIDI out")
        f.setBold(False)
        f.setPointSizeF(max(f.pointSizeF() - 2, 8))
        p.setFont(f)
        p.setPen(theme.TEXT_DIM)
        p.drawText(self.rect().adjusted(10, 24, -8, -4), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.subtitle, Qt.ElideRight, self.width() - 20))
        p.end()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        start_file_drag(self, self.ctl, None, self.dragFailed.emit, self.dragDone.emit)

    def mouseReleaseEvent(self, _e) -> None:
        self._press = None


def start_file_drag(widget: QWidget, ctl: Controller, track_ids: list[str] | None,
                    on_error, on_done) -> None:
    try:
        results = ctl.build_exports(track_ids=track_ids)
    except Exception as exc:  # noqa: BLE001 - surface to the user, never crash the drag
        on_error(f"Export failed: {exc}")
        return
    if not results or not ctl.export_tracks(track_ids):
        on_error("Nothing to export (check the track and range toggles)")
        return
    paths = write_temp(results, ctl.default_export_name(track_ids))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    drag = QDrag(widget)
    drag.setMimeData(mime)
    pm = QPixmap(widget.size())
    pm.fill(Qt.transparent)
    widget.render(pm)
    drag.setPixmap(pm.scaledToWidth(min(pm.width(), 160), Qt.SmoothTransformation))
    drag.setHotSpot(QPoint(12, 12))
    drag.exec(Qt.CopyAction)
    on_done(paths)


class ExportPanel(QFrame):
    saveRequested = Signal()
    message = Signal(str)

    def __init__(self, ctl: Controller, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.setObjectName("ExportPanel")
        self.setStyleSheet("#ExportPanel { background: #26282c; border-top: 1px solid #121315; }")

        # Range editor row
        self.range_combo = QComboBox()
        self.range_combo.setMinimumWidth(150)
        self.range_combo.currentIndexChanged.connect(self._range_chosen)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Range name")
        self.name_edit.setAcceptDrops(False)
        self.name_edit.setMaximumWidth(180)
        self.name_edit.editingFinished.connect(self._commit_name)
        self.start_edit = QLineEdit()
        self.end_edit = QLineEdit()
        for ed, tip in ((self.start_edit, "Start (bar.beat.tick, 480 ticks/quarter)"),
                        (self.end_edit, "End, exclusive (bar.beat.tick)")):
            ed.setMaximumWidth(92)
            ed.setAcceptDrops(False)
            ed.setToolTip(tip)
            ed.editingFinished.connect(self._commit_positions)
        self.length_label = QLabel()
        self.length_label.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        self.delete_btn = QToolButton()
        self.delete_btn.setText("Delete")
        self.delete_btn.clicked.connect(lambda: ctl.delete_range())
        self.hint = QLabel("Drag across the timeline to mark a range · Shift bypasses snap · "
                           + ("⌥-" if sys.platform == "darwin" else "Alt+") + "drag moves clips")
        self.hint.setStyleSheet(f"color: {theme.TEXT_FAINT.name()};")

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(QLabel("Range"))
        r1.addWidget(self.range_combo)
        r1.addWidget(self.name_edit)
        r1.addWidget(QLabel("Start"))
        r1.addWidget(self.start_edit)
        r1.addWidget(QLabel("End"))
        r1.addWidget(self.end_edit)
        r1.addWidget(self.length_label)
        r1.addWidget(self.delete_btn)
        r1.addStretch(1)
        r1.addWidget(self.hint)

        # Export row
        self.mode_combo = QComboBox()
        for mode, label in MODE_LABELS:
            self.mode_combo.addItem(label, mode)
        self.mode_combo.currentIndexChanged.connect(
            lambda i: ctl.set_export_mode(self.mode_combo.itemData(i)))
        self.trim_cb = QCheckBox("Trim leading/trailing silence")
        self.trim_cb.setToolTip("Trims the assembled output as a whole; track alignment is kept")
        self.trim_cb.toggled.connect(ctl.set_trim)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        self.drag_tile = DragTile(ctl)
        self.drag_tile.dragFailed.connect(self.message)
        self.drag_tile.dragDone.connect(lambda paths: self.message.emit(f"Dragged {len(paths)} file(s)"))
        self.save_btn = QPushButton("Save MIDI…")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.saveRequested)

        r2 = QHBoxLayout()
        r2.setSpacing(10)
        r2.addWidget(QLabel("Export"))
        r2.addWidget(self.mode_combo)
        r2.addWidget(self.trim_cb)
        r2.addWidget(self.summary, 1)
        r2.addWidget(self.drag_tile)
        r2.addWidget(self.save_btn)

        col = QVBoxLayout(self)
        col.setContentsMargins(10, 6, 10, 8)
        col.setSpacing(6)
        col.addLayout(r1)
        col.addLayout(r2)

        ctl.rangesChanged.connect(self.refresh)
        ctl.selectionChanged.connect(self.refresh)
        ctl.tracksChanged.connect(self.refresh)
        ctl.tempoChanged.connect(self.refresh)
        ctl.exportSettingsChanged.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        ws = self.ctl.ws
        tm = ws.tempo_map
        self.range_combo.blockSignals(True)
        self.range_combo.clear()
        if not ws.ranges:
            self.range_combo.addItem("No ranges", None)
        for i, r in enumerate(ws.ranges):
            self.range_combo.addItem(range_label(r.name, i), r.id)
        sel = self.ctl.selected_range
        idx = next((i for i, r in enumerate(ws.ranges) if sel and r.id == sel.id), -1)
        if idx < 0 and ws.ranges:
            self.range_combo.insertItem(0, "— select —", None)
            self.range_combo.setCurrentIndex(0)
        else:
            self.range_combo.setCurrentIndex(max(idx, 0))
        self.range_combo.blockSignals(False)
        self.range_combo.setEnabled(bool(ws.ranges))

        has = sel is not None
        for w in (self.name_edit, self.start_edit, self.end_edit, self.delete_btn):
            w.setEnabled(has)
        if has:
            if not self.name_edit.hasFocus():
                self.name_edit.setText(sel.name)
            if not self.start_edit.hasFocus():
                self.start_edit.setText(tm.format_bbt(sel.start))
            if not self.end_edit.hasFocus():
                self.end_edit.setText(tm.format_bbt(sel.end))
            bars = sel.length / tm.timesig_at(sel.start).bar_length
            n_in = sum(1 for t in ws.tracks if sel.includes(t.id))
            self.length_label.setText(f"{float(sel.length):g} beats ({float(bars):.4g} bars) · "
                                      f"{n_in} of {len(ws.tracks)} tracks")
        else:
            for ed in (self.name_edit, self.start_edit, self.end_edit):
                ed.clear()
            self.length_label.clear()
        self.hint.setVisible(not ws.ranges)

        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex([m for m, _ in MODE_LABELS].index(self.ctl.export_mode))
        self.mode_combo.blockSignals(False)
        self.trim_cb.blockSignals(True)
        self.trim_cb.setChecked(self.ctl.trim)
        self.trim_cb.blockSignals(False)

        n_en, n = len(self.ctl.export_tracks()), len(ws.tracks)
        mode = self.ctl.export_mode if ws.ranges else ExportMode.WHOLE
        if mode is ExportMode.WHOLE:
            what = "whole workspace"
        elif mode is ExportMode.SEPARATE:
            what = f"{len(ws.ranges)} file(s), one per range"
        else:
            what = f"{len(ws.ranges)} range(s), {'kept in place' if mode is ExportMode.PRESERVE else 'concatenated'}"
        self.summary.setText(f"{n_en} of {n} tracks · {what}" if n else "No tracks")
        self.drag_tile.subtitle = f"{n_en} track{'s' if n_en != 1 else ''} · {what}"
        self.drag_tile.update()
        self.save_btn.setEnabled(n_en > 0)

    def _range_chosen(self, i: int) -> None:
        rid = self.range_combo.itemData(i)
        self.ctl.select_range(rid)

    def _commit_name(self) -> None:
        sel = self.ctl.selected_range
        if sel and self.name_edit.text() != sel.name:
            self.ctl.checkpoint()
            self.ctl.update_range(sel.id, name=self.name_edit.text().strip())

    def _commit_positions(self) -> None:
        sel = self.ctl.selected_range
        if not sel:
            return
        tm = self.ctl.ws.tempo_map
        try:
            start = tm.parse_bbt(self.start_edit.text())
            end = tm.parse_bbt(self.end_edit.text())
        except ValueError as exc:
            self.message.emit(str(exc))
            self.refresh()
            return
        if (start, end) != (sel.start, sel.end) and end != start:
            self.ctl.checkpoint()
            self.ctl.update_range(sel.id, start=start, end=end)
        else:
            self.refresh()

    def focus_range_name(self) -> None:
        self.name_edit.setFocus()
        self.name_edit.selectAll()
