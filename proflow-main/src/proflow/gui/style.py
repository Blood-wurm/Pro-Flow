"""One visual style for the desktop UI: palette, fonts and the Qt stylesheet.

Plot colours and the report's HTML colours come from the same palette.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Segoe UI"
ASSETS = Path(__file__).resolve().parent / "assets"

INK = "#1f2933"
MUTED = "#52606d"
FAINT = "#9aa5b1"
RULE = "#d9e2ec"
PANEL = "#f4f6f9"
CARD = "#ffffff"
ACCENT = "#1f5fbf"
ACCENT_SOFT = "#e8f0fc"
WARN = "#b45309"
WARN_SOFT = "#fff4e5"
OK = "#2f7d4f"
OK_SOFT = "#e6f4ea"
ERROR = "#b42318"
ERROR_SOFT = "#fdecea"

WATER = QColor(80, 150, 230, 90)
WATER_LINE = QColor("#1f5fbf")
GROUND = QColor("#4a4f57")
EGL = QColor("#2f7d4f")
CRITICAL = QColor("#c2410c")

CHEVRON = (ASSETS / "chevron-down.svg").as_posix()

STYLESHEET = f"""
QWidget {{ color: {INK}; }}
QMainWindow, QWidget#page {{ background: {PANEL}; }}
QFrame#sidebar {{ background: {CARD}; border-right: 1px solid {RULE}; }}
QLabel#appName {{ font-size: 13pt; font-weight: 700; color: {ACCENT}; }}
QLabel#navGroup {{ color: {FAINT}; font-size: 8pt; font-weight: 600;
                  letter-spacing: 1px; padding: 6px 4px 2px 4px; }}
QPushButton#nav {{ text-align: left; border: 0; border-radius: 6px;
                  padding: 7px 10px; background: transparent; color: {MUTED}; }}
QPushButton#nav:hover {{ background: {PANEL}; color: {INK}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {ACCENT};
                          font-weight: 600; }}
QTabWidget#plotTabs QTabBar::tab {{ padding: 4px 12px; }}
QFrame#card {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 8px; }}
QLabel#cardTitle {{ font-weight: 600; color: {INK}; padding-bottom: 2px; }}
QLabel#screenTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#chipWarn {{ background: {WARN_SOFT}; color: {WARN}; border-radius: 10px;
                  padding: 3px 10px; font-weight: 600; }}
QLabel#chipInfo {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-radius: 10px;
                  padding: 3px 10px; }}
QLabel#statusOk {{ background: {OK_SOFT}; color: {OK}; border-radius: 6px; padding: 6px 10px; }}
QLabel#statusWarn {{ background: {WARN_SOFT}; color: {WARN}; border-radius: 6px; padding: 6px 10px; }}
QLabel#statusError {{ background: {ERROR_SOFT}; color: {ERROR}; border-radius: 6px;
                     padding: 6px 10px; }}
QLabel#valueLabel {{ color: {MUTED}; }}
QLabel#value {{ font-weight: 600; }}
QLabel#unit {{ color: {MUTED}; }}
QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{
    background: {CARD}; border: 1px solid {RULE}; border-radius: 5px; padding: 3px 6px;
    min-height: 22px;
}}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox::down-arrow {{ image: url({CHEVRON}); width: 12px; height: 12px; }}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}
QDoubleSpinBox:disabled, QSpinBox:disabled {{ color: {FAINT}; background: {PANEL}; }}
/* Hide spin arrows here: Qt 6.12 hides the text of a styled spin box set to
   NoButtons. */
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: 0; }}
QPushButton {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 5px;
              padding: 5px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; padding: 7px 16px; color: {MUTED};
               border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QTableWidget {{ background: {CARD}; border: 0; gridline-color: {RULE}; }}
QHeaderView::section {{ background: {CARD}; border: 0; border-bottom: 1px solid {RULE};
                       padding: 4px 6px; color: {MUTED}; }}
QTextBrowser {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 8px; }}
"""


def _light_palette() -> QPalette:
    """Fixed light palette, so the OS dark/light theme does not leak in."""
    pal = QPalette()
    roles = {
        QPalette.Window: PANEL,
        QPalette.WindowText: INK,
        QPalette.Base: CARD,
        QPalette.AlternateBase: PANEL,
        QPalette.Text: INK,
        QPalette.Button: CARD,
        QPalette.ButtonText: INK,
        QPalette.ToolTipBase: CARD,
        QPalette.ToolTipText: INK,
        QPalette.PlaceholderText: FAINT,
        QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: "#ffffff",
        QPalette.Link: ACCENT,
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(FAINT))
    return pal


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_light_palette())
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(9.5)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
