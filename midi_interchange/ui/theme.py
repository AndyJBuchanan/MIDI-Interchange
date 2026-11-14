"""Colours and application palette (dark, consistent on macOS and Windows)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = QColor("#1b1c1f")
LANE_A = QColor("#202125")
LANE_B = QColor("#24252a")
LANE_SEP = QColor("#121315")
GRID_BAR = QColor("#3b3e46")
GRID_BEAT = QColor("#2c2e34")
GRID_SUB = QColor("#26282d")
RULER_BG = QColor("#2a2c31")
INFO_BG = QColor("#25272b")
RANGE_STRIP_BG = QColor("#1f2024")
TEXT = QColor("#d5d8de")
TEXT_DIM = QColor("#8a8f99")
TEXT_FAINT = QColor("#5b606a")
ACCENT = QColor("#f2b134")
SOLO = QColor("#ff6e6e")
RANGE_EDGE = QColor("#8a7a52")
RANGE_FILL = QColor(242, 177, 52, 9)
RANGE_FILL_SEL = QColor(242, 177, 52, 20)
RANGE_BODY = QColor(242, 177, 52, 50)
RANGE_BODY_SEL = QColor(242, 177, 52, 110)
RANGE_TOGGLE = QColor(242, 177, 52, 150)        # toggles of an unselected range
EXCLUDED_FILL = QColor(20, 21, 24, 150)         # lane section a range excludes
EXCLUDED_HATCH = QColor(120, 112, 90, 110)
DISABLED = QColor("#5a5d64")
LYRIC = QColor("#e7e7a0")
TEMPO_COL = QColor("#7fc7ff")
TS_COL = QColor("#b9a6ff")
HOVER_LINE = QColor(255, 255, 255, 90)
PANEL_BG = QColor("#26282c")
DROP_OVERLAY = QColor(242, 177, 52, 40)
DROP_LANE_FILL = QColor(242, 177, 52, 28)
DROP_NEW_FILL = QColor(242, 177, 52, 18)
DROP_LABEL_BG = QColor(20, 21, 24, 225)
OVERLAP_FILL = QColor(255, 96, 96, 38)
OVERLAP_EDGE = QColor(255, 110, 110, 200)


def _luminance(c: QColor) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on_info(color: QColor) -> QColor:
    """A track colour as drawn on the header's info rows: unchanged if it reads well on
    INFO_BG, otherwise lightened until it does (black and the darker presets)."""
    c = QColor(color)
    h, s, l, _a = c.getHslF()
    h = max(h, 0.0)                      # greys have no hue
    while _contrast(c, INFO_BG) < 4.5 and l < 1.0:
        l = min(l + 0.04, 1.0)
        c.setHslF(h, s, l)
    return c


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#2b2d31"))
    pal.setColor(QPalette.WindowText, TEXT)
    pal.setColor(QPalette.Base, QColor("#1e1f23"))
    pal.setColor(QPalette.AlternateBase, QColor("#26282c"))
    pal.setColor(QPalette.Text, TEXT)
    pal.setColor(QPalette.Button, QColor("#34363c"))
    pal.setColor(QPalette.ButtonText, TEXT)
    pal.setColor(QPalette.Highlight, QColor("#b5831f"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#34363c"))
    pal.setColor(QPalette.ToolTipText, TEXT)
    pal.setColor(QPalette.PlaceholderText, TEXT_FAINT)
    pal.setColor(QPalette.Disabled, QPalette.Text, TEXT_FAINT)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, TEXT_FAINT)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, TEXT_FAINT)
    app.setPalette(pal)
