"""Express weir calculator panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QWidget,
)

from proflow.engine.weir import DEFAULT_CW
from proflow.gui.panel import CalculatorPanel
from proflow.gui.widgets import increments, number
from proflow.model.express import (
    BROAD_CREST_TYPES,
    COMPUTE_BY,
    COMPUTE_LABELS,
    CW_OVERRIDE_TYPES,
    WEIR_DEPTH_LABEL,
    WEIR_LABELS,
    WEIR_TYPES,
    Calculation,
    WeirInputs,
    calculate_weir,
)

# The published Express case "Forebay @ DP 4.3 Notch" (fixtures/public).
WEIR_EXAMPLE = WeirInputs(
    title="Forebay @ DP 4.3 Notch",
    crest="sharp",
    bottom_length=0.90,
    total_depth=1.50,
    compute_by="known_q",
    known_q=5.25,
)

# Which form rows each weir type uses.
_ROWS = {
    "bottom_length": ("rectangular", "compound", "trapezoidal", "proportional"),
    "notch_length": ("compound",),
    "notch_depth": ("compound", "proportional"),
    "diameter": ("circular",),
    "angle": ("v_notch",),
    "side_slope": ("trapezoidal",),
    "cw": CW_OVERRIDE_TYPES,
}


class WeirPanel(CalculatorPanel):
    KIND = "weir"
    TITLE = "Weir"
    SUBTITLE = "Express · weirs, equations as printed in the Express manual"
    SECTION_TAB = "Weir section"
    INPUT_NOTE = (
        "Rectangular, compound and circular weirs take Cw (3.33 sharp, 2.6 broad); "
        "the others use the manual's own coefficients."
    )

    def __init__(self, inputs: WeirInputs = WEIR_EXAMPLE) -> None:
        super().__init__()
        self.load(inputs)

    def build_form(self, form: QFormLayout) -> None:
        self.form = form
        self.title = QLineEdit()
        self.weir_type = QComboBox()
        for t in WEIR_TYPES:
            self.weir_type.addItem(WEIR_LABELS[t], t)
        self.crest = QComboBox()
        for c in DEFAULT_CW:
            self.crest.addItem(c.capitalize(), c)
        self.bottom_length = number("ft", 2, 1e4)
        self.bottom_length_label = QLabel("Bottom length")
        self.notch_length = number("ft", 2, 1e4)
        self.notch_depth = number("ft", 2, 1e3)
        self.diameter = number("ft", 2, 100.0)
        self.angle = number("deg", 1, 120.0)
        self.side_slope = number("H:1V", 2, 4.0)
        self.total_depth = number("ft", 2, 1e3)
        self.cw = number("", 2, 10.0)
        self.cw_default = QCheckBox("Express default")
        self.cw_row = QWidget()
        cw_layout = QHBoxLayout(self.cw_row)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.addWidget(self.cw, 1)
        cw_layout.addWidget(self.cw_default)
        self.compute_by = QComboBox()
        for m in COMPUTE_BY:
            self.compute_by.addItem(COMPUTE_LABELS[m], m)
        self.known_q = number("cfs", 2, 1e7)
        self.known_depth = number("ft", 3, 1e3)
        self.increments = increments()
        self.mode_value = QStackedWidget()
        for w in (self.known_q, self.known_depth, self.increments):
            self.mode_value.addWidget(w)
        self.mode_label = QLabel()
        depths = QLabel("Exact", objectName="muted")
        depths.setToolTip(WEIR_DEPTH_LABEL)
        self._row_widgets = {
            "bottom_length": self.bottom_length,
            "notch_length": self.notch_length,
            "notch_depth": self.notch_depth,
            "diameter": self.diameter,
            "angle": self.angle,
            "side_slope": self.side_slope,
            "cw": self.cw_row,
        }
        form.addRow("Title", self.title)
        form.addRow("Weir type", self.weir_type)
        form.addRow("Crest", self.crest)
        form.addRow(self.bottom_length_label, self.bottom_length)
        for label, widget in (
            ("Length, x", self.notch_length),
            ("Depth, a", self.notch_depth),
            ("Diameter", self.diameter),
            ("Angle", self.angle),
            ("Side slope, z", self.side_slope),
            ("Total depth", self.total_depth),
            ("Weir coeff. Cw", self.cw_row),
            ("Compute by", self.compute_by),
        ):
            form.addRow(label, widget)
        form.addRow(self.mode_label, self.mode_value)
        form.addRow("Depths", depths)

        self.title.editingFinished.connect(self.recalculate)
        for w in (self.weir_type, self.crest, self.compute_by):
            w.currentIndexChanged.connect(self.recalculate)
        self.cw_default.toggled.connect(self.recalculate)
        for w in self._numbers():
            w.valueChanged.connect(self.recalculate)

    def _numbers(self):
        return (
            self.bottom_length, self.notch_length, self.notch_depth, self.diameter,
            self.angle, self.side_slope, self.total_depth, self.cw, self.known_q,
            self.known_depth, self.increments,
        )  # fmt: skip

    def load(self, x: WeirInputs) -> None:
        widgets = (
            self.title, self.weir_type, self.crest, self.compute_by, self.cw_default,
            *self._numbers(),
        )  # fmt: skip
        for w in widgets:
            w.blockSignals(True)
        self.title.setText(x.title)
        self.weir_type.setCurrentIndex(WEIR_TYPES.index(x.weir_type))
        self.crest.setCurrentIndex(list(DEFAULT_CW).index(x.crest))
        self.bottom_length.setValue(x.bottom_length)
        self.notch_length.setValue(x.notch_length)
        self.notch_depth.setValue(x.notch_depth)
        self.diameter.setValue(x.diameter)
        self.angle.setValue(x.angle)
        self.side_slope.setValue(x.side_slope)
        self.total_depth.setValue(x.total_depth)
        self.cw_default.setChecked(x.cw is None)
        self.cw.setValue(x.weir_coefficient)
        self.compute_by.setCurrentIndex(COMPUTE_BY.index(x.compute_by))
        self.known_q.setValue(x.known_q)
        self.known_depth.setValue(x.known_depth)
        self.increments.setValue(x.increments)
        for w in widgets:
            w.blockSignals(False)
        self.recalculate()

    def inputs(self) -> WeirInputs:
        return WeirInputs(
            title=self.title.text().strip(),
            weir_type=self.weir_type.currentData(),
            crest=self.crest.currentData(),
            bottom_length=self.bottom_length.value(),
            total_depth=self.total_depth.value(),
            cw=None if self.cw_default.isChecked() else self.cw.value(),
            notch_length=self.notch_length.value(),
            notch_depth=self.notch_depth.value(),
            diameter=self.diameter.value(),
            angle=self.angle.value(),
            side_slope=self.side_slope.value(),
            compute_by=self.compute_by.currentData(),
            known_q=self.known_q.value(),
            known_depth=self.known_depth.value(),
            increments=self.increments.value(),
        )

    def calculate(self) -> Calculation:
        t = self.weir_type.currentData()
        # Express: only rectangular and compound weirs can be broad crested.
        broad_ok = t in BROAD_CREST_TYPES
        if not broad_ok and self.crest.currentData() == "broad":
            self.crest.blockSignals(True)
            self.crest.setCurrentIndex(0)
            self.crest.blockSignals(False)
        self.crest.model().item(1).setEnabled(broad_ok)
        x = self.inputs()
        for key, widget in self._row_widgets.items():
            self.form.setRowVisible(widget, t in _ROWS[key])
        self.bottom_length_label.setText(
            "Bottom width" if t == "trapezoidal" else "Bottom length"
        )
        self.cw.setEnabled(not self.cw_default.isChecked())
        if self.cw_default.isChecked():
            self.cw.blockSignals(True)
            self.cw.setValue(DEFAULT_CW[x.crest])
            self.cw.blockSignals(False)
        index = COMPUTE_BY.index(x.compute_by)
        self.mode_value.setCurrentIndex(index)
        self.mode_label.setText(("Known Q", "Known depth", "Increments")[index])
        return calculate_weir(x)

    def depth_chip(self, calc: Calculation) -> str:
        return "Exact depths"
