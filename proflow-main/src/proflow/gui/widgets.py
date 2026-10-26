"""Small building blocks shared by the calculator panels."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QLabel, QSpinBox, QVBoxLayout

STATUS_TEXT = {
    "invalid_input": "invalid input",
    "unsupported_regime": "outside the supported range",
    "no_convergence": "no convergence",
}


def card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    if title:
        layout.addWidget(QLabel(title, objectName="cardTitle"))
    return frame, layout


def number(
    suffix: str, decimals: int, maximum: float, minimum: float = 0.0
) -> QDoubleSpinBox:
    """A right-aligned number field with its unit shown as a suffix."""
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSuffix(f"  {suffix}" if suffix else "")
    box.setAlignment(Qt.AlignRight)
    box.setKeyboardTracking(False)
    return box


def increments() -> QSpinBox:
    box = QSpinBox()
    box.setRange(1, 50)  # Express allows up to 50 increments
    box.setAlignment(Qt.AlignRight)
    return box
