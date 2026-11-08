"""Left track panel: one header per timeline lane, vertically locked to the timeline."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..core.document import Track
from . import theme
from .controller import Controller
from .timeline import HEADER_H, Timeline


class _Grip(QLabel):
    pressed = Signal(QPoint)
    moved = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__("⋮⋮", parent)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to reorder")
        self.setStyleSheet(f"color: {theme.TEXT_FAINT.name()};")
        self.setFixedWidth(12)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self.pressed.emit(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if e.buttons() & Qt.LeftButton:
            self.moved.emit(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self.setCursor(Qt.OpenHandCursor)
        self.released.emit(e.globalPosition().toPoint())


class TrackHeader(QFrame):
    contextMenuRequested = Signal(str, QPoint)

    def __init__(self, ctl: Controller, track_id: str, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.track_id = track_id
        self.setAutoFillBackground(False)

        self.grip = _Grip(self)
        self.color_btn = QToolButton(self)
        self.color_btn.setFixedSize(14, 14)
        self.color_btn.setToolTip("Track colour")
        self.color_btn.clicked.connect(self._pick_color)
        self.enabled_cb = QCheckBox(self)
        self.enabled_cb.setToolTip("Include in export")
        self.enabled_cb.toggled.connect(lambda on: ctl.set_track_enabled(track_id, on))
        self.name_edit = QLineEdit(self)
        self.name_edit.setFrame(False)
        self.name_edit.setAcceptDrops(False)
        self.name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.name_edit.setStyleSheet("QLineEdit { background: transparent; font-weight: 600; }"
                                     "QLineEdit:focus { background: #1b1c1f; }")
        self.name_edit.editingFinished.connect(self._commit_name)
        self.remove_btn = QToolButton(self)
        self.remove_btn.setText("✕")
        self.remove_btn.setAutoRaise(True)
        self.remove_btn.setToolTip("Remove track from workspace")
        self.remove_btn.clicked.connect(lambda: ctl.remove_track(track_id))
        self.info = QLabel(self)
        self.info.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        f = self.info.font()
        f.setPointSizeF(max(f.pointSizeF() - 2, 8))
        self.info.setFont(f)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.grip)
        row.addWidget(self.color_btn)
        row.addWidget(self.enabled_cb)
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.remove_btn)
        col = QVBoxLayout(self)
        col.setContentsMargins(6, 4, 4, 4)
        col.setSpacing(1)
        col.addLayout(row)
        col.addWidget(self.info)
        col.addStretch(1)

    def refresh(self, track: Track, source_desc: str, source_label: str) -> None:
        if not self.name_edit.hasFocus() and self.name_edit.text() != track.name:
            self.name_edit.setText(track.name)
            self.name_edit.setCursorPosition(0)
        self.enabled_cb.blockSignals(True)
        self.enabled_cb.setChecked(track.enabled)
        self.enabled_cb.blockSignals(False)
        self.color_btn.setStyleSheet(f"QToolButton {{ background: {track.color}; border: 1px solid #111;"
                                     f" border-radius: 3px; }}")
        chans = ",".join(str(c + 1) for c in track.channels)
        kind = "meta" if track.auxiliary else (f"ch {chans}" if chans else "")
        text = " · ".join(x for x in (source_label, kind) if x)
        self.info.setText(self.info.fontMetrics().elidedText(text, Qt.ElideMiddle, max(self.width() - 20, 40)))
        self.info.setToolTip(source_desc + (f"\nOriginal track name: {track.original_name}" if track.original_name else ""))
        self.name_edit.setEnabled(True)
        self.name_edit.setStyleSheet(
            "QLineEdit { background: transparent; font-weight: 600; color: %s; }"
            "QLineEdit:focus { background: #1b1c1f; }" % (theme.TEXT.name() if track.enabled else theme.TEXT_DIM.name()))

    def _commit_name(self) -> None:
        self.ctl.rename_track(self.track_id, self.name_edit.text())
        t = self.ctl.ws.track(self.track_id)
        if t:
            self.name_edit.setText(t.name)
        self.name_edit.clearFocus()

    def _pick_color(self) -> None:
        t = self.ctl.ws.track(self.track_id)
        if not t:
            return
        c = QColorDialog.getColor(QColor(t.color), self, "Track colour")
        if c.isValid():
            self.ctl.set_track_color(self.track_id, c.name())

    def contextMenuEvent(self, e) -> None:
        self.contextMenuRequested.emit(self.track_id, e.globalPos())

    def focus_name(self) -> None:
        self.name_edit.setFocus()
        self.name_edit.selectAll()


class TrackPanel(QWidget):
    trackContextMenuRequested = Signal(str, QPoint)

    def __init__(self, ctl: Controller, timeline: Timeline, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.timeline = timeline
        self.headers: dict[str, TrackHeader] = {}
        self._voffset = 0
        self._drag_tid: str | None = None
        self._drop_index: int | None = None
        self.setMinimumWidth(170)
        self.setAcceptDrops(False)

        self.title = QLabel("TRACKS", self)
        self.title.setStyleSheet(f"color: {theme.TEXT_DIM.name()}; font-weight: 600; letter-spacing: 1px;")

        ctl.tracksChanged.connect(self.rebuild)
        ctl.tempoChanged.connect(self.rebuild)
        timeline.verticalOffsetChanged.connect(self._set_offset)
        timeline.laneHeightChanged.connect(lambda _h: self._layout())

    def _set_offset(self, v: int) -> None:
        self._voffset = v
        self._layout()

    def rebuild(self) -> None:
        ws = self.ctl.ws
        live = {t.id for t in ws.tracks}
        for tid in list(self.headers):
            if tid not in live:
                self.headers.pop(tid).deleteLater()
        for t in ws.tracks:
            h = self.headers.get(t.id)
            if h is None:
                h = self.headers[t.id] = TrackHeader(self.ctl, t.id, self)
                h.contextMenuRequested.connect(self.trackContextMenuRequested)
                h.grip.pressed.connect(lambda gp, tid=t.id: self._grip_press(tid, gp))
                h.grip.moved.connect(self._grip_move)
                h.grip.released.connect(self._grip_release)
                h.show()
            src = ws.source(t.source_id)
            label = src.name if src else ""
            desc = src.describe() if src else ""
            if src and src.id == ws.tempo_source_id:
                desc += "\n(Workspace tempo map is taken from this source)"
            h.refresh(t, desc, label)
        self.title.setText(f"TRACKS  {len(ws.enabled_tracks())}/{len(ws.tracks)}" if ws.tracks else "TRACKS")
        self._layout()

    def _layout(self) -> None:
        lane_h = self.timeline.lane_h
        w = self.width()
        for i, t in enumerate(self.ctl.ws.tracks):
            h = self.headers.get(t.id)
            if h is None:
                continue
            y = HEADER_H + i * lane_h - self._voffset
            h.setGeometry(0, y, w, lane_h)
            h.setVisible(y + lane_h > HEADER_H and y < self.height())
        self.title.setGeometry(10, 0, w - 20, HEADER_H)
        self.title.raise_()
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._layout()
        self.rebuild()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, theme.PANEL_BG)
        for i, _t in enumerate(self.ctl.ws.tracks):
            y = HEADER_H + i * self.timeline.lane_h - self._voffset
            p.fillRect(0, y + self.timeline.lane_h - 1, w, 1, theme.LANE_SEP)
        p.fillRect(0, 0, w, HEADER_H, theme.RULER_BG)
        p.fillRect(0, HEADER_H - 1, w, 1, theme.LANE_SEP)
        p.fillRect(w - 1, 0, 1, h, theme.LANE_SEP)
        if self._drop_index is not None:
            y = HEADER_H + self._drop_index * self.timeline.lane_h - self._voffset
            p.setPen(QPen(theme.ACCENT, 2))
            p.drawLine(0, y, w, y)
        p.end()

    def paint_over_headers(self) -> None:
        self.update()

    def wheelEvent(self, e: QWheelEvent) -> None:
        self.timeline.wheelEvent(e)

    def header(self, track_id: str) -> TrackHeader | None:
        return self.headers.get(track_id)

    # -- drag to reorder --------------------------------------------------------
    def _index_at_global(self, gp: QPoint) -> int:
        y = self.mapFromGlobal(gp).y() + self._voffset - HEADER_H
        n = len(self.ctl.ws.tracks)
        return max(0, min(n, round(y / self.timeline.lane_h)))

    def _grip_press(self, tid: str, gp: QPoint) -> None:
        self._drag_tid = tid
        self._drop_index = None

    def _grip_move(self, gp: QPoint) -> None:
        if self._drag_tid is None:
            return
        self._drop_index = self._index_at_global(gp)
        self.update()
        # Draw indicator above child headers.
        self._indicator().setGeometry(QRect(0, HEADER_H + self._drop_index * self.timeline.lane_h
                                            - self._voffset - 1, self.width(), 2))
        self._indicator().show()
        self._indicator().raise_()

    def _grip_release(self, gp: QPoint) -> None:
        tid, idx = self._drag_tid, self._drop_index
        self._drag_tid = self._drop_index = None
        self._indicator().hide()
        if tid is None or idx is None:
            return
        cur = next((i for i, t in enumerate(self.ctl.ws.tracks) if t.id == tid), None)
        if cur is None:
            return
        target = idx - 1 if idx > cur else idx
        self.ctl.move_track(tid, target)

    def _indicator(self) -> QFrame:
        ind = getattr(self, "_ind", None)
        if ind is None:
            ind = self._ind = QFrame(self)
            ind.setStyleSheet(f"background: {theme.ACCENT.name()};")
            ind.hide()
        return ind
