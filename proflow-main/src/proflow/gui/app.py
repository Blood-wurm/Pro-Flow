"""Pro-Flow desktop application shell.

Run: proflow-gui, or python -m proflow.gui
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from proflow import __version__
from proflow.gui import style
from proflow.gui.channel_panel import ChannelPanel
from proflow.gui.panel import CalculatorPanel
from proflow.gui.weir_panel import WeirPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pro-Flow")
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.panels: dict[str, CalculatorPanel] = {
            "Channel": ChannelPanel(),
            "Weir": WeirPanel(),
        }
        layout.addWidget(self._sidebar())
        for panel in self.panels.values():
            self.pages.addWidget(panel)
        layout.addWidget(self.pages, 1)
        self.show_panel("Channel")

        available = self.screen().availableGeometry()
        self.resize(
            min(1480, int(available.width() * 0.92)),
            min(880, int(available.height() * 0.9)),
        )

    def _sidebar(self) -> QFrame:
        bar = QFrame(objectName="sidebar")
        bar.setFixedWidth(176)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)
        layout.addWidget(QLabel("Pro-Flow", objectName="appName"))
        layout.addSpacing(14)
        layout.addWidget(QLabel("EXPRESS", objectName="navGroup"))
        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for name in self.panels:
            button = QPushButton(name, objectName="nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, n=name: self.show_panel(n))
            self.nav.addButton(button)
            self.nav_buttons[name] = button
            layout.addWidget(button)
        layout.addStretch(1)
        footer = QLabel(f"v{__version__} · experimental", objectName="muted")
        layout.addWidget(footer)
        return bar

    def show_panel(self, name: str) -> None:
        self.pages.setCurrentWidget(self.panels[name])
        self.nav_buttons[name].setChecked(True)
        self.setWindowTitle(f"Pro-Flow · Express · {name}")

    @property
    def current(self) -> CalculatorPanel:
        return self.pages.currentWidget()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    style.apply(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
