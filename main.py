"""MIDI Interchange entry point: python main.py [files...]"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from midi_interchange.interchange.drag_export import prune_old
from midi_interchange.ui import theme
from midi_interchange.ui.app_icon import app_icon
from midi_interchange.ui.main_window import APP_NAME, MainWindow


class _FileOpenFilter(QObject):
    """macOS: files dropped on the Dock icon / 'Open With' arrive as FileOpen events."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window

    def eventFilter(self, obj, e) -> bool:
        if e.type() == QEvent.FileOpen:
            self.window.import_paths([e.file()])
            return True
        return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    theme.apply(app)
    icon = app_icon()
    if icon:
        app.setWindowIcon(icon)
    prune_old()
    win = MainWindow()
    filt = _FileOpenFilter(win)
    app.installEventFilter(filt)
    win.show()
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        win.import_paths(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
