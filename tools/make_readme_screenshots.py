"""Makes the annotated screenshots used in the README (docs/images/).

Run from the repo root:  QT_QPA_PLATFORM=offscreen .venv/bin/python tools/make_readme_screenshots.py

It builds a small demo song (four tracks, a verse and a chorus) inside the real window and grabs the
window in each scenario, so the pictures always show the app as it really is. Numbered badges are
drawn on top; the README's captions explain them.
"""
from __future__ import annotations

import os
import sys
from fractions import Fraction as F

import mido

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from midi_interchange.core.placement import Placement  # noqa: E402
from midi_interchange.core.export_smf import ExportMode  # noqa: E402
from midi_interchange.interchange.payload import Payload  # noqa: E402
from midi_interchange.ui import theme  # noqa: E402
from midi_interchange.ui.main_window import MainWindow  # noqa: E402
from midi_interchange.ui.timeline import RULER_H  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
PPQ = 480
BAR = 4 * PPQ
BADGE = QColor("#ff5a36")


# ---------------------------------------------------------------- demo MIDI
def _track(events, name):
    trk = mido.MidiTrack()
    trk.append(mido.MetaMessage("track_name", name=name, time=0))
    prev = 0
    for tick, msg in sorted(events, key=lambda e: e[0]):
        trk.append(msg.copy(time=tick - prev))
        prev = tick
    trk.append(mido.MetaMessage("end_of_track", time=0))
    return trk


def _notes(ch, pitches_starts_durs, vel=96):
    ev = []
    for pitch, start, dur in pitches_starts_durs:
        ev.append((start, mido.Message("note_on", channel=ch, note=pitch, velocity=vel)))
        ev.append((start + dur, mido.Message("note_off", channel=ch, note=pitch, velocity=0)))
    return ev


def _file(name, events, bars=4):
    mf = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    cond = mido.MidiTrack()
    cond.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(110), time=0))
    cond.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    cond.append(mido.MetaMessage("end_of_track", time=0))
    mf.tracks.append(cond)
    trk = _track(events, name)
    trk[-1].time = max(0, bars * BAR - sum(m.time for m in trk))
    mf.tracks.append(trk)
    import io
    buf = io.BytesIO()
    mf.save(file=buf)
    return buf.getvalue()


# The verse is sparse, low and slow; the chorus is busy, high and fast, so the two ranges look
# clearly different on the timeline.
def drums(chorus, marker: str | None = None):
    ev = [(0, mido.MetaMessage("marker", text=marker, time=0))] if marker else []
    for bar in range(4):
        for beat in range(4):
            t = bar * BAR + beat * PPQ
            if not chorus:
                if beat in (0, 2):
                    ev += _notes(9, [(36, t, 120)])            # kick on 1 and 3
                if beat == 3:
                    ev += _notes(9, [(38, t, 120)])            # one snare per bar
            else:
                ev += _notes(9, [(36 if beat % 2 == 0 else 38, t, 100)])
                for sub in range(4):                           # sixteenth hats
                    ev += _notes(9, [(42, t + sub * PPQ // 4, 50)], vel=75)
                if beat == 2:
                    ev += _notes(9, [(46, t + PPQ // 2, 100)])  # open hat
        if chorus:
            ev += _notes(9, [(49, bar * BAR, 480)])             # crash every bar
    return _file("Drums", ev)


def bass(chorus):
    ev = []
    if not chorus:
        for bar, r in enumerate([36, 41, 43, 36]):              # one long low note a bar
            ev += _notes(1, [(r, bar * BAR, BAR - 60)])
    else:
        for bar, r in enumerate([48, 53, 55, 50]):              # busy octave-jumping eighths
            for step in range(8):
                ev += _notes(1, [(r + (12 if step % 2 else 0), bar * BAR + step * PPQ // 2, PPQ // 2 - 20)])
    return _file("Bass", ev)


def keys(chorus):
    ev = []
    if not chorus:
        for bar, ch in enumerate([(48, 52, 55), (53, 57, 60), (55, 59, 62), (48, 52, 55)]):
            ev += _notes(2, [(p, bar * BAR, BAR - 40) for p in ch], vel=70)   # low held chords
    else:
        for bar, ch in enumerate([(72, 76, 79), (77, 81, 84), (79, 83, 86), (72, 76, 79)]):
            for beat in range(4):                                              # high stabs
                ev += _notes(2, [(p, bar * BAR + beat * PPQ, PPQ // 3) for p in ch], vel=100)
    return _file("Keys", ev)


def lead(chorus):
    ev = []
    if not chorus:
        for i, p in enumerate([64, 67, 65, 62]):                # four long notes
            ev += _notes(3, [(p, i * BAR, BAR - 120)], vel=90)
    else:
        mel = [76, 79, 83, 79, 84, 83, 79, 76]
        for i in range(32):                                     # fast eighth-note run
            ev += _notes(3, [(mel[i % 8] + (2 if i >= 16 else 0), i * PPQ // 2, PPQ // 2 - 20)], vel=110)
    return _file("Lead", ev)


# A mid-energy build between verse and chorus (quarter-note pulse, rising lead), used only by image 8
# so its ranges are visibly carved out of a continuous song.
def prechorus(fn):
    ev = []
    name = fn.__name__
    if name == "drums":
        for bar in range(4):
            for beat in range(4):
                t = bar * BAR + beat * PPQ
                ev += _notes(9, [(36 if beat == 0 else 38, t, 100)])
                ev += _notes(9, [(42, t + PPQ // 2, 60)], vel=70)         # eighth hats
    elif name == "bass":
        for bar, r in enumerate([40, 45, 47, 43]):
            for beat in range(4):
                ev += _notes(1, [(r, bar * BAR + beat * PPQ, PPQ - 40)])  # steady quarters
    elif name == "keys":
        for bar, ch in enumerate([(60, 64, 67), (65, 69, 72), (67, 71, 74), (67, 71, 74)]):
            for half in range(2):
                ev += _notes(2, [(p, bar * BAR + half * 2 * PPQ, 2 * PPQ - 40) for p in ch], vel=85)
    else:
        for i in range(16):
            ev += _notes(3, [(64 + i, i * PPQ, PPQ - 40)], vel=100)       # rising quarter notes
    return _file(name.capitalize(), ev)


# ---------------------------------------------------------------- annotation
class Shot:
    def __init__(self, w: MainWindow) -> None:
        QApplication.processEvents()
        self.w = w
        self.pm: QPixmap = w.grab()
        self.p = QPainter(self.pm)
        self.p.setRenderHint(QPainter.Antialiasing)
        self.n = 0

    def rect(self, r: QRect | QRectF, color=BADGE) -> None:
        self.p.setPen(QPen(color, 2.5))
        self.p.setBrush(Qt.NoBrush)
        self.p.drawRoundedRect(QRectF(r), 4, 4)

    def badge(self, x: float, y: float, text: str | None = None) -> None:
        """A numbered circle centred on (x, y)."""
        if text is None:
            self.n += 1
            text = str(self.n)
        p = self.p
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(BADGE)
        p.drawEllipse(QPointF(x, y), 12, 12)
        f = QFont(p.font())
        f.setBold(True)
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(x - 12, y - 12, 24, 24), Qt.AlignCenter, text)

    def note(self, r: QRect | QRectF, x: float | None = None, y: float | None = None) -> None:
        """Outline a region and put the next number at its top-left corner (or at x, y)."""
        r = QRectF(r)
        self.rect(r)
        self.badge(r.left() + 14 if x is None else x, r.top() + 2 if y is None else y)

    def arrow(self, x0, y0, x1, y1) -> None:
        import math
        p = self.p
        p.setPen(QPen(BADGE, 3))
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        a = math.atan2(y1 - y0, x1 - x0)
        for da in (2.7, -2.7):
            p.drawLine(QPointF(x1, y1), QPointF(x1 + 12 * math.cos(a + da), y1 + 12 * math.sin(a + da)))

    def save(self, name: str, crop: QRect | None = None) -> None:
        self.p.end()
        pm = self.pm.copy(crop) if crop else self.pm
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, name)
        pm.save(path, "PNG")
        print("wrote", os.path.relpath(path, ROOT), pm.width(), "x", pm.height())


# ---------------------------------------------------------------- scenario plumbing
def new_window(app) -> MainWindow:
    # Own settings file, so the pictures never depend on this machine's settings (Show Markers on).
    import tempfile
    from PySide6.QtCore import QSettings
    w = MainWindow(QSettings(os.path.join(tempfile.mkdtemp(), "screenshots.ini"), QSettings.IniFormat))
    w.resize(1280, 760)
    w.show()
    app.processEvents()
    return w


def drop(w: MainWindow, name: str, data: bytes, bar: int, track: str | None = None) -> None:
    tid = None
    if track:
        tid = next(t.id for t in w.ctl.ws.tracks if t.name == track)
    w.ctl.import_payloads([Payload(f"{name}.mid", data)], Placement(time=F(4 * (bar - 1)), target_track_id=tid))


def build_song(w: MainWindow, chorus_bar: int = 9, full_song: bool = False, markers: bool = False) -> None:
    """full_song also fills the gap with a Pre-Chorus (bars 5-9) and adds an Outro after the chorus.
    markers puts "Verse" and "Chorus" markers on the Drums clips, so the header shows its marker row."""
    for fn in (drums, bass, keys, lead):
        name = fn.__name__.capitalize()
        if markers and fn is drums:
            drop(w, name + " - Verse", drums(False, "Verse"), 1)
            drop(w, name + " - Chorus", drums(True, "Chorus"), chorus_bar, name)
            continue
        drop(w, name + " - Verse", fn(False), 1)
        if full_song:
            drop(w, name + " - Pre-Chorus", prechorus(fn), 5, name)
        drop(w, name + " - Chorus", fn(True), chorus_bar, name)
        if full_song:
            drop(w, name + " - Outro", fn(False), chorus_bar + 4, name)
    w.timeline.zoom_to_fit()
    w.timeline.horizontalScrollBar().setValue(0)
    QApplication.processEvents()


def pos_in(w: MainWindow, widget, pt: QPoint) -> QPoint:
    return widget.mapTo(w, pt)


def clip_xy(w: MainWindow, track_index: int, bar: float) -> tuple[float, float]:
    """Window coordinates of the left edge of a bar in a lane (lane's vertical middle)."""
    tl = w.timeline
    pt = QPoint(int(tl.x_of(4 * (bar - 1))), tl.lane_top(track_index) + tl.lane_h // 2)
    return pos_in(w, tl.viewport(), pt).x(), pos_in(w, tl.viewport(), pt).y()


def bar_x(w: MainWindow, bar: float) -> float:
    return pos_in(w, w.timeline.viewport(), QPoint(int(w.timeline.x_of(4 * (bar - 1))), 0)).x()


def vp_rect(w: MainWindow, x0: float, y0: float, x1: float, y1: float) -> QRectF:
    o = pos_in(w, w.timeline.viewport(), QPoint(0, 0))
    return QRectF(o.x() + x0, o.y() + y0, x1 - x0, y1 - y0)


def wrect(w: MainWindow, widget) -> QRectF:
    """A child widget's rectangle in window coordinates."""
    o = pos_in(w, widget, QPoint(0, 0))
    return QRectF(o.x(), o.y(), widget.width(), widget.height())


def compose(parts: list[tuple[str, QPixmap]], width: int | None = None) -> QPixmap:
    """Stack captioned pictures vertically."""
    cap_h, gap = 26, 10
    width = width or max(pm.width() for _, pm in parts)
    height = sum(cap_h + pm.height() + gap for _, pm in parts) - gap
    out = QPixmap(width, height)
    out.fill(QColor("#101113"))
    p = QPainter(out)
    f = QFont(p.font())
    f.setBold(True)
    f.setPixelSize(15)
    p.setFont(f)
    y = 0
    for caption, pm in parts:
        p.setPen(QColor("#f2b134"))
        p.drawText(QRect(8, y, width - 16, cap_h), Qt.AlignVCenter | Qt.AlignLeft, caption)
        p.drawPixmap(0, y + cap_h, pm)
        y += cap_h + pm.height() + gap
    p.end()
    return out


def tracks_crop(w: MainWindow) -> QPixmap:
    """Just the track headers and the timeline (no toolbar or export panel)."""
    QApplication.processEvents()
    y = pos_in(w, w.timeline.viewport(), QPoint(0, 0)).y()
    n = len(w.ctl.ws.tracks)
    return w.grab().copy(QRect(0, y - 2, w.width(), w.timeline.header_h() + n * w.timeline.lane_h + 6))


def exported_window(app, results, height=520) -> QPixmap:
    """Open an export result in a fresh window and return a picture of its timeline area."""
    import io
    w = new_window(app)
    w.resize(1280, height)
    for r in results:
        buf = io.BytesIO()
        r.midi.save(file=buf)
        w.ctl.import_payloads([Payload(r.label + ".mid", buf.getvalue())], Placement(end_to_end=False))
    w.timeline.zoom_to_fit()
    pm = tracks_crop(w)
    w.close()
    return pm


def main() -> None:
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    from PySide6.QtWidgets import QToolBar

    # ---- 1. the window ------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 640)
    build_song(w, markers=True)
    ctl = w.ctl
    ctl.add_range(F(0), F(16))
    ctl.update_range(ctl.ws.ranges[0].id, name="Verse")
    ctl.add_range(F(32), F(48))
    ctl.update_range(ctl.ws.ranges[1].id, name="Chorus")
    ctl.select_range(ctl.ws.ranges[0].id)
    s = Shot(w)
    tl, tp, ep = w.timeline, w.track_panel, w.export_panel
    vw = tl.viewport().width()
    s.note(QRectF(w.findChild(QToolBar).geometry()).adjusted(2, 2, -2, -2))
    s.note(vp_rect(w, 0, 0, vw, tl.range_top()))
    s.note(vp_rect(w, 0, tl.range_top(), vw, tl.header_h()))
    s.note(QRectF(wrect(w, tp)).adjusted(1, tl.header_h(), -1, 0))
    s.note(vp_rect(w, 0, tl.header_h(), vw, tl.lane_top(4)), x=bar_x(w, 3) + 6, y=vp_rect(w, 0, tl.header_h(), 0, 0).top() + 14)
    s.note(wrect(w, ep).adjusted(2, 2, -2, -2))
    s.save("01-window.png")
    w.close()

    # ---- 2. dragging in: the landing preview ------------------------------------------
    w = new_window(app)
    w.resize(1280, 520)
    build_song(w)
    w.ctl.delete_clip(w.ctl.ws.tracks[3].clips[1].id)  # the Lead chorus clip is "still in the DAW"
    w.timeline.set_drop_indicator((3, F(32), "Onto “Lead” at 9.1.000 if the names match, else new track(s)"))
    s = Shot(w)
    x, y = clip_xy(w, 3, 9)
    s.badge(x + 16, y - 42)
    s.save("02-drag-in.png")
    w.close()

    # ---- 3. making ranges ---------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 560)
    build_song(w)
    ctl = w.ctl
    ctl.add_range(F(0), F(16))
    ctl.update_range(ctl.ws.ranges[0].id, name="Verse")
    ctl.add_range(F(32), F(48))
    ctl.select_range(ctl.ws.ranges[1].id)
    ctl.update_range(ctl.ws.ranges[1].id, name="Chorus")
    s = Shot(w)
    tl, ep = w.timeline, w.export_panel
    s.arrow(bar_x(w, 5) + 150, vp_rect(w, 0, tl.range_top(), 0, 0).top() + 12, bar_x(w, 5) + 20, vp_rect(w, 0, tl.range_top(), 0, 0).top() + 12)
    s.badge(bar_x(w, 5) + 168, vp_rect(w, 0, tl.range_top(), 0, 0).top() + 12)
    s.note(vp_rect(w, tl.x_of(32) - 3, tl.range_top(), tl.x_of(48) + 3, tl.header_h()))
    s.note(QRectF(wrect(w, ep)).adjusted(2, 2, -2, -ep.height() // 2 - 6))
    s.save("03-ranges.png")
    w.close()

    # ---- 4. which tracks each range sends ---------------------------------------------------
    w = new_window(app)
    w.resize(1280, 540)
    build_song(w)
    ctl = w.ctl
    ctl.add_range(F(0), F(16))
    ctl.update_range(ctl.ws.ranges[0].id, name="Verse")
    ctl.add_range(F(32), F(48))
    ctl.update_range(ctl.ws.ranges[1].id, name="Chorus")
    ch = ctl.ws.ranges[1]
    ctl.set_range_locked(ch.id, True)
    ctl.set_range_track_included(ch.id, ctl.ws.tracks[2].id, False)   # no Keys in the chorus
    ctl.set_range_track_included(ch.id, ctl.ws.tracks[0].id, False)   # no Drums either
    ctl.select_range(ch.id)
    s = Shot(w)
    tl = w.timeline
    lk = tl.lock_rect(ch)
    s.note(vp_rect(w, lk.left() - 3, lk.top() - 3, lk.right() + 3, lk.bottom() + 3))
    t0 = tl.toggle_rect(ch, 0)
    s.note(vp_rect(w, t0.left() - 3, t0.top() - 3, t0.right() + 3, t0.bottom() + 3))
    s.note(vp_rect(w, tl.x_of(32) + 60, tl.lane_top(2) + 2, tl.x_of(48) - 4, tl.lane_top(3) - 2))
    s.note(vp_rect(w, tl.x_of(32) + 60, tl.lane_top(0) + 2, tl.x_of(48) - 4, tl.lane_top(1) - 2))
    s.save("04-range-tracks.png")
    w.close()

    # ---- 5. editing clips -----------------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 540)
    build_song(w)
    ctl = w.ctl
    tr = ctl.ws.tracks
    bass_c = tr[1].clips[0]
    ctl.trim_clip_live(bass_c.id, "end", F(12), bypass_snap=True)                 # trimmed to 3 bars
    ctl.duplicate_clip(tr[2].clips[0].id)                                          # duplicate of Keys verse
    ctl.move_clip_live(tr[3].clips[1].id, F(12))                                   # Lead chorus slides back over the verse
    ctl.add_range(F(0), F(16))
    ctl.select_range(None)
    ctl.ws.ranges.clear()
    ctl.rangesChanged.emit()
    s = Shot(w)
    tl = w.timeline
    s.note(vp_rect(w, tl.x_of(10), tl.lane_top(1) + 2, tl.x_of(14), tl.lane_top(2) - 2))       # trimmed Bass clip edge
    s.note(vp_rect(w, tl.x_of(16), tl.lane_top(2) + 2, tl.x_of(32), tl.lane_top(3) - 2))      # duplicated Keys
    s.note(vp_rect(w, tl.x_of(12), tl.lane_top(3) + 2, tl.x_of(16), tl.lane_top(4) - 2))      # overlap
    s.save("05-clips.png")
    w.close()

    # ---- 6. mute and solo ----------------------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 520)
    build_song(w)
    ctl = w.ctl
    ctl.set_mute(ctl.ws.tracks[1].id, True)
    ctl.toggle_solo(ctl.ws.tracks[3].id)
    ctl.toggle_solo(ctl.ws.tracks[0].id)
    s = Shot(w)
    tp = w.track_panel
    for i, attr in ((1, "mute_btn"), (3, "solo_btn")):
        b = getattr(tp.header(ctl.ws.tracks[i].id), attr)
        s.note(QRectF(pos_in(w, b, QPoint(-3, -3)), QPointF(pos_in(w, b, QPoint(b.width() + 3, b.height() + 3)))))
    s.note(QRectF(pos_in(w, tp.clear_m, QPoint(-3, -3)), QPointF(pos_in(w, tp.clear_s, QPoint(tp.clear_s.width() + 3, tp.clear_s.height() + 3)))))
    s.save("06-mute-solo.png")
    w.close()

    # ---- 7. menus --------------------------------------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 420)
    build_song(w)
    grabbed: list[QPixmap] = []

    import midi_interchange.ui.main_window as mw

    class CaptureMenu(QMenu):
        """Stands in for QMenu while a context menu is built, so it's grabbed instead of popping up."""
        def exec(self, *a, **k):
            self.resize(self.sizeHint())
            self.ensurePolished()
            grabbed.append(self.grab())
            return None

    orig = mw.QMenu
    mw.QMenu = CaptureMenu
    try:
        w.clip_menu(w.ctl.ws.tracks[1].id, w.ctl.ws.tracks[1].clips[0].id, QPoint(10, 10))
        w.track_menu(w.ctl.ws.tracks[1].id, QPoint(10, 10))
    finally:
        mw.QMenu = orig
    w.close()
    gap = 24
    out = QPixmap(sum(pm.width() for pm in grabbed) + gap * (len(grabbed) + 1), max(pm.height() for pm in grabbed) + 2 * gap)
    out.fill(QColor("#101113"))
    p = QPainter(out)
    x = gap
    for pm in grabbed:
        p.drawPixmap(x, gap, pm)
        x += pm.width() + gap
    p.end()
    out.save(os.path.join(OUT, "07-menus.png"), "PNG")
    print("wrote docs/images/07-menus.png", out.width(), "x", out.height())

    # ---- 8. what each export mode produces ------------------------------------------------------------------
    w = new_window(app)
    w.resize(1280, 420)
    build_song(w, full_song=True)
    ctl = w.ctl
    ctl.add_range(F(0), F(16))
    ctl.update_range(ctl.ws.ranges[0].id, name="Verse")
    ctl.add_range(F(32), F(48))
    ctl.update_range(ctl.ws.ranges[1].id, name="Chorus")
    w.resize(1280, 520)
    src = tracks_crop(w)
    parts = [("Your workspace: a Verse range and a Chorus range (bars 1–5 and 9–13)", src)]
    for mode, caption in ((ExportMode.PRESERVE, "Ranges · keep positions: one file, the gap between the ranges is kept as silence"),
                          (ExportMode.REBASE, "Ranges · rebase & concatenate: one file, the ranges back to back from bar 1"),
                          (ExportMode.SEPARATE, "Ranges · separate files: one file per range (Verse.mid, Chorus.mid), each from bar 1")):
        ctl.set_export_mode(mode)
        results = ctl.build_exports()
        if mode is ExportMode.SEPARATE:
            pm = [exported_window(app, [r]) for r in results]
            for k, one in enumerate(pm):
                parts.append((caption if k == 0 else "…and the second file", one))
        else:
            parts.append((caption, exported_window(app, results)))
    w.close()
    compose(parts).save(os.path.join(OUT, "08-export-modes.png"), "PNG")
    print("wrote docs/images/08-export-modes.png")
    print("ok")


if __name__ == "__main__":
    main()
