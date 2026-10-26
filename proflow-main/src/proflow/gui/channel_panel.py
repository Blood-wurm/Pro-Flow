"""Express channel calculator panel."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QStackedWidget

from proflow.gui.panel import CalculatorPanel
from proflow.gui.widgets import increments, number
from proflow.model.express import (
    COMPUTE_BY,
    COMPUTE_LABELS,
    DEPTH_LABELS,
    SECTIONS,
    Calculation,
    ChannelInputs,
    calculate_channel,
)

# The published Express case "EX DRAINAGEWAY SEC B-B @ Q100" (fixtures/express).
CHANNEL_EXAMPLE = ChannelInputs(
    title="EX Drainageway Sec B-B @ Q100",
    section="trapezoidal",
    bottom_width=5.0,
    left_slope=9.0,
    right_slope=9.0,
    total_depth=2.5,
    invert_elevation=6892.10,
    slope_percent=1.5,
    n=0.050,
    compute_by="known_q",
    known_q=21.33,
)


class ChannelPanel(CalculatorPanel):
    KIND = "channel"
    TITLE = "Channel"
    SUBTITLE = "Express · uniform flow by Manning's equation"
    INPUT_NOTE = (
        "Manning k = 1.486 (published Express reports reproduce with it; "
        "the manual prints 1.49)."
    )

    def __init__(self, inputs: ChannelInputs = CHANNEL_EXAMPLE) -> None:
        super().__init__()
        self.load(inputs)

    def build_form(self, form: QFormLayout) -> None:
        self.title = QLineEdit()
        self.section = QComboBox()
        for s in SECTIONS:
            self.section.addItem(s.capitalize(), s)
        self.bottom_width = number("ft", 2, 1e4)
        self.left_slope = number("H:1V", 2, 1e3)
        self.right_slope = number("H:1V", 2, 1e3)
        self.total_depth = number("ft", 2, 1e3)
        self.invert = number("ft", 2, 1e5, -1e5)
        self.slope = number("%", 3, 100.0, -100.0)
        self.n = number("", 3, 1.0)
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
        self.depth_reporting = QComboBox()
        self.depth_reporting.addItem("Exact", "exact")
        self.depth_reporting.addItem("Express stepped (0.01 ft, up)", "express_stepped")
        self.depth_reporting.setToolTip(
            "\n".join(f"{k}: {v}" for k, v in DEPTH_LABELS.items())
        )
        for label, widget in (
            ("Title", self.title),
            ("Section", self.section),
            ("Bottom width", self.bottom_width),
            ("Left side slope", self.left_slope),
            ("Right side slope", self.right_slope),
            ("Total depth", self.total_depth),
            ("Invert elevation", self.invert),
            ("Slope", self.slope),
            ("Manning's n", self.n),
            ("Compute by", self.compute_by),
        ):
            form.addRow(label, widget)
        form.addRow(self.mode_label, self.mode_value)
        form.addRow("Depths", self.depth_reporting)

        self.title.editingFinished.connect(self.recalculate)
        for w in (self.section, self.compute_by, self.depth_reporting):
            w.currentIndexChanged.connect(self.recalculate)
        for w in self._numbers():
            w.valueChanged.connect(self.recalculate)

    def _numbers(self):
        return (
            self.bottom_width, self.left_slope, self.right_slope, self.total_depth,
            self.invert, self.slope, self.n, self.known_q, self.known_depth,
            self.increments,
        )  # fmt: skip

    def load(self, x: ChannelInputs) -> None:
        widgets = (
            self.title, self.section, self.compute_by, self.depth_reporting,
            *self._numbers(),
        )  # fmt: skip
        for w in widgets:
            w.blockSignals(True)
        self.title.setText(x.title)
        self.section.setCurrentIndex(SECTIONS.index(x.section))
        self.bottom_width.setValue(x.bottom_width)
        self.left_slope.setValue(x.left_slope)
        self.right_slope.setValue(x.right_slope)
        self.total_depth.setValue(x.total_depth)
        self.invert.setValue(x.invert_elevation)
        self.slope.setValue(x.slope_percent)
        self.n.setValue(x.n)
        self.compute_by.setCurrentIndex(COMPUTE_BY.index(x.compute_by))
        self.known_q.setValue(x.known_q)
        self.known_depth.setValue(x.known_depth)
        self.increments.setValue(x.increments)
        self.depth_reporting.setCurrentIndex(0 if x.depth_reporting == "exact" else 1)
        for w in widgets:
            w.blockSignals(False)
        self.recalculate()

    def inputs(self) -> ChannelInputs:
        return ChannelInputs(
            title=self.title.text().strip(),
            section=self.section.currentData(),
            bottom_width=self.bottom_width.value(),
            left_slope=self.left_slope.value(),
            right_slope=self.right_slope.value(),
            total_depth=self.total_depth.value(),
            invert_elevation=self.invert.value(),
            slope_percent=self.slope.value(),
            n=self.n.value(),
            compute_by=self.compute_by.currentData(),
            known_q=self.known_q.value(),
            known_depth=self.known_depth.value(),
            increments=self.increments.value(),
            depth_reporting=self.depth_reporting.currentData(),
        )

    def calculate(self) -> Calculation:
        x = self.inputs()
        self.bottom_width.setEnabled(x.section != "triangular")
        for w in (self.left_slope, self.right_slope):
            w.setEnabled(x.section != "rectangular")
        index = COMPUTE_BY.index(x.compute_by)
        self.mode_value.setCurrentIndex(index)
        self.mode_label.setText(("Known Q", "Known depth", "Increments")[index])
        return calculate_channel(x)

    def depth_chip(self, calc: Calculation) -> str:
        if calc.inputs.depth_reporting == "exact":
            return "Exact depths"
        return "Express stepped depths"

    def state_note(self, state) -> str:
        return f"Flow regime: {state.regime}"
