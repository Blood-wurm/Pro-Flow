"""Express weir calculator panel (rectangular weir)."""

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
    COMPUTE_BY,
    COMPUTE_LABELS,
    WEIR_DEPTH_LABEL,
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


class WeirPanel(CalculatorPanel):
    KIND = "weir"
    TITLE = "Weir"
    SUBTITLE = "Express · rectangular weir, Q = Cw L H^1.5"
    SECTION_TAB = "Weir section"
    INPUT_NOTE = (
        "Cw defaults follow the Express manual: 3.33 sharp crest, 2.6 broad "
        "crest. No end-contraction correction."
    )

    def __init__(self, inputs: WeirInputs = WEIR_EXAMPLE) -> None:
        super().__init__()
        self.load(inputs)

    def build_form(self, form: QFormLayout) -> None:
        self.title = QLineEdit()
        self.crest = QComboBox()
        for c in DEFAULT_CW:
            self.crest.addItem(c.capitalize(), c)
        self.bottom_length = number("ft", 2, 1e4)
        self.total_depth = number("ft", 2, 1e3)
        self.cw = number("", 2, 10.0)
        self.cw_default = QCheckBox("Express default")
        cw_row = QWidget()
        cw_layout = QHBoxLayout(cw_row)
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
        depths = QLabel("Exact (closed form)", objectName="muted")
        depths.setToolTip(WEIR_DEPTH_LABEL)
        for label, widget in (
            ("Title", self.title),
            ("Crest", self.crest),
            ("Bottom length", self.bottom_length),
            ("Total depth", self.total_depth),
            ("Weir coeff. Cw", cw_row),
            ("Compute by", self.compute_by),
        ):
            form.addRow(label, widget)
        form.addRow(self.mode_label, self.mode_value)
        form.addRow("Depths", depths)

        self.title.editingFinished.connect(self.recalculate)
        for w in (self.crest, self.compute_by):
            w.currentIndexChanged.connect(self.recalculate)
        self.cw_default.toggled.connect(self.recalculate)
        for w in self._numbers():
            w.valueChanged.connect(self.recalculate)

    def _numbers(self):
        return (
            self.bottom_length, self.total_depth, self.cw, self.known_q,
            self.known_depth, self.increments,
        )  # fmt: skip

    def load(self, x: WeirInputs) -> None:
        widgets = (
            self.title,
            self.crest,
            self.compute_by,
            self.cw_default,
            *self._numbers(),
        )
        for w in widgets:
            w.blockSignals(True)
        self.title.setText(x.title)
        self.crest.setCurrentIndex(list(DEFAULT_CW).index(x.crest))
        self.bottom_length.setValue(x.bottom_length)
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
            crest=self.crest.currentData(),
            bottom_length=self.bottom_length.value(),
            total_depth=self.total_depth.value(),
            cw=None if self.cw_default.isChecked() else self.cw.value(),
            compute_by=self.compute_by.currentData(),
            known_q=self.known_q.value(),
            known_depth=self.known_depth.value(),
            increments=self.increments.value(),
        )

    def calculate(self) -> Calculation:
        x = self.inputs()
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
