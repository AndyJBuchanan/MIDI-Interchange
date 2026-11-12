"""The app's icon for its windows (files made by tools/make_icons.py)."""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon, QPixmap

RES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources")


def icon_path() -> str | None:
    """The PNG to use as the window icon, or None where the bundle's own icon should show.

    The packaged macOS app takes its Dock icon from the .icns in the bundle, so nothing is set.
    Run from source on macOS, the Dock shows the macOS-grid version instead of Python's icon.
    """
    if sys.platform == "darwin":
        return None if getattr(sys, "frozen", False) else os.path.join(RES_DIR, "app_icon_mac.png")
    return os.path.join(RES_DIR, "app_icon.png")


def about_icon_path() -> str:
    """The PNG shown in the About box: the macOS-grid version on macOS, the full one elsewhere.

    Unlike icon_path(), this also works in the packaged Mac app, where the PNGs are bundled as data files.
    """
    return os.path.join(RES_DIR, "app_icon_mac.png" if sys.platform == "darwin" else "app_icon.png")


def about_icon() -> QPixmap:
    """The About box image (null if the file is missing)."""
    return QPixmap(about_icon_path())


def app_icon() -> QIcon | None:
    path = icon_path()
    return QIcon(path) if path and os.path.isfile(path) else None
