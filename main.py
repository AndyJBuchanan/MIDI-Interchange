"""MIDI Interchange entry point: python main.py [files...]"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from midi_interchange.interchange.drag_export import prune_old
from midi_interchange.ui import theme
from midi_interchange.ui.app_icon import app_icon
from midi_interchange.ui.main_window import APP_NAME, MainWindow
from midi_interchange.single_instance import SingleInstance, InstanceError
from midi_interchange.ui.session import SessionLifecycle


class _FileOpenFilter(QObject):
    """macOS: files dropped on the Dock icon / 'Open With' arrive as FileOpen events."""

    def __init__(self) -> None:
        super().__init__()
        self.pending = []
        self.handler = None

    def eventFilter(self, obj, e) -> bool:
        if e.type() == QEvent.FileOpen:
            if self.handler:
                self.handler([e.file()])
            else:
                self.pending.append(e.file())
            return True
        return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    filt = _FileOpenFilter()
    app.installEventFilter(filt)
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    instance = None
    try:
        instance = SingleInstance(directory)
        primary = instance.acquire()
        app.processEvents()  # collect early macOS FileOpen events
        files = [os.path.abspath(a) for a in sys.argv[1:] if os.path.isfile(a)]
        files.extend(filt.pending)
        filt.pending.clear()
        if not primary:
            instance.handoff(files)
            return 0
    except (OSError, InstanceError) as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        if instance:
            instance.close()
        return 1
    filt.handler = instance.enqueue
    theme.apply(app)
    icon = app_icon()
    if icon:
        app.setWindowIcon(icon)
    prune_old()
    win = MainWindow()
    lifecycle = SessionLifecycle(app, win, directory, instance=instance)

    def receive(paths):
        lifecycle.note_activity()
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()
        if paths:
            win.import_paths(paths)

    win.show()
    if files:
        instance.enqueue(files)
    QTimer.singleShot(0, lambda: lifecycle.start(lambda: instance.set_handler(receive)))
    try:
        return app.exec()
    finally:
        lifecycle.stop()
        instance.close()


if __name__ == "__main__":
    sys.exit(main())
