import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Tests never touch the real user settings: QSettings falls back to an INI file in a temp dir.
import tempfile  # noqa: E402

from PySide6.QtCore import QSettings  # noqa: E402

_SETTINGS_DIR = tempfile.mkdtemp(prefix="midi-interchange-test-settings-")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _SETTINGS_DIR)
