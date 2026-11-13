"""Left track panel: one header per timeline lane, vertically locked to the timeline."""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QWidgetAction,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..core.document import TRACK_COLORS, Track
from . import theme
from .controller import Controller
from .timeline import HEADER_H, Timeline


CONTROL_SIZE = 22
CONTROL_GAP = 4


def channel_text_color(color: QColor) -> str:
    """Choose whichever of black/white has the higher WCAG contrast ratio."""
    def linear(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    luminance = sum(w * linear(v) for w, v in zip(
        (0.2126, 0.7152, 0.0722), (color.redF(), color.greenF(), color.blueF())))
    return "#000000" if luminance > 0.179 else "#ffffff"


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
        self.color_btn.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.color_btn.setToolTip("Track colour")
        self.color_btn.clicked.connect(self._show_color_menu)
        self.mute_btn = QToolButton(self)
        self.solo_btn = QToolButton(self)
        for button, label, tip in ((self.mute_btn, "M", "Mute; Alt/Option-click: set all mutes"),
                                   (self.solo_btn, "S", "Solo; Alt/Option-click: exclusive solo")):
            button.setText(label)
            button.setCheckable(True)
            button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
            button.setToolTip(tip)
        self.mute_btn.clicked.connect(self._mute_clicked)
        self.solo_btn.clicked.connect(lambda: ctl.toggle_solo(track_id,
            bool(QGuiApplication.keyboardModifiers() & Qt.AltModifier)))
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
        row.setSpacing(CONTROL_GAP)
        row.addWidget(self.grip)
        row.addWidget(self.color_btn)
        ms = QHBoxLayout()
        ms.setContentsMargins(0, 0, 0, 0)
        ms.setSpacing(0)
        ms.addWidget(self.mute_btn)
        ms.addWidget(self.solo_btn)
        row.addLayout(ms)
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
        self.mute_btn.setChecked(track.muted)
        self.solo_btn.setChecked(track.soloed)
        self.mute_btn.setStyleSheet(
            f"QToolButton:checked {{ background: {(theme.DISABLED if track.soloed else theme.ACCENT).name()}; }}")
        self.solo_btn.setStyleSheet(f"QToolButton:checked {{ background: {theme.SOLO.name()}; }}")
        self.color_btn.setText("" if track.export_channel is None else str(track.export_channel))
        channel_label = "Original channels" if track.export_channel is None else f"Export MIDI channel {track.export_channel}"
        self.color_btn.setToolTip(f"Track colour / export MIDI channel\n{channel_label}")
        foreground = channel_text_color(QColor(track.color))
        self.color_btn.setStyleSheet(f"QToolButton {{ color: {foreground}; background: {track.color}; border: 1px solid #111;"
                                     f" border-radius: 3px; }}")
        chans = ",".join(str(c + 1) for c in track.channels)
        kind = "meta" if track.auxiliary else (f"ch {chans}" if chans else "")
        text = " · ".join(x for x in (source_label, kind) if x)
        self.info.setText(self.info.fontMetrics().elidedText(text, Qt.ElideMiddle, max(self.width() - 20, 40)))
        self.info.setToolTip(source_desc + (f"\nOriginal track name: {track.original_name}" if track.original_name else ""))
        self.name_edit.setEnabled(True)
        self.name_edit.setStyleSheet(
            "QLineEdit { background: transparent; font-weight: 600; color: %s; }"
            "QLineEdit:focus { background: #1b1c1f; }" % (theme.TEXT.name() if track in self.ctl.ws.global_tracks() else theme.TEXT_DIM.name()))

    def _mute_clicked(self) -> None:
        track = self.ctl.ws.track(self.track_id)
        if track:
            self.ctl.set_mute(track.id, True if track.soloed else not track.muted,
                             bool(QGuiApplication.keyboardModifiers() & Qt.AltModifier))

    def _commit_name(self) -> None:
        self.ctl.rename_track(self.track_id, self.name_edit.text())
        t = self.ctl.ws.track(self.track_id)
        if t:
            self.name_edit.setText(t.name)
        self.name_edit.clearFocus()

    def _build_color_menu(self) -> QMenu:
        menu = QMenu(self)
        track = self.ctl.ws.track(self.track_id)
        if track is None:
            return menu
        palette = QWidget(menu)
        grid = QGridLayout(palette)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(CONTROL_GAP)
        for i, color in enumerate([*TRACK_COLORS, "#ffffff", "#000000"]):
            button = QToolButton(palette)
            button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
            button.setToolTip(color)
            button.setStyleSheet(f"background: {color}; border: 1px solid {theme.TEXT_DIM.name()};")
            button.clicked.connect(lambda _checked=False, value=color: self._choose_color(menu, value))
            grid.addWidget(button, i // 6, i % 6)
        action = QWidgetAction(menu)
        action.setDefaultWidget(palette)
        menu.addAction(action)
        menu.addAction("More colours…", self._pick_color)
        menu.addSeparator()
        channels = menu.addMenu("Export MIDI channel")
        for channel in [None, *range(1, 17)]:
            action = channels.addAction("Original channels" if channel is None else str(channel))
            action.setCheckable(True)
            action.setChecked(track.export_channel == channel)
            action.triggered.connect(lambda _checked=False, value=channel:
                                     self.ctl.set_export_channel(self.track_id, value))
        return menu

    def _choose_color(self, menu: QMenu, color: str) -> None:
        menu.close()
        self.ctl.set_track_color(self.track_id, color)

    def _show_color_menu(self) -> None:
        previous = getattr(self, "_color_menu", None)
        if previous is not None:
            previous.deleteLater()
        self._color_menu = self._build_color_menu()
        self._color_menu.popup(self.color_btn.mapToGlobal(QPoint(0, self.color_btn.height())))

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

        # headers live in a container below the title band, which clips them
        self.lanes = QWidget(self)

        self.title = QLabel("TRACKS", self)
        self.title.setStyleSheet(f"color: {theme.TEXT_DIM.name()}; font-weight: 600; letter-spacing: 1px;")

        self.clear_m = QToolButton(self)
        self.clear_s = QToolButton(self)
        for button, label, slot, tip in ((self.clear_m, "M", ctl.clear_mutes, "Clear all mutes"),
                                         (self.clear_s, "S", ctl.clear_solos, "Clear all solos")):
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            color = theme.SOLO if label == "S" else theme.ACCENT
            button.setStyleSheet(f"QToolButton:checked {{ background: {color.name()}; }}")
            button.clicked.connect(slot)
            button.clicked.connect(self.rebuild)
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
                h = self.headers[t.id] = TrackHeader(self.ctl, t.id, self.lanes)
                h.contextMenuRequested.connect(self.trackContextMenuRequested)
                h.grip.pressed.connect(lambda gp, tid=t.id: self._grip_press(tid, gp))
                h.grip.moved.connect(self._grip_move)
                h.grip.released.connect(self._grip_release)
                h.show()
            srcs = [x for x in (ws.source(sid) for sid in t.source_ids()) if x]
            src = srcs[0] if srcs else None
            label = (src.name if len(srcs) == 1 else f"{len(t.clips)} clips · {len(srcs)} sources") if src else ""
            desc = "\n\n".join(x.describe() for x in srcs)
            if any(x.id == ws.tempo_source_id for x in srcs):
                desc += "\n(Workspace tempo map is taken from this source)"
            h.refresh(t, desc, label)
        self.title.setText(f"TRACKS  {len(ws.global_tracks())}/{len(ws.tracks)}" if ws.tracks else "TRACKS")
        self.clear_m.setChecked(any(t.muted and not t.soloed for t in ws.tracks))
        self.clear_s.setChecked(any(t.soloed for t in ws.tracks))
        self._layout()

    def _layout(self) -> None:
        lane_h = self.timeline.lane_h
        w = self.width()
        self.lanes.setGeometry(0, HEADER_H, w, max(self.height() - HEADER_H, 0))
        for i, t in enumerate(self.ctl.ws.tracks):
            h = self.headers.get(t.id)
            if h is None:
                continue
            y = i * lane_h - self._voffset
            h.setGeometry(0, y, w, lane_h)
            h.setVisible(y + lane_h > 0 and y < self.lanes.height())
        self.title.setGeometry(10, 0, w - 70, HEADER_H)
        self.clear_m.setGeometry(w - 2 * CONTROL_SIZE - CONTROL_GAP, 16, CONTROL_SIZE, CONTROL_SIZE)
        self.clear_s.setGeometry(w - CONTROL_SIZE - CONTROL_GAP, 16, CONTROL_SIZE, CONTROL_SIZE)
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
        self._indicator().setGeometry(QRect(0, self._drop_index * self.timeline.lane_h
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
            ind = self._ind = QFrame(self.lanes)
            ind.setStyleSheet(f"background: {theme.ACCENT.name()};")
            ind.hide()
        return ind
