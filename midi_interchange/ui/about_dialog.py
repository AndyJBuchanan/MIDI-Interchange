"""The About box: icon, name, version, description, copyright, GitHub link and OK."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from .. import __version__
from .app_icon import about_icon

APP_NAME = "MIDI Interchange"
DESCRIPTION = ("A MIDI palette for moving MIDI between apps: drag in or import MIDI from one or more apps, "
               "pick the tracks and ranges you want, and drag them out or export to another.")
COPYRIGHT = "© 2026 Andy Buchanan"
REPO_URL = "https://github.com/AndyJBuchanan/MIDI-Interchange"
REPO_TEXT = "github.com/AndyJBuchanan/MIDI-Interchange"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setModal(True)

        self.icon_label = QLabel()
        pm = about_icon()
        if not pm.isNull():
            self.icon_label.setPixmap(pm.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignCenter)

        self.name_label = QLabel(APP_NAME)
        f = self.name_label.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.5)
        self.name_label.setFont(f)
        self.name_label.setAlignment(Qt.AlignCenter)

        self.version_label = QLabel(f"Version {__version__}")
        self.version_label.setAlignment(Qt.AlignCenter)

        self.description_label = QLabel(DESCRIPTION)
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignCenter)

        self.copyright_label = QLabel(COPYRIGHT)
        self.copyright_label.setAlignment(Qt.AlignCenter)

        self.link_label = QLabel(f'<a href="{REPO_URL}">{REPO_TEXT}</a>')
        self.link_label.setTextFormat(Qt.RichText)
        self.link_label.setOpenExternalLinks(True)
        self.link_label.setAlignment(Qt.AlignCenter)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.button(QDialogButtonBox.Ok).setDefault(True)

        lay = QVBoxLayout(self)
        for w in (self.icon_label, self.name_label, self.version_label, self.description_label,
                  self.copyright_label, self.link_label):
            lay.addWidget(w)
        lay.addWidget(self.buttons)
        self.setFixedWidth(380)
        self.layout().setSizeConstraint(QVBoxLayout.SetFixedSize)
