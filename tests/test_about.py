"""About box: toolbar button, dialog content, icon loader and the single version source."""
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QSizePolicy, QToolBar  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    from midi_interchange.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    QTest.qWaitForWindowExposed(w)
    yield w
    w.close()


def test_about_is_last_toolbar_item_after_expanding_spacer(win):
    tb = win.findChild(QToolBar)
    acts = tb.actions()
    assert acts[-1] is win.a_about
    spacer = tb.widgetForAction(acts[-2])
    assert spacer.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert all(a is not win.a_about for m in win.menuBar().actions() if m.menu() for a in m.menu().actions())
    btn = tb.widgetForAction(win.a_about)
    assert btn.geometry().right() >= tb.width() - 30


def test_about_button_opens_dialog(win, monkeypatch):
    from midi_interchange.ui import main_window
    shown = []
    monkeypatch.setattr(main_window.AboutDialog, "exec", lambda self: shown.append(self))
    win.a_about.trigger()
    assert len(shown) == 1


def test_dialog_content(app):
    from midi_interchange import __version__
    from midi_interchange.ui.about_dialog import AboutDialog, REPO_URL
    d = AboutDialog()
    assert d.name_label.text() == "MIDI Interchange"
    assert d.version_label.text() == f"Version {__version__}"
    assert d.copyright_label.text() == "© 2026 Andy Buchanan"
    assert REPO_URL == "https://github.com/AndyJBuchanan/MIDI-Interchange"
    assert f'href="{REPO_URL}"' in d.link_label.text()
    assert d.link_label.openExternalLinks()
    assert d.description_label.text().startswith("A MIDI palette for moving MIDI between apps:")
    assert d.isModal()
    assert not d.icon_label.pixmap().isNull()


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_about_icon_loads(app, monkeypatch, frozen, platform):
    from midi_interchange.ui import app_icon
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    assert not app_icon.about_icon().isNull()
    assert app_icon.about_icon_path().endswith("app_icon_mac.png" if platform == "darwin" else "app_icon.png")


def test_version_is_digits_and_read_by_build_files():
    from midi_interchange import __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    spec = (ROOT / "midi_interchange.spec").read_text(encoding="utf-8")
    assert "from midi_interchange import __version__ as VERSION" in spec
    assert not re.search(r'(?m)^VERSION\s*=\s*"', spec)
    ps1 = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    m = re.search(r"-notmatch '([^']*__version__[^']*)'", ps1)
    assert m and "__init__.py" in ps1
    pattern = m.group(1).replace("\\s", r"\s")
    init = (ROOT / "midi_interchange" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(pattern, init)
    assert found and found.group(1) == __version__
