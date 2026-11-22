"""The timeline's application-wide event filter lives only while the timeline is shown (headless)."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_ui_assembly import app, win  # noqa: E402,F401


def reaches_the_filter(tl) -> bool:
    """Deactivate the window: the timeline's application filter, if installed, forgets the pointer."""
    tl._pointer = QPointF(5, 5)
    QApplication.sendEvent(tl.window(), QEvent(QEvent.WindowDeactivate))
    return tl._pointer is None


def test_a_shown_timeline_filters_application_events(win):
    assert reaches_the_filter(win.timeline)


def test_a_closed_window_leaves_no_filter_behind(win):
    win.close()
    QApplication.processEvents()
    assert not reaches_the_filter(win.timeline)


def test_showing_the_window_again_restores_the_filter(win):
    win.close()
    win.show()
    QApplication.processEvents()
    assert reaches_the_filter(win.timeline)
