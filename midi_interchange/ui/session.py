"""Application-owned session lifecycle; ordinary MainWindow tests have no disk IO."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.export_smf import ExportMode
from ..core.session import Session, SessionStore, boolean, integer, number, require
from .controller import SNAP_CHOICES
from .timeline import MAX_PPB, MIN_PPB

PERSISTENCE_SETTING = 'session_persistence_enabled'
SAVE_INTERVAL = 120
IDLE_INTERVAL = 15
INPUT_EVENTS = {
    QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
    QEvent.MouseButtonDblClick, QEvent.KeyPress, QEvent.KeyRelease,
    QEvent.Wheel, QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd,
    QEvent.NativeGesture, QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop,
    QEvent.FileOpen,
}


def capture(window) -> Session:
    ctl, tl = window.ctl, window.timeline
    return Session(ctl.ws.snapshot(), {
        'export_mode': ctl.export_mode.value, 'trim': ctl.trim,
        'snap': ctl.snap, 'selected_range_id': ctl.selected_range_id,
        'zoom': tl.ppb, 'lane_height': tl.lane_h,
        'horizontal_scroll': tl.horizontalScrollBar().value(),
        'vertical_scroll': tl.verticalScrollBar().value(),
    })


def validate_settings(session: Session):
    s = session.settings
    require(set(s) == {'export_mode', 'trim', 'snap', 'selected_range_id', 'zoom',
                       'lane_height', 'horizontal_scroll', 'vertical_scroll'}, 'Invalid settings fields')
    ExportMode(s['export_mode'])
    boolean(s['trim'])
    require(any(type(s['snap']) is type(v) and s['snap'] == v for _, v in SNAP_CHOICES), 'Invalid snap setting')
    require(s['selected_range_id'] is None or
            any(s['selected_range_id'] == r.id for r in session.workspace['ranges']), 'Missing selected range')
    number(s['zoom'], MIN_PPB, MAX_PPB)
    integer(s['lane_height'], 28, 220)
    integer(s['horizontal_scroll'], 0, 2**31 - 1)
    integer(s['vertical_scroll'], 0, 2**31 - 1)


def apply_session(window, session: Session):
    """Use normal model refresh and UI setters; suppress first-import zoom-to-fit."""
    validate_settings(session)
    ctl, tl, s = window.ctl, window.timeline, session.settings
    window._had_tracks = bool(session.workspace['tracks'])
    ctl.restore_session(session.workspace, s['selected_range_id'])
    ctl.set_export_mode(ExportMode(s['export_mode']))
    ctl.set_trim(s['trim'])
    window.snap_combo.setCurrentIndex(next(i for i, (_, v) in enumerate(SNAP_CHOICES) if v == s['snap']))
    tl.set_lane_height(s['lane_height'])
    tl.set_zoom(s['zoom'])
    tl.horizontalScrollBar().setValue(s['horizontal_scroll'])
    tl.verticalScrollBar().setValue(s['vertical_scroll'])


class SessionLifecycle(QObject):
    def __init__(self, app, window, directory, *, clock=time.monotonic, instance=None,
                 notice=None, close_failure=None):
        super().__init__(window)
        self.app, self.window, self.instance = app, window, instance
        self.store = SessionStore(directory)
        self.clock = clock
        self.enabled = window.settings.value(PERSISTENCE_SETTING, True, type=bool)
        self.notice = notice or (lambda message: QMessageBox.warning(window, 'Session recovery', message))
        self.close_failure = close_failure or self._close_failure_dialog
        self.generation = 0
        self.saved_generation = 0
        self.last_saved = self.last_input = clock()
        self.retry_after = 0
        self.restoring = True
        self.closing = self.allow_close = False
        self.close_deferred = False
        self._future = None
        self._saving_generation = 0
        self._saving_final = False
        self._save_warning = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='session') if self.enabled else None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.tick)
        self._defaults = capture(window)
        if self.enabled:
            ctl, tl = window.ctl, window.timeline
            for signal in (ctl.tracksChanged, ctl.rangesChanged, ctl.selectionChanged,
                           ctl.tempoChanged, ctl.exportSettingsChanged,
                           window.snap_combo.currentIndexChanged, tl.zoomChanged,
                           tl.laneHeightChanged, tl.horizontalScrollBar().valueChanged,
                           tl.verticalScrollBar().valueChanged):
                signal.connect(self.mark_dirty)
        app.installEventFilter(self)

    def start(self, ready=lambda: None):
        """Called after show/layout, before queued imports are released."""
        restored = None
        self._unclean = False
        self._restored = False
        self._rejection = None  # (error, detail) when a saved session was rejected
        self._tracking_error = None
        if self.enabled:
            self.store.purge_rejected()  # leftovers from earlier runs only
            try:
                restored = self.store.load()
                if restored:
                    apply_session(self.window, restored)
                    self._restored = True
            except Exception as exc:  # session data/IO must never terminate startup
                self._recover(exc)
                restored = None
            try:
                self._unclean = self.store.begin_run()
            except OSError as exc:
                self._tracking_error = exc

        def finish():
            # Layout/scrollbar ranges settle after refresh. Keep this inside the
            # same recovery boundary, before imports or the first checkpoint.
            if restored and self._restored:
                try:
                    s, tl = restored.settings, self.window.timeline
                    tl.horizontalScrollBar().setValue(s['horizontal_scroll'])
                    tl.verticalScrollBar().setValue(s['vertical_scroll'])
                except Exception as exc:
                    self._recover(exc)
            self.restoring = False
            self.last_input = self.last_saved = self.clock()
            if self.enabled:
                self.mark_dirty()  # also save a first-run empty workspace on exit
            self._timer.start()  # also releases a close deferred during restore
            ready()
            message = self.startup_message()
            if message:
                self.notice(message)
        QTimer.singleShot(0, finish)

    def startup_message(self):
        """One notice matching what actually happened at startup; never claims a restore that didn't."""
        parts = []
        if self._rejection:
            error, detail = self._rejection
            lead = ('The previous run did not close cleanly, and the saved session could not be restored. '
                    if self._unclean else 'The saved session could not be restored. ')
            parts.append(f'{lead}The app started with an empty workspace. '
                         f'The rejected file is kept until the app quits.\n{error}{detail}')
        elif self._unclean and self._restored:
            parts.append('The previous run did not close cleanly. The last saved checkpoint was restored; '
                         'more recent changes may have been lost.')
        if self._tracking_error:
            parts.append(f'Session recovery tracking could not be started: {self._tracking_error}')
        return '\n\n'.join(parts)

    def _recover(self, error):
        # Set before moving: if preservation fails, later saves must retry it,
        # never overwrite the rejected file.
        self.store.rejected = True
        try:
            path = self.store.preserve_rejected()
            self.store.rejected = False
            detail = f'\nPreserved at: {path}' if path else ''
        except OSError as exc:
            detail = f'\nThe original file is untouched; saving must wait until it can be preserved: {exc}'
        apply_session(self.window, self._defaults)
        self._restored = False
        self._rejection = (error, detail)

    def mark_dirty(self, *_):
        if self.enabled and not self.restoring:
            self.generation += 1

    def note_activity(self):
        self.last_input = self.clock()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in INPUT_EVENTS:
            self.note_activity()
        if obj is self.app and kind == QEvent.Quit and self.enabled and not self.allow_close:
            self.window.close()
            return True
        if obj is self.window and kind == QEvent.Close and not self.allow_close:
            if self.close_blocked():
                # Remember the request; tick() runs the normal close once not busy.
                event.ignore()
                if not self.close_deferred:
                    self.close_deferred = True
                    self.window.statusBar().showMessage('Closing when the current operation finishes\u2026')
                return True
            if self.enabled:
                event.ignore()
                self.request_close()
                return True
        return False

    def close_blocked(self):
        return bool(self.restoring or self.window.timeline.gesture_active or self.window.ctl.file_drag_active
                    or (self.instance and self.instance.has_pending))

    @staticmethod
    def dialog_open():
        # Only the deferred release waits for dialogs; a fresh close request and the
        # close-failure dialog (opened while closing) are unaffected.
        return QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None

    def busy(self):
        return (self.window.timeline.gesture_active
                or self.window.ctl.file_drag_active
                or QApplication.mouseButtons() != Qt.NoButton
                or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None)

    def tick(self):
        if self._future and self._future.done():
            self._complete_save()
        if (self.close_deferred and not self.closing and not self.close_blocked()
                and not self.dialog_open()):
            self.close_deferred = False
            self.window.close()  # normal close path, including the final save
            return
        if self.closing or self.restoring or not self.enabled or self._future:
            return
        now = self.clock()
        if self.busy():
            self.last_input = now  # full inactivity interval after a dialog/gesture
            return
        if (self.generation != self.saved_generation
                and now >= self.retry_after
                and now - self.last_saved >= SAVE_INTERVAL
                and now - self.last_input >= IDLE_INTERVAL):
            self._submit()

    def _submit(self, *, final=False):
        self._saving_generation = self.generation
        self._saving_final = final
        try:
            snapshot = capture(self.window)
            self._future = self._executor.submit(self.store.save, snapshot)
        except Exception as exc:
            self._save_failed(exc)

    def _complete_save(self):
        future, self._future = self._future, None
        try:
            future.result()
        except Exception as exc:
            self._save_failed(exc)
            return
        self.saved_generation = self._saving_generation
        self.last_saved = self.clock()
        self._save_warning = False
        if self._saving_final:
            self._finish_close()
        elif self.closing:
            self._submit(final=True)

    def _save_failed(self, exc):
        if self.closing:
            self.window.setEnabled(True)
            choice = self.close_failure(str(exc))
            if choice == 'retry':
                self.window.setEnabled(False)
                self._submit(final=True)
            elif choice == 'discard':
                # Retain the running marker: next launch warns of unsaved work.
                self._finish_close(clean=False)
            else:
                self.closing = False
                if self.instance:
                    self.instance.closing = False
                self.last_input = self.clock()
        else:
            # Retry after another interval, without repeatedly interrupting work.
            self.retry_after = self.clock() + SAVE_INTERVAL
            if not self._save_warning:
                self.window.statusBar().showMessage(f'Session could not be saved: {exc}', 15000)
                self._save_warning = True

    def request_close(self):
        if self.closing:
            return
        focus = self.window.focusWidget()
        if focus:
            focus.clearFocus()  # commit any pending text edit through its normal slot
        self.closing = True
        if self.instance:
            self.instance.closing = True
        self.window.setEnabled(False)
        if self._future is None:
            self._submit(final=True)

    def _finish_close(self, *, clean=True):
        if clean:
            try:
                self.store.end_run()
            except OSError as exc:
                self._save_failed(exc)
                return
            self.store.purge_rejected(current_run_only=True)  # failures ignored
        self.allow_close = True
        self._timer.stop()
        self.window.setEnabled(True)
        self.window.close()

    def _close_failure_dialog(self, error):
        box = QMessageBox(self.window)
        box.setWindowTitle('Session could not be saved')
        box.setText(error)
        retry = box.addButton('Retry', QMessageBox.AcceptRole)
        discard = box.addButton('Exit without saving', QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(retry)
        box.exec()
        return 'retry' if box.clickedButton() is retry else 'discard' if box.clickedButton() is discard else 'cancel'

    def stop(self):
        """Release resources after the event loop, or during isolated test cleanup."""
        self._timer.stop()
        self.app.removeEventFilter(self)
        if self._executor:
            self._executor.shutdown(wait=True)
