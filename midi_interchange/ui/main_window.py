"""Single-window workspace: toolbar, track panel + timeline, export panel."""
from __future__ import annotations

import os

from fractions import Fraction

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPainter
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QSizePolicy, QSplitter, QToolBar, QVBoxLayout, QWidget)

from ..core.import_smf import ImportError_, import_smf_bytes
from ..core.names import quoted
from ..core.placement import Placement, plan_drop
from ..core.timing import ZERO
from ..interchange.drag_import import extract_payloads
from ..interchange.payload import Payload
from . import theme
from .about_dialog import AboutDialog
from .controller import SNAP_CHOICES, Controller
from .export_panel import ExportPanel, start_file_drag
from .timeline import HEADER_H, Timeline
from .track_panel import TrackPanel

APP_NAME = "MIDI Interchange"


class DropOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _e) -> None:
        # Border only: the lanes stay visible so the insertion cursor can be seen.
        p = QPainter(self)
        p.setPen(theme.ACCENT)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 820)
        self.setAcceptDrops(True)
        self.settings = QSettings("MIDI Interchange", "MIDI Interchange")

        self.ctl = Controller()
        self.timeline = Timeline(self.ctl)
        self.track_panel = TrackPanel(self.ctl, self.timeline)
        self.export_panel = ExportPanel(self.ctl)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.track_panel)
        splitter.addWidget(self.timeline)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1100])
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(splitter, 1)
        lay.addWidget(self.export_panel)
        self.setCentralWidget(central)
        self.overlay = DropOverlay(central)

        self.hover_label = QLabel()
        self.tempo_label = QLabel()
        self.statusBar().addPermanentWidget(self.tempo_label)
        self.statusBar().addPermanentWidget(self.hover_label)
        self.statusBar().setSizeGripEnabled(False)

        self._build_actions()
        self._build_toolbar()
        self._build_menus()

        self.ctl.message.connect(lambda m: self.statusBar().showMessage(m, 10000))
        self.export_panel.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.export_panel.saveRequested.connect(self.save_midi)
        self.ctl.undoStateChanged.connect(self._update_undo_actions)
        self.ctl.tempoChanged.connect(self._update_tempo_label)
        self.ctl.tracksChanged.connect(self._first_import_fit)
        self.timeline.hoverTextChanged.connect(self.hover_label.setText)
        self.timeline.trackContextMenuRequested.connect(self.track_menu)
        self.timeline.clipContextMenuRequested.connect(self.clip_menu)
        self.timeline.rangeEditRequested.connect(lambda _rid: self.export_panel.focus_range_name())
        self.track_panel.trackContextMenuRequested.connect(self.track_menu)
        self._update_undo_actions()
        self._update_tempo_label()
        self._had_tracks = False
        self._drag_payloads: list[Payload] = []
        self._drag_diagnostics: list[str] = []
        self._drag_parsed: list | None = None   # the dragged files, parsed (None = not readable yet)

    # ------------------------------------------------------------------ actions
    def _act(self, text: str, slot, shortcut=None, tip: str | None = None) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        self.a_new = self._act("New", self.ctl.new_document, QKeySequence.New,
                               "Clear the workspace and start again (undoable)")
        self.a_open = self._act("Open…", self.open_files, QKeySequence.Open, "Import MIDI files (accumulative)")
        self.a_save = self._act("Save MIDI…", self.save_midi, QKeySequence.Save, "Export with current settings")
        self.a_undo = self._act("Undo", self.ctl.undo, QKeySequence.Undo)
        self.a_redo = self._act("Redo", self.ctl.redo, QKeySequence.Redo)
        self.a_zoom_in = self._act("Zoom In", lambda: self.timeline.zoom_by(1.4), QKeySequence.ZoomIn)
        self.a_zoom_out = self._act("Zoom Out", lambda: self.timeline.zoom_by(1 / 1.4), QKeySequence.ZoomOut)
        self.a_zoom_fit = self._act("Zoom to Fit", self.timeline.zoom_to_fit, "Ctrl+0")
        self.a_taller = self._act("Taller Lanes", lambda: self.timeline.set_lane_height(self.timeline.lane_h + 12),
                                  "Ctrl+Shift+=")
        self.a_shorter = self._act("Shorter Lanes", lambda: self.timeline.set_lane_height(self.timeline.lane_h - 12),
                                   "Ctrl+Shift+-")
        self.a_del_range = self._act("Delete Range", lambda: self.ctl.delete_range())
        self.a_clear_ranges = self._act("Clear All Ranges", self.ctl.clear_ranges)
        self.a_enable_all = self._act("Enable All Tracks", lambda: self.ctl.set_all_enabled(True))
        self.a_about = self._act("About", self.show_about, tip="About MIDI Interchange")
        self.a_disable_all = self._act("Disable All Tracks", lambda: self.ctl.set_all_enabled(False))

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction(self.a_new)
        tb.addAction(self.a_open)
        tb.addAction(self.a_save)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        tb.addAction(self.a_zoom_in)
        tb.addAction(self.a_zoom_fit)
        tb.addSeparator()
        tb.addWidget(QLabel(" Snap "))
        self.snap_combo = QComboBox()
        for label, val in SNAP_CHOICES:
            self.snap_combo.addItem(label, val)
        self.snap_combo.setCurrentIndex(2)
        self.snap_combo.currentIndexChanged.connect(self._snap_changed)
        tb.addWidget(self.snap_combo)
        tb.addSeparator()
        tb.addAction(self.a_clear_ranges)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.a_about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self.a_new)
        m.addAction(self.a_open)
        m.addAction(self.a_save)
        m.addSeparator()
        m.addAction(self._act("Quit", self.close, QKeySequence.Quit))
        m = mb.addMenu("&Edit")
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addSeparator()
        m.addAction(self.a_del_range)
        m.addAction(self.a_clear_ranges)
        m.addSeparator()
        m.addAction(self.a_enable_all)
        m.addAction(self.a_disable_all)
        m = mb.addMenu("&View")
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_zoom_fit, self.a_taller, self.a_shorter):
            m.addAction(a)
        m = mb.addMenu("&Timing")
        self.snap_menu = m.addMenu("Snap")
        grp = QActionGroup(self)
        for i, (label, _val) in enumerate(SNAP_CHOICES):
            a = self.snap_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(i == 2)
            a.setActionGroup(grp)
            a.triggered.connect(lambda _c=False, i=i: self.snap_combo.setCurrentIndex(i))
        self._snap_actions = grp.actions()
        self.tempo_menu = m.addMenu("Tempo Map")
        self.tempo_menu.aboutToShow.connect(self._fill_tempo_menu)

    def _snap_changed(self, i: int) -> None:
        self.ctl.snap = self.snap_combo.itemData(i)
        self._snap_actions[i].setChecked(True)

    def _fill_tempo_menu(self) -> None:
        m = self.tempo_menu
        m.clear()
        ws = self.ctl.ws
        sources = [s for s in ws.sources if not s.tempo_map.is_empty]
        if not sources:
            a = m.addAction("No imported tempo maps (using 120 BPM, 4/4)")
            a.setEnabled(False)
            return
        for s in sources:
            t = s.tempo_map.effective_tempos()[0]
            ts = s.tempo_map.effective_timesigs()[0]
            extra = len(s.tempo_map.tempos) - 1
            label = f"{s.name}  —  {t.bpm:.4g} BPM, {ts.numerator}/{ts.denominator}"
            if extra > 0:
                label += f" (+{extra} changes)"
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(s.id == ws.tempo_source_id)
            a.triggered.connect(lambda _c=False, sid=s.id: self.ctl.adopt_tempo(sid))

    def _update_undo_actions(self) -> None:
        self.a_undo.setEnabled(self.ctl.can_undo())
        self.a_redo.setEnabled(self.ctl.can_redo())

    def _update_tempo_label(self) -> None:
        tm = self.ctl.ws.tempo_map
        t = tm.effective_tempos()[0]
        ts = tm.effective_timesigs()[0]
        src = self.ctl.ws.source(self.ctl.ws.tempo_source_id or "")
        more = " (map)" if len(tm.tempos) > 1 or len(tm.timesigs) > 1 else ""
        self.tempo_label.setText(f"♩ {t.bpm:.4g} BPM  {ts.numerator}/{ts.denominator}{more}"
                                 f"  ·  {src.name if src else 'default'}   ")

    def _first_import_fit(self) -> None:
        has = bool(self.ctl.ws.tracks)
        if has and not self._had_tracks:
            QTimer.singleShot(0, self.timeline.zoom_to_fit)
        self._had_tracks = has

    # ------------------------------------------------------------------ import
    def open_files(self) -> None:
        start = self.settings.value("last_open_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, "Import MIDI", start,
                                                "MIDI files (*.mid *.midi *.smf *.kar);;All files (*)")
        if paths:
            self.settings.setValue("last_open_dir", os.path.dirname(paths[0]))
            self.import_paths(paths)

    def import_paths(self, paths: list[str]) -> None:
        payloads = []
        errors = []
        for p in paths:
            try:
                with open(p, "rb") as fh:
                    payloads.append(Payload(os.path.basename(p), fh.read(), path=p))
            except OSError as exc:
                errors.append(f"{os.path.basename(p)}: {exc.strerror}")
        errors += self.ctl.import_payloads(payloads)
        self._report_errors(errors)

    def _report_errors(self, errors: list[str]) -> None:
        if errors:
            QMessageBox.warning(self, "Some MIDI could not be imported", "\n".join(errors))

    # ------------------------------------------------------------------ drop placement
    def dragEnterEvent(self, e) -> None:
        mime = e.mimeData()
        if not (mime.hasUrls() or mime.formats()):
            return
        e.acceptProposedAction()
        self._drag_payloads, self._drag_diagnostics, self._drag_parsed = [], [], None
        if e.source() is None:
            # Read the payload now so the cursor can say which track names match.
            # Some apps only hand data over on drop; then names stay unknown.
            try:
                self._drag_payloads, self._drag_diagnostics = extract_payloads(mime)
                self._drag_parsed = self.ctl.parse_payloads(self._drag_payloads)[0] if self._drag_payloads else None
            except Exception:  # noqa: BLE001 - previewing must never break the drag
                self._drag_payloads, self._drag_parsed = [], None
        self.overlay.setGeometry(self.centralWidget().rect())
        self.overlay.show()
        self.overlay.raise_()
        self._update_drop_indicator(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction()
        self._update_drop_indicator(e)

    def dragLeaveEvent(self, _e) -> None:
        self.overlay.hide()
        self.timeline.set_drop_indicator(None)

    def drop_placement(self, pos: QPointF, bypass_snap: bool = False) -> tuple[Placement, int | None]:
        """Placement for a drop at a window position, plus the timeline lane it points at."""
        pt = pos.toPoint()
        vp = self.timeline.viewport()
        p_tl = vp.mapFrom(self, pt)
        if vp.rect().contains(p_tl):
            lane, t = self.timeline.drop_target(QPointF(p_tl), bypass_snap)
            if lane is not None and lane >= 0:
                return Placement(t, self.ctl.ws.tracks[lane].id), lane
            return Placement(t), None
        tp = self.track_panel
        p_tp = tp.mapFrom(self, pt)
        if tp.rect().contains(p_tp) and p_tp.y() >= HEADER_H:
            lane = self.timeline.lane_at(p_tp.y())
            if lane >= 0:
                return Placement(ZERO, self.ctl.ws.tracks[lane].id), lane
        return Placement(ZERO), None

    def _update_drop_indicator(self, e) -> None:
        if e.source() is not None:  # our own drag-out tile
            self.timeline.set_drop_indicator(None)
            return
        bypass = bool(e.modifiers() & Qt.ShiftModifier)
        pl, lane = self.drop_placement(e.position(), bypass)
        bbt = self.ctl.ws.tempo_map.format_bbt(pl.time)
        n_files = len(self._drag_payloads)
        many = f"{n_files} files" if n_files > 1 else ""
        if pl.target_track_id and self._drag_parsed is None:
            tgt = self.ctl.ws.track(pl.target_track_id)
            label = f"Onto “{tgt.name}” (and other tracks) at {bbt} if the names match, else new track(s)"
        else:
            plan = plan_drop(self.ctl.ws, self._drag_parsed or [], pl)
            if plan.matching:
                label = f"Onto {quoted(t.name for t in plan.onto())} at {bbt}"
                if plan.new_names:
                    label += f", {len(plan.new_names)} new track(s)"
            else:
                label = f"New track(s) at {bbt}" + (f": {plan.no_match}" if plan.no_match else "")
                lane = None
        if many:
            label += f"  ·  {many}"
        self.timeline.set_drop_indicator((lane, pl.time, label))

    def dropEvent(self, e) -> None:
        self.overlay.hide()
        self.timeline.set_drop_indicator(None)
        if e.source() is not None:  # our own drag-out tile
            return
        placement, _lane = self.drop_placement(e.position(), bool(e.modifiers() & Qt.ShiftModifier))
        payloads, diagnostics = self._drag_payloads, self._drag_diagnostics
        if not payloads:
            payloads, diagnostics = extract_payloads(e.mimeData())
        self._drag_payloads, self._drag_diagnostics, self._drag_parsed = [], [], None
        e.acceptProposedAction()
        if len(payloads) > 1:
            # Ask after the drop completes, so the source app isn't left waiting on a modal dialog.
            QTimer.singleShot(0, lambda: self._finish_drop(payloads, diagnostics, placement, ask=True))
        else:
            self._finish_drop(payloads, diagnostics, placement, ask=False)

    def _finish_drop(self, payloads: list[Payload], diagnostics: list[str], placement: Placement,
                     ask: bool) -> None:
        if ask:
            box = QMessageBox(self)
            box.setWindowTitle("Place dropped files")
            box.setText(f"{len(payloads)} files were dropped.")
            run = plan_drop(self.ctl.ws, self.ctl.parse_payloads(payloads)[0], Placement(end_to_end=True)).new_names
            if len(run) == 1:
                e2e = f"End to End joins them on one new track, “{run[0]}”, in the order dropped."
            else:
                shown = quoted(run, 4)
                e2e = (f"End to End lays them in the order dropped on {len(run)} new tracks ({shown}), "
                       "lining up each file's tracks by position.")
            box.setInformativeText(e2e + "\n\nAll at Cursor places each file at the cursor "
                                   "on its own track(s), matching track names as usual.")
            seq = box.addButton("End to End", QMessageBox.AcceptRole)
            same = box.addButton("All at Cursor", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(same)
            box.exec()
            if box.clickedButton() not in (seq, same):
                return
            placement.end_to_end = box.clickedButton() is seq
        errors = self.ctl.import_payloads(payloads, placement) if payloads else []
        if not payloads:
            errors += diagnostics
        elif diagnostics:
            self.statusBar().showMessage("  ·  ".join(diagnostics), 10000)
        self._report_errors(errors)

    # ------------------------------------------------------------------ export
    def save_midi(self, track_ids: list[str] | None = None) -> None:
        if not isinstance(track_ids, list):
            track_ids = None
        if not self.ctl.export_tracks(track_ids):
            self.statusBar().showMessage("No tracks to export (check the track and range toggles)", 6000)
            return
        try:
            results = self.ctl.build_exports(track_ids=track_ids)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        start_dir = self.settings.value("last_save_dir", os.path.expanduser("~"))
        default = os.path.join(start_dir, self.ctl.default_export_name(track_ids) + ".mid")
        title = "Save MIDI" if len(results) == 1 else f"Save {len(results)} MIDI files (range name is appended)"
        path, _ = QFileDialog.getSaveFileName(self, title, default, "MIDI files (*.mid)")
        if not path:
            return
        self.settings.setValue("last_save_dir", os.path.dirname(path))
        from ..core.export_smf import save_exports
        try:
            written = save_exports(results, path)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Saved {len(written)} file(s): " + ", ".join(os.path.basename(p) for p in written), 10000)

    # ------------------------------------------------------------------ track menu
    def track_menu(self, track_id: str, global_pos: QPoint) -> None:
        m = QMenu(self)
        if self._add_track_actions(m, track_id):
            m.exec(global_pos)

    def clip_menu(self, track_id: str, clip_id: str, global_pos: QPoint) -> None:
        ws = self.ctl.ws
        found = ws.find_clip(clip_id)
        if found is None:
            return
        track, clip = found
        m = QMenu(self)
        title = m.addAction(f"Clip: {clip.name or track.name}")
        title.setEnabled(False)
        m.addAction("Duplicate Clip (after it)", lambda: self.ctl.duplicate_clip(clip_id))
        a = m.addAction("Butt Against Previous Clip", lambda: self.ctl.snap_clip_to_previous(clip_id))
        a.setEnabled(any(c is not clip and c.start < clip.start for c in track.clips))
        if clip.is_trimmed:
            m.addAction("Restore Full Clip", lambda: self.ctl.restore_clip(clip_id))
        mv = m.addMenu("Move Clip to Track")
        for t in ws.tracks:
            if t.id != track.id:
                mv.addAction(t.name, lambda tid=t.id: self.ctl.move_clip_to_track(clip_id, tid))
        if len(ws.tracks) > 1:
            mv.addSeparator()
        mv.addAction("New Track", lambda: self.ctl.move_clip_to_track(clip_id, None))
        m.addAction("Delete Clip", lambda: self.ctl.delete_clip(clip_id))
        m.addSeparator()
        tm = m.addMenu(f"Track: {track.name}")
        self._add_track_actions(tm, track_id)
        m.exec(global_pos)

    def _add_track_actions(self, m: QMenu, track_id: str) -> bool:
        ws = self.ctl.ws
        t = ws.track(track_id)
        if t is None:
            return False
        idx = ws.tracks.index(t)
        m.addAction("Disable" if t.enabled else "Enable",
                    lambda: self.ctl.set_track_enabled(track_id, not t.enabled))
        m.addAction("Rename", lambda: self.track_panel.header(track_id) and self.track_panel.header(track_id).focus_name())
        if self.ctl.is_soloed(track_id):
            m.addAction("Unsolo (Restore Track Selection)", self.ctl.unsolo)
        else:
            m.addAction("Solo for Export", lambda: self.ctl.solo_track(track_id))
        m.addSeparator()
        a = m.addAction("Move Up", lambda: self.ctl.move_track(track_id, idx - 1))
        a.setEnabled(idx > 0)
        a = m.addAction("Move Down", lambda: self.ctl.move_track(track_id, idx + 1))
        a.setEnabled(idx < len(ws.tracks) - 1)
        mg = m.addMenu("Merge Into")
        for o in ws.tracks:
            if o.id != track_id:
                mg.addAction(o.name, lambda oid=o.id: self.ctl.merge_tracks(track_id, oid))
        mg.setEnabled(len(ws.tracks) > 1)
        m.addSeparator()
        m.addAction("Save This Track…", lambda: self.save_midi([track_id]))
        m.addAction("Source Info…", lambda: self._source_info(track_id))
        m.addSeparator()
        m.addAction("Remove Track", lambda: self.ctl.remove_track(track_id))
        return True

    def _source_info(self, track_id: str) -> None:
        t = self.ctl.ws.track(track_id)
        if t is None:
            return
        from .source_info import SourceInfoDialog
        SourceInfoDialog(self.ctl.ws, t, self).exec()
