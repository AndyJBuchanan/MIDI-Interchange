"""Custom-painted multitrack timeline.

Everything is drawn in a single viewport paint pass: ruler, info row
(tempo/time-signature/markers), range strip, lanes, clips, notes, lyric
indicators and range overlays. Notes are drawn from a per-clip render cache
(float arrays sorted by start) with bisect-based culling, so cost scales with
what is visible, not with file size.

Interaction
  drag on empty space (ruler or lanes)     create a range
  drag a range edge (any row)              resize
  drag a range body in the range strip     move
  Alt/Option-drag a clip                   move the clip, in time and across tracks
                                           (below the last track: onto a new track)
  Alt+Ctrl / Option-Cmd-drag a clip        copy the clip
  Shift while dragging a clip              keep its time; change track only
  Shift while dragging a range             bypass snap
  Cmd/Ctrl + wheel, pinch                  zoom around the cursor
  wheel / trackpad                         scroll (Shift+wheel = horizontal)
  Delete / Backspace                       delete selected range
  double-click a range in the strip        edit its name/position
  click a range's track toggle             include/exclude that track in that range
                                           (the toggle sits at the range's inner left
                                           edge in each lane; right-click a range for
                                           the same choices when it is too narrow)
"""
from __future__ import annotations

import bisect
import math
import sys
from dataclasses import dataclass
from fractions import Fraction

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
                           QNativeGestureEvent, QPainter, QPainterPath, QPen, QWheelEvent)
from PySide6.QtWidgets import QAbstractScrollArea, QMenu

from ..core.document import Clip, Track
from ..core.events import TEXT_META, display_text, pair_notes
from ..core.timing import ZERO, quantize
from .controller import Controller
from . import theme

RULER_H = 22
INFO_H = 16
RANGE_H = 20
HEADER_H = RULER_H + INFO_H + RANGE_H
RANGE_TOP = RULER_H + INFO_H
EDGE_PX = 5
TOGGLE_PX = 13        # range track toggle: size, and gap from the range's left edge
TOGGLE_GAP = 6
MIN_PPB, MAX_PPB = 1.5, 1600.0


@dataclass
class ClipRender:
    starts: list[float]
    notes: list[tuple[float, float, int, int]]  # start, end, pitch, velocity
    max_len: float
    pmin: int
    pmax: int
    texts: list[tuple[float, str, str]]          # time, meta type, text


def build_render(clip: Clip) -> ClipRender:
    notes, _ = pair_notes(clip.events, clip.length)
    rows = [(float(n.start), float(n.end), n.pitch, n.velocity) for n in notes]
    texts = [(float(e.time), e.msg.type, display_text(e.msg))
             for e in clip.events if e.msg.type in TEXT_META]
    pitches = [r[2] for r in rows]
    return ClipRender(
        starts=[r[0] for r in rows], notes=rows,
        max_len=max((r[1] - r[0] for r in rows), default=0.0),
        pmin=min(pitches, default=60), pmax=max(pitches, default=60), texts=texts)


def note_rows(area_top: float, area_h: float, pmin: int, pmax: int) -> tuple[float, float, float]:
    """Vertical layout of a lane's notes: (y of row pmax, row pitch, drawn note height).

    Note y = y_base + (pmax - pitch) * row. Rows always fit inside the area (a wide
    pitch range compresses rather than overflowing the lane); each note is still
    drawn at least 1.2 px tall so it stays visible.
    """
    span = pmax - pmin + 1
    row = min(area_h / span, 7.0)
    y_base = area_top + (area_h - row * span) / 2
    return y_base, row, max(row - (1 if row >= 4 else 0), 1.2)


class Timeline(QAbstractScrollArea):
    verticalOffsetChanged = Signal(int)
    laneHeightChanged = Signal(int)
    hoverTextChanged = Signal(str)
    trackContextMenuRequested = Signal(str, QPoint)
    clipContextMenuRequested = Signal(str, str, QPoint)   # track id, clip id
    rangeEditRequested = Signal(str)

    def __init__(self, ctl: Controller, parent=None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.ppb = 28.0          # pixels per quarter note
        self.lane_h = 68
        self._cache: dict[str, ClipRender] = {}
        self._drag: dict | None = None
        self._hover_x: float | None = None
        self._press_pos: QPointF | None = None
        self._drop_ind: tuple[int | None, Fraction, str] | None = None   # lane (None = new track), time, label

        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self.verticalScrollBar().valueChanged.connect(self._on_vscroll)

        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(30)
        self._autoscroll.timeout.connect(self._autoscroll_tick)

        self.font_small = QFont(self.font())
        self.font_small.setPointSizeF(max(self.font().pointSizeF() - 2.5, 8.0))
        self.font_ruler = QFont(self.font())
        self.font_ruler.setPointSizeF(max(self.font().pointSizeF() - 1.5, 9.0))

        ctl.tracksChanged.connect(self._content_changed)
        ctl.rangesChanged.connect(self._content_changed)
        ctl.selectionChanged.connect(self.viewport().update)
        ctl.tempoChanged.connect(self._content_changed)

    # ------------------------------------------------------------------ geometry
    def x_of(self, t: float) -> float:
        return t * self.ppb - self.horizontalScrollBar().value()

    def t_of(self, x: float) -> float:
        return (x + self.horizontalScrollBar().value()) / self.ppb

    def time_at(self, x: float, bypass_snap: bool = False) -> Fraction:
        return self.ctl.snap_time(quantize(max(self.t_of(x), 0.0)), bypass_snap)

    def lane_top(self, i: int) -> int:
        return HEADER_H + i * self.lane_h - self.verticalScrollBar().value()

    def lane_at(self, y: float) -> int:
        if y < HEADER_H:
            return -1
        i = int((y - HEADER_H + self.verticalScrollBar().value()) // self.lane_h)
        return i if 0 <= i < len(self.ctl.ws.tracks) else -1

    def total_beats(self) -> float:
        ws = self.ctl.ws
        end = float(ws.end)
        for r in ws.ranges:
            end = max(end, float(r.end))
        return max(end + 32.0, 128.0)

    def _update_scrollbars(self) -> None:
        vw, vh = self.viewport().width(), self.viewport().height()
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        content_w = int(self.total_beats() * self.ppb)
        hbar.setRange(0, max(0, content_w - vw))
        hbar.setPageStep(vw)
        hbar.setSingleStep(max(int(self.ppb), 8))
        content_h = HEADER_H + len(self.ctl.ws.tracks) * self.lane_h + 24
        vbar.setRange(0, max(0, content_h - vh))
        vbar.setPageStep(max(vh - HEADER_H, 1))
        vbar.setSingleStep(self.lane_h // 3)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_scrollbars()

    def _on_vscroll(self, v: int) -> None:
        self.verticalOffsetChanged.emit(v)
        self.viewport().update()

    def _content_changed(self) -> None:
        live = {c.id for t in self.ctl.ws.tracks for c in t.clips}
        for cid in list(self._cache):
            if cid not in live:
                del self._cache[cid]
        self._update_scrollbars()
        self.viewport().update()

    def render_for(self, clip: Clip) -> ClipRender:
        r = self._cache.get(clip.id)
        if r is None:
            r = self._cache[clip.id] = build_render(clip)
        return r

    # ------------------------------------------------------------------ zoom
    def set_zoom(self, ppb: float, anchor_x: float | None = None) -> None:
        ppb = min(max(ppb, MIN_PPB), MAX_PPB)
        if anchor_x is None:
            anchor_x = self.viewport().width() / 2
        t_anchor = self.t_of(anchor_x)
        self.ppb = ppb
        self._update_scrollbars()
        self.horizontalScrollBar().setValue(int(round(t_anchor * ppb - anchor_x)))
        self.viewport().update()

    def zoom_by(self, factor: float, anchor_x: float | None = None) -> None:
        self.set_zoom(self.ppb * factor, anchor_x)

    def zoom_to_fit(self) -> None:
        ws = self.ctl.ws
        end = max(float(ws.end), *(float(r.end) for r in ws.ranges), 16.0) if ws.ranges else max(float(ws.end), 16.0)
        avail = max(self.viewport().width() - 40, 100)
        self.ppb = min(max(avail / end, MIN_PPB), MAX_PPB)
        self._update_scrollbars()
        self.horizontalScrollBar().setValue(0)
        self.viewport().update()

    def set_lane_height(self, h: int) -> None:
        h = min(max(h, 28), 220)
        if h != self.lane_h:
            self.lane_h = h
            self._update_scrollbars()
            self.laneHeightChanged.emit(h)
            self.viewport().update()

    def scroll_to_time(self, t: float) -> None:
        x = self.x_of(t)
        if x < 40 or x > self.viewport().width() - 40:
            self.horizontalScrollBar().setValue(int(t * self.ppb - self.viewport().width() / 3))

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _e) -> None:
        p = QPainter(self.viewport())
        w, h = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, w, h, theme.BG)
        ws = self.ctl.ws
        t0, t1 = max(self.t_of(0), 0.0), self.t_of(w)

        p.setClipRect(0, HEADER_H, w, h - HEADER_H)
        self._paint_lanes_bg(p, w)
        self._paint_grid(p, t0, t1, HEADER_H, h)
        for i, track in enumerate(ws.tracks):
            top = self.lane_top(i)
            if top + self.lane_h < HEADER_H or top > h:
                continue
            self._paint_track(p, track, top, t0, t1, w)
        self._paint_range_overlays(p, HEADER_H, h)
        if self._drop_ind is not None:
            self._paint_drop_indicator(p, w, h)
        p.setClipping(False)

        self._paint_header(p, w, t0, t1)
        if not ws.tracks:
            p.setPen(theme.TEXT_DIM)
            f = QFont(self.font())
            f.setPointSizeF(self.font().pointSizeF() + 3)
            p.setFont(f)
            p.drawText(QRectF(0, HEADER_H, w, h - HEADER_H), Qt.AlignCenter,
                       "Drop MIDI files or clips here\nor use File ▸ Open ("
                       + ("⌘O" if sys.platform == "darwin" else "Ctrl+O") + ")")
        p.end()

    def _paint_lanes_bg(self, p: QPainter, w: int) -> None:
        for i, track in enumerate(self.ctl.ws.tracks):
            top = self.lane_top(i)
            p.fillRect(0, top, w, self.lane_h, theme.LANE_A if i % 2 == 0 else theme.LANE_B)
            p.fillRect(0, top + self.lane_h - 1, w, 1, theme.LANE_SEP)

    def _grid_levels(self) -> tuple[int, Fraction | None]:
        """(bar label stride, subdivision step in quarters or None)."""
        bar_px = 4 * self.ppb
        stride = 1
        while bar_px * stride < 44:
            stride *= 2
        sub = None
        for step in (Fraction(1, 8), Fraction(1, 4), Fraction(1, 2)):
            if self.ppb * step >= 14:
                sub = step
                break
        return stride, sub

    def _paint_grid(self, p: QPainter, t0: float, t1: float, y0: int, y1: int) -> None:
        tm = self.ctl.ws.tempo_map
        stride, sub = self._grid_levels()
        start = Fraction(math.floor(t0)) - 8
        for idx, bs, be, ts in tm.bars(max(start, ZERO), Fraction(math.ceil(t1)) + 1):
            x = round(self.x_of(float(bs))) + 0.5
            strong = idx % stride == 0
            if strong or self.ppb * float(ts.bar_length) >= 6:
                p.setPen(QPen(theme.GRID_BAR if strong else theme.GRID_BEAT, 1))
                p.drawLine(QPointF(x, y0), QPointF(x, y1))
            beat_px = self.ppb * float(ts.beat_length)
            if beat_px >= 7:
                p.setPen(QPen(theme.GRID_BEAT, 1))
                b = bs + ts.beat_length
                while b < be:
                    xb = round(self.x_of(float(b))) + 0.5
                    p.drawLine(QPointF(xb, y0), QPointF(xb, y1))
                    b += ts.beat_length
            if sub is not None and sub < ts.beat_length:
                p.setPen(QPen(theme.GRID_SUB, 1))
                s = bs + sub
                while s < be:
                    if (s - bs) % ts.beat_length != 0:
                        xs = round(self.x_of(float(s))) + 0.5
                        p.drawLine(QPointF(xs, y0), QPointF(xs, y1))
                    s += sub

    def _paint_track(self, p: QPainter, track: Track, top: int, t0: float, t1: float, w: int) -> None:
        base = QColor(track.color)
        if not track.enabled:
            base = QColor(theme.DISABLED)
        lane_h = self.lane_h
        name_h = 13 if lane_h >= 44 else 0
        pmin = min((self.render_for(c).pmin for c in track.clips), default=60)
        pmax = max((self.render_for(c).pmax for c in track.clips), default=60)
        pmin, pmax = pmin - 1, pmax + 1
        area_top = top + 3 + name_h
        area_h = lane_h - 7 - name_h - (8 if track.auxiliary or lane_h < 44 else 4)
        y_base, note_h, draw_h = note_rows(area_top, area_h, pmin, pmax)

        for clip in track.clips:
            x0, x1 = self.x_of(float(clip.start)), self.x_of(float(clip.end))
            if x1 < -2 or x0 > w + 2:
                continue
            cr = QRectF(x0, top + 2, max(x1 - x0, 3), lane_h - 5)
            fill = QColor(base)
            fill.setAlpha(46 if track.enabled else 28)
            border = QColor(base)
            border.setAlpha(150 if track.enabled else 70)
            p.setPen(QPen(border, 1))
            p.setBrush(fill)
            p.drawRoundedRect(cr, 3, 3)
            if name_h and cr.width() > 30:
                p.setFont(self.font_small)
                p.setPen(theme.TEXT if track.enabled else theme.TEXT_DIM)
                lx = max(cr.left(), 0) + 5
                fm = QFontMetrics(self.font_small)
                label = fm.elidedText(clip.name or track.name, Qt.ElideRight, int(cr.right() - lx - 4))
                p.drawText(QPointF(lx, top + 2 + fm.ascent() + 1), label)

            render = self.render_for(clip)
            off = float(clip.offset)
            p.save()
            p.setClipRect(cr.adjusted(1, 1, -1, -1))          # notes never paint outside their clip
            note_col = base.lighter(135) if track.enabled else base
            p.setPen(Qt.NoPen)
            a, b = t0 - off, t1 - off
            i = bisect.bisect_left(render.starts, a - render.max_len)
            notes = render.notes
            n = len(notes)
            ppb = self.ppb
            scroll = self.horizontalScrollBar().value()
            while i < n:
                s, e, pitch, vel = notes[i]
                if s > b:
                    break
                i += 1
                if e < a:
                    continue
                nx = (s + off) * ppb - scroll
                nw = max((e - s) * ppb - (1 if ppb > 30 else 0), 1.5)
                ny = y_base + (pmax - pitch) * note_h
                c = QColor(note_col)
                c.setAlpha(int(140 + vel * 115 / 127) if track.enabled else 110)
                p.fillRect(QRectF(nx, ny, nw, draw_h), c)
            p.restore()

            if render.texts:
                self._paint_texts(p, render, off, top, lane_h, t0, t1, base, track.enabled)

        if len(track.clips) > 1:
            for lo, hi in track.overlaps():
                x0, x1 = self.x_of(float(lo)), self.x_of(float(hi))
                if x1 < 0 or x0 > w:
                    continue
                p.fillRect(QRectF(x0, top + 2, max(x1 - x0, 2), lane_h - 5), theme.OVERLAP_FILL)
                p.fillRect(QRectF(x0, top + 2, max(x1 - x0, 2), 2), theme.OVERLAP_EDGE)

    def _paint_drop_indicator(self, p: QPainter, w: int, h: int) -> None:
        lane, t, label = self._drop_ind
        x = round(self.x_of(float(t))) + 0.5
        n = len(self.ctl.ws.tracks)
        if lane is None:
            top = self.lane_top(n)
            box = QRectF(max(x, 0), top + 2, max(w - x, 0), self.lane_h - 5)
            p.setPen(QPen(theme.ACCENT, 1, Qt.DashLine))
            p.setBrush(theme.DROP_NEW_FILL)
            p.drawRect(box)
            y0, y1 = top, top + self.lane_h
        else:
            top = self.lane_top(lane)
            p.fillRect(QRectF(0, top, w, self.lane_h), theme.DROP_LANE_FILL)
            y0, y1 = top, top + self.lane_h
        p.setPen(QPen(theme.ACCENT, 2))
        p.drawLine(QPointF(x, y0), QPointF(x, y1))
        p.setFont(self.font_small)
        fm = QFontMetrics(self.font_small)
        tw = fm.horizontalAdvance(label) + 10
        lx = min(max(x + 4, 2), w - tw - 2)
        ly = max(y0 + 2, HEADER_H + 2)
        p.fillRect(QRectF(lx, ly, tw, fm.height() + 4), theme.DROP_LABEL_BG)
        p.setPen(theme.ACCENT)
        p.drawText(QPointF(lx + 5, ly + 2 + fm.ascent()), label)

    # ------------------------------------------------------------------ drop targeting
    def drop_target(self, pos: QPointF, bypass_snap: bool = False) -> tuple[int | None, Fraction]:
        """(lane index or None for 'new tracks', snapped time) for a point in the viewport."""
        t = self.time_at(pos.x(), bypass_snap)
        return (self.lane_at(pos.y()) if pos.y() >= HEADER_H else -1), t

    def set_drop_indicator(self, ind: tuple[int | None, Fraction, str] | None) -> None:
        if ind != self._drop_ind:
            self._drop_ind = ind
            self.viewport().update()

    def _paint_texts(self, p, render: ClipRender, off: float, top: int, lane_h: int,
                     t0: float, t1: float, base: QColor, enabled: bool) -> None:
        fm = QFontMetrics(self.font_small)
        p.setFont(self.font_small)
        y = top + lane_h - 4
        texts = render.texts
        tick_col = QColor(theme.LYRIC if enabled else theme.TEXT_DIM)
        for k, (t, kind, text) in enumerate(texts):
            ta = t + off
            if ta < t0 - 50 / self.ppb or ta > t1:
                continue
            x = self.x_of(ta)
            p.setPen(QPen(tick_col, 1))
            p.drawLine(QPointF(x + 0.5, y - 5), QPointF(x + 0.5, y))
            nxt = next((texts[j][0] + off for j in range(k + 1, len(texts))), None)
            room = (self.x_of(nxt) - x - 4) if nxt is not None else 200
            if room > 14 and lane_h >= 40:
                label = fm.elidedText(text.strip(), Qt.ElideRight, int(min(room, 200)))
                p.drawText(QPointF(x + 3, y - 1), label)

    def _paint_range_overlays(self, p: QPainter, y0: int, y1: int) -> None:
        sel = self.ctl.selected_range_id
        for r in self.ctl.ws.ranges:
            x0, x1 = self.x_of(float(r.start)), self.x_of(float(r.end))
            if x1 < 0 or x0 > self.viewport().width():
                continue
            selected = r.id == sel
            p.fillRect(QRectF(x0, y0, x1 - x0, y1 - y0), theme.RANGE_FILL_SEL if selected else theme.RANGE_FILL)
            p.setPen(QPen(theme.ACCENT if selected else theme.RANGE_EDGE, 1))
            p.drawLine(QPointF(round(x0) + 0.5, y0), QPointF(round(x0) + 0.5, y1))
            p.drawLine(QPointF(round(x1) - 0.5, y0), QPointF(round(x1) - 0.5, y1))
        # per-range track toggles; the selected range is drawn last (on top)
        for r in sorted(self.ctl.ws.ranges, key=lambda r: r.id == sel):
            self._paint_range_toggles(p, r, r.id == sel, y0, y1)

    def _paint_range_toggles(self, p: QPainter, r, selected: bool, y0: int, y1: int) -> None:
        x0, x1 = self.x_of(float(r.start)), self.x_of(float(r.end))
        if x1 < 0 or x0 > self.viewport().width():
            return
        hatch = QBrush(theme.EXCLUDED_HATCH, Qt.BDiagPattern)
        accent = QColor(theme.ACCENT if selected else theme.RANGE_TOGGLE)
        for i, track in enumerate(self.ctl.ws.tracks):
            top = self.lane_top(i)
            if top + self.lane_h < y0 or top > y1:
                continue
            on = r.includes(track.id)
            if not on:
                lane = QRectF(round(x0) + 1, top, max(round(x1) - round(x0) - 2, 0), self.lane_h - 1)
                p.fillRect(lane, theme.EXCLUDED_FILL)
                p.fillRect(lane, hatch)
            tr = self.toggle_rect(r, i)
            if tr is None:
                continue
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(accent, 1.5))
            p.setBrush(accent if on else theme.BG)
            p.drawRoundedRect(tr.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            if on:
                tick = QPainterPath(QPointF(tr.left() + 3, tr.center().y() + 0.5))
                tick.lineTo(tr.left() + 5.5, tr.bottom() - 3.5)
                tick.lineTo(tr.right() - 3, tr.top() + 3.5)
                p.setPen(QPen(theme.BG, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPath(tick)
            p.setRenderHint(QPainter.Antialiasing, False)

    def _paint_header(self, p: QPainter, w: int, t0: float, t1: float) -> None:
        ws = self.ctl.ws
        tm = ws.tempo_map
        p.fillRect(0, 0, w, RULER_H, theme.RULER_BG)
        p.fillRect(0, RULER_H, w, INFO_H, theme.INFO_BG)
        p.fillRect(0, RANGE_TOP, w, RANGE_H, theme.RANGE_STRIP_BG)
        p.fillRect(0, HEADER_H - 1, w, 1, theme.LANE_SEP)

        # bar numbers and beat ticks
        stride, _ = self._grid_levels()
        p.setFont(self.font_ruler)
        fm = QFontMetrics(self.font_ruler)
        start = Fraction(math.floor(t0)) - 8
        for idx, bs, be, ts in tm.bars(max(start, ZERO), Fraction(math.ceil(t1)) + 1):
            x = round(self.x_of(float(bs))) + 0.5
            if idx % stride == 0:
                p.setPen(QPen(theme.TEXT_DIM, 1))
                p.drawLine(QPointF(x, RULER_H - 9), QPointF(x, RULER_H))
                p.setPen(theme.TEXT)
                p.drawText(QPointF(x + 3, fm.ascent() + 2), str(idx + 1))
            beat_px = self.ppb * float(ts.beat_length)
            if beat_px >= 9 and stride == 1:
                b = bs + ts.beat_length
                k = 2
                while b < be:
                    xb = round(self.x_of(float(b))) + 0.5
                    p.setPen(QPen(theme.TEXT_FAINT, 1))
                    p.drawLine(QPointF(xb, RULER_H - 4), QPointF(xb, RULER_H))
                    if beat_px >= 46:
                        p.setPen(theme.TEXT_DIM)
                        p.drawText(QPointF(xb + 3, fm.ascent() + 2), f"{idx + 1}.{k}")
                    b += ts.beat_length
                    k += 1

        # info row: tempo, time signature, markers
        p.setFont(self.font_small)
        fs = QFontMetrics(self.font_small)
        iy = RULER_H + fs.ascent() + 2
        for c in tm.effective_timesigs():
            x = self.x_of(float(c.time))
            if -60 < x < w:
                p.setPen(theme.TS_COL)
                p.drawText(QPointF(x + 3, iy), f"{c.numerator}/{c.denominator}")
        for c in tm.effective_tempos():
            x = self.x_of(float(c.time))
            if -60 < x < w:
                p.setPen(theme.TEMPO_COL)
                p.drawText(QPointF(x + 30, iy), f"♩{c.bpm:.4g}")
        change_times = {float(c.time) for c in tm.effective_tempos()} | {float(c.time) for c in tm.effective_timesigs()}
        for track in ws.tracks:
            for clip in track.clips:
                for t, kind, text in self.render_for(clip).texts:
                    if kind not in ("marker", "cue_marker"):
                        continue
                    x = self.x_of(t + float(clip.offset))
                    if -100 < x < w:
                        p.setPen(QPen(theme.MARKER_COL, 1))
                        p.drawLine(QPointF(x + 0.5, RULER_H), QPointF(x + 0.5, RANGE_TOP))
                        dx = 72 if (t + float(clip.offset)) in change_times else 4
                        p.drawText(QPointF(x + dx, iy), fs.elidedText(text, Qt.ElideRight, 120))

        # range strip
        sel = self.ctl.selected_range_id
        for i, r in enumerate(ws.ranges):
            x0, x1 = self.x_of(float(r.start)), self.x_of(float(r.end))
            if x1 < 0 or x0 > w:
                continue
            selected = r.id == sel
            rect = QRectF(x0, RANGE_TOP + 2, max(x1 - x0, 2), RANGE_H - 4)
            p.setPen(QPen(theme.ACCENT if selected else theme.RANGE_EDGE, 1))
            p.setBrush(theme.RANGE_BODY_SEL if selected else theme.RANGE_BODY)
            p.drawRoundedRect(rect, 3, 3)
            label = r.name or f"Range {i + 1}"
            label += f"   {tm.format_bbt(r.start)} – {tm.format_bbt(r.end)}"
            p.setPen(theme.TEXT if selected else theme.TEXT_DIM)
            vis_left = max(rect.left(), 0) + 5
            avail = int(rect.right() - vis_left - 5)
            if avail > 12:
                p.drawText(QPointF(vis_left, RANGE_TOP + 2 + (RANGE_H - 4 + fs.ascent() - fs.descent()) / 2),
                           fs.elidedText(label, Qt.ElideRight, avail))
            # edge handles
            p.setPen(Qt.NoPen)
            p.setBrush(theme.ACCENT if selected else theme.RANGE_EDGE)
            p.drawRect(QRectF(x0, RANGE_TOP + 2, 3, RANGE_H - 4))
            p.drawRect(QRectF(x1 - 3, RANGE_TOP + 2, 3, RANGE_H - 4))

        if self._hover_x is not None and self._drag is None:
            p.setPen(QPen(theme.HOVER_LINE, 1))
            p.drawLine(QPointF(self._hover_x + 0.5, 0), QPointF(self._hover_x + 0.5, HEADER_H))

    def toggle_rect(self, r, lane: int) -> QRectF | None:
        """Where a range's include toggle sits in a lane, or None when the range
        (or lane) is too small to hold it."""
        x0, x1 = self.x_of(float(r.start)), self.x_of(float(r.end))
        if x1 - x0 < TOGGLE_GAP + TOGGLE_PX + 4 or self.lane_h < TOGGLE_PX + 6:
            return None
        return QRectF(round(x0) + TOGGLE_GAP, self.lane_top(lane) + 4, TOGGLE_PX, TOGGLE_PX)

    # ------------------------------------------------------------------ hit testing
    def _hit(self, pos: QPointF) -> tuple:
        x, y = pos.x(), pos.y()
        ranges = sorted(self.ctl.ws.ranges, key=lambda r: r.id != self.ctl.selected_range_id)
        if y >= HEADER_H:
            i = self.lane_at(y)
            if i >= 0:
                for r in ranges:
                    tr = self.toggle_rect(r, i)
                    if tr is not None and tr.adjusted(-2, -2, 2, 2).contains(pos):
                        return ("toggle", r.id, self.ctl.ws.tracks[i].id)
        best = None
        for r in ranges:
            for edge, t in (("start", r.start), ("end", r.end)):
                d = abs(self.x_of(float(t)) - x)
                if d <= EDGE_PX and (best is None or d < best[0]):
                    best = (d, r.id, edge)
        if best is not None and y >= RULER_H:
            return ("edge", best[1], best[2])
        if RANGE_TOP <= y < HEADER_H:
            for r in ranges:
                if self.x_of(float(r.start)) <= x <= self.x_of(float(r.end)):
                    return ("body", r.id)
            return ("strip",)
        if y >= HEADER_H:
            i = self.lane_at(y)
            if i >= 0:
                track = self.ctl.ws.tracks[i]
                t = self.t_of(x)
                for clip in track.clips:
                    if float(clip.start) <= t < float(clip.end):
                        return ("clip", track.id, clip.id)
                return ("lane", track.id)
        return ("empty",)

    def _range_at_x(self, x: float) -> str | None:
        t = self.t_of(x)
        for r in reversed(self.ctl.ws.ranges):
            if float(r.start) <= t < float(r.end):
                return r.id
        return None

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self.setFocus()
        pos = e.position()
        hit = self._hit(pos)
        if e.button() == Qt.RightButton:
            self._context_menu(hit, e)
            return
        if e.button() != Qt.LeftButton:
            return
        bypass = bool(e.modifiers() & Qt.ShiftModifier)
        self._press_pos = pos
        if hit[0] == "toggle":
            self._flip_toggle(hit)
        elif hit[0] == "edge":
            self.ctl.checkpoint()
            self.ctl.select_range(hit[1])
            self._drag = {"kind": "resize", "rid": hit[1], "edge": hit[2]}
        elif hit[0] == "body":
            r = self.ctl.ws.range(hit[1])
            self.ctl.select_range(hit[1])
            self._drag = {"kind": "move", "rid": hit[1], "grab": self.time_at(pos.x(), True) - r.start,
                          "checkpointed": False}
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif hit[0] == "clip" and e.modifiers() & Qt.AltModifier:
            track = self.ctl.ws.track(hit[1])
            clip = next(c for c in track.clips if c.id == hit[2])
            self._drag = {"kind": "clip", "cid": hit[2], "orig_off": clip.offset, "origin": track.copy(),
                          "copy": bool(e.modifiers() & Qt.ControlModifier),
                          "grab": quantize(self.t_of(pos.x())) - clip.offset, "checkpointed": False}
            self.viewport().setCursor(Qt.DragCopyCursor if self._drag["copy"] else Qt.ClosedHandCursor)
        else:
            self._drag = {"kind": "create", "anchor": self.time_at(pos.x(), bypass), "rid": None}

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pos = e.position()
        bypass = bool(e.modifiers() & Qt.ShiftModifier)
        self._hover_x = pos.x()
        t_hover = self.time_at(pos.x(), True)
        tm = self.ctl.ws.tempo_map
        self.hoverTextChanged.emit(f"{tm.format_bbt(t_hover)}   ({tm.seconds_at(t_hover):.2f} s)")
        d = self._drag
        if d is None:
            self._update_cursor(pos, e.modifiers())
            self.viewport().update(0, 0, self.viewport().width(), HEADER_H)
            return
        self._check_autoscroll(pos.x())
        self._drag_to(pos.x(), bypass, pos.y())

    def _drag_to(self, x: float, bypass: bool, y: float | None = None) -> None:
        d = self._drag
        if d is None:
            return
        if d["kind"] == "clip":
            self._drag_clip(x, y, bypass)
            return
        t = self.time_at(x, bypass)
        if d["kind"] == "create":
            if d["rid"] is None:
                if self._press_pos is None or abs(x - self._press_pos.x()) < 4:
                    return
                self.ctl.checkpoint()
                d["rid"] = self.ctl.add_range(d["anchor"], d["anchor"]).id
            a = d["anchor"]
            self.ctl.update_range(d["rid"], start=min(a, t), end=max(a, t))
        elif d["kind"] == "resize":
            r = self.ctl.ws.range(d["rid"])
            if r is None:
                return
            if d["edge"] == "start":
                if t > r.end:
                    d["edge"] = "end"
                    self.ctl.update_range(r.id, start=r.end, end=t)
                else:
                    self.ctl.update_range(r.id, start=t)
            else:
                if t < r.start:
                    d["edge"] = "start"
                    self.ctl.update_range(r.id, start=t, end=r.start)
                else:
                    self.ctl.update_range(r.id, end=t)
        elif d["kind"] == "move":
            r = self.ctl.ws.range(d["rid"])
            if r is None:
                return
            raw = self.time_at(x, True) - d["grab"]
            new_start = max(self.ctl.snap_time(max(raw, ZERO), bypass), ZERO)
            if new_start != r.start:
                if not d["checkpointed"]:
                    self.ctl.checkpoint()
                    d["checkpointed"] = True
                self.ctl.update_range(r.id, start=new_start, end=new_start + r.length)

    def _drag_clip(self, x: float, y: float | None, lock_time: bool) -> None:
        """Move (or copy) a clip in time and across tracks. Shift keeps its time."""
        d = self._drag
        ws = self.ctl.ws
        found = ws.find_clip(d["cid"])
        if found is None:
            return
        cur_track, clip = found
        if lock_time:
            new_off = d["orig_off"]
        else:
            raw = quantize(max(self.t_of(x), 0.0)) - d["grab"]
            new_off = max(self.ctl.snap_time(max(raw, ZERO)), ZERO)
        dest_id: str | None = cur_track.id
        to_new = False
        if y is not None and y >= HEADER_H:
            lane = self.lane_at(y)
            if lane >= 0:
                dest_id = ws.tracks[lane].id
            elif y >= self.lane_top(len(ws.tracks)):
                # below the last lane: a new track, unless the clip already sits alone on the
                # last one (a new track there would look identical once the old one is removed)
                last = ws.tracks[-1] if ws.tracks else None
                pending_copy = d["copy"] and not d["checkpointed"]   # the copy isn't made yet
                to_new = not (last is cur_track and len(cur_track.clips) == 1 and not pending_copy)
                dest_id = None if to_new else cur_track.id
        if new_off == clip.offset and dest_id == cur_track.id and not to_new:
            return
        if not d["checkpointed"]:
            self.ctl.checkpoint()
            d["checkpointed"] = True
            if d["copy"]:
                dup = self.ctl.duplicate_clip(d["cid"], offset=clip.offset, checkpoint=False)
                if dup is None:
                    return
                d["cid"] = dup
        if to_new:
            ws.new_track_for_clip(d["cid"], like=d["origin"])
            self.ctl.move_clip_live(d["cid"], new_off)
            self.ctl.tracksChanged.emit()
        else:
            self.ctl.move_clip_live(d["cid"], new_off, dest_id)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        d = self._drag
        self._drag = None
        self._autoscroll.stop()
        if d is None:
            return
        if d["kind"] == "clip" and d["checkpointed"]:
            self.ctl.end_clip_gesture()
        if d["kind"] == "create":
            if d["rid"] is None:
                rid = self._range_at_x(e.position().x()) if e.position().y() >= RULER_H else None
                self.ctl.select_range(rid)
            else:
                r = self.ctl.ws.range(d["rid"])
                if r is not None and r.is_empty:
                    self.ctl.delete_range(r.id, checkpoint=False)
        self._update_cursor(e.position(), e.modifiers())
        self.viewport().update()

    def _flip_toggle(self, hit: tuple) -> None:
        _kind, rid, tid = hit
        r = self.ctl.ws.range(rid)
        if r is not None:
            self.ctl.select_range(rid)
            self.ctl.set_range_track_included(rid, tid, not r.includes(tid))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        hit = self._hit(e.position())
        if hit[0] == "toggle":          # a quick second click is another click, not "edit range"
            self._flip_toggle(hit)
        elif hit[0] in ("body", "edge"):
            self.ctl.select_range(hit[1])
            self.rangeEditRequested.emit(hit[1])
        elif hit[0] in ("lane", "clip") and e.position().y() >= HEADER_H:
            rid = self._range_at_x(e.position().x())
            if rid:
                self.ctl.select_range(rid)
                self.rangeEditRequested.emit(rid)

    def leaveEvent(self, _e) -> None:
        self._hover_x = None
        self.viewport().update(0, 0, self.viewport().width(), HEADER_H)

    def _update_cursor(self, pos: QPointF, mods) -> None:
        hit = self._hit(pos)
        vp = self.viewport()
        tip = ""
        if hit[0] == "toggle":
            vp.setCursor(Qt.PointingHandCursor)
            r, t = self.ctl.ws.range(hit[1]), self.ctl.ws.track(hit[2])
            if r is not None and t is not None:
                label = r.name or f"Range {self.ctl.ws.ranges.index(r) + 1}"
                tip = (f"“{t.name}” is {'included in' if r.includes(t.id) else 'excluded from'} {label}"
                       f" — click to {'exclude' if r.includes(t.id) else 'include'}")
        elif hit[0] == "edge":
            vp.setCursor(Qt.SizeHorCursor)
        elif hit[0] == "body":
            vp.setCursor(Qt.OpenHandCursor)
        elif hit[0] == "clip" and mods & Qt.AltModifier:
            vp.setCursor(Qt.SizeAllCursor)
        else:
            vp.setCursor(Qt.IBeamCursor)
        if vp.toolTip() != tip:
            vp.setToolTip(tip)

    def _check_autoscroll(self, x: float) -> None:
        w = self.viewport().width()
        if x < 20 or x > w - 20:
            if not self._autoscroll.isActive():
                self._autoscroll.start()
        else:
            self._autoscroll.stop()

    def _autoscroll_tick(self) -> None:
        if self._drag is None:
            self._autoscroll.stop()
            return
        x = self.viewport().mapFromGlobal(QCursor.pos()).x()
        w = self.viewport().width()
        hbar = self.horizontalScrollBar()
        if x < 20:
            hbar.setValue(hbar.value() - max(4, int(20 - x)))
        elif x > w - 20:
            hbar.setValue(hbar.value() + max(4, int(x - (w - 20))))
        else:
            self._autoscroll.stop()
            return
        from PySide6.QtWidgets import QApplication
        y = self.viewport().mapFromGlobal(QCursor.pos()).y()
        self._drag_to(min(max(x, 0), w), bool(QApplication.keyboardModifiers() & Qt.ShiftModifier), y)

    def _context_menu(self, hit: tuple, e: QMouseEvent) -> None:
        gp = e.globalPosition().toPoint()
        if hit[0] in ("body", "edge", "toggle"):
            self.ctl.select_range(hit[1])
            self.range_menu(hit[1]).exec(gp)
        elif hit[0] == "clip":
            self.clipContextMenuRequested.emit(hit[1], hit[2], gp)
        elif hit[0] == "lane":
            self.trackContextMenuRequested.emit(hit[1], gp)

    def range_menu(self, rid: str) -> QMenu:
        """Range context menu: edit/delete, and which tracks this range exports."""
        ctl = self.ctl
        r = ctl.ws.range(rid)
        m = QMenu(self)
        m.addAction("Edit Range…", lambda: self.rangeEditRequested.emit(rid))
        m.addAction("Delete Range", lambda: ctl.delete_range(rid))
        if r is None or not ctl.ws.tracks:
            return m
        m.addSection("Tracks in this range")
        for t in ctl.ws.tracks:
            a = m.addAction(t.name)
            a.setCheckable(True)
            a.setChecked(r.includes(t.id))
            a.toggled.connect(lambda on, tid=t.id: ctl.set_range_track_included(rid, tid, on))
        m.addSeparator()
        m.addAction("Include All Tracks", lambda: ctl.set_range_tracks(rid, True))
        m.addAction("Exclude All Tracks", lambda: ctl.set_range_tracks(rid, False))
        m.addAction("Reset to Track Toggles", lambda: ctl.set_range_tracks(rid, None))
        return m

    # ------------------------------------------------------------------ wheel / keys / gestures
    def wheelEvent(self, e: QWheelEvent) -> None:
        mods = e.modifiers()
        pd, ad = e.pixelDelta(), e.angleDelta()
        if mods & Qt.ControlModifier:  # Cmd on macOS
            dy = ad.y() if ad.y() else pd.y() * 2
            self.zoom_by(1.0015 ** dy, e.position().x())
            e.accept()
            return
        if mods & Qt.AltModifier:
            dy = ad.y() or ad.x()
            self.set_lane_height(self.lane_h + (6 if dy > 0 else -6))
            e.accept()
            return
        if not pd.isNull():
            dx, dy = pd.x(), pd.y()
        else:
            dx, dy = ad.x() / 2, ad.y() / 2
        if mods & Qt.ShiftModifier and dx == 0:
            dx, dy = dy, 0
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        hbar.setValue(int(hbar.value() - dx))
        vbar.setValue(int(vbar.value() - dy))
        e.accept()

    def viewportEvent(self, e: QEvent) -> bool:
        if e.type() == QEvent.NativeGesture:
            ge: QNativeGestureEvent = e  # type: ignore[assignment]
            if ge.gestureType() == Qt.ZoomNativeGesture:
                self.zoom_by(1.0 + ge.value(), ge.position().x())
                return True
            if ge.gestureType() == Qt.SmartZoomNativeGesture:
                self.zoom_to_fit()
                return True
        return super().viewportEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.ctl.delete_range()
        elif e.key() == Qt.Key_Escape:
            self.ctl.select_range(None)
        elif e.key() == Qt.Key_Tab and self.ctl.ws.ranges:
            ids = [r.id for r in self.ctl.ws.ranges]
            cur = ids.index(self.ctl.selected_range_id) if self.ctl.selected_range_id in ids else -1
            nxt = ids[(cur + 1) % len(ids)]
            self.ctl.select_range(nxt)
            self.scroll_to_time(float(self.ctl.ws.range(nxt).start))
        else:
            super().keyPressEvent(e)

    def focusNextPrevChild(self, _next: bool) -> bool:
        return False  # keep Tab for range cycling
