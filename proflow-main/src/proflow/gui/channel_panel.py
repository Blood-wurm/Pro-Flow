"""Express channel calculator panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from proflow.engine.result import Status
from proflow.gui.panel import CalculatorPanel
from proflow.gui.widgets import increments, number
from proflow.model.express import (
    COMPUTE_BY,
    COMPUTE_LABELS,
    DEPTH_LABELS,
    SECTION_LABELS,
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

# Which form rows each section uses.
_ROWS = {
    "bottom_width": ("rectangular", "trapezoidal"),
    "left_slope": ("triangular", "trapezoidal"),
    "right_slope": ("triangular", "trapezoidal"),
    "diameter": ("circular",),
    "cross_slope": ("gutter",),
    "gutter_slope": ("gutter",),
    "gutter_width": ("gutter",),
    "points": ("user",),
    "invert": ("rectangular", "triangular", "trapezoidal", "circular", "gutter"),
    "n": ("rectangular", "triangular", "trapezoidal", "circular", "gutter"),
}


class PointsTable(QWidget):
    """Station / elevation / n rows for a user-defined section (up to 50)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Sta (ft)", "Elev (ft)", "n"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(210)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add = QPushButton("Add point")
        self.remove = QPushButton("Remove")
        buttons.addWidget(self.add)
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.add.clicked.connect(self._add)
        self.remove.clicked.connect(self._remove)
        note = QLabel("n applies from the previous point.", objectName="muted")
        layout.addWidget(note)

    def set_points(self, points) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(points))
        for r, row in enumerate(points):
            for c, v in enumerate(row):
                text = "" if (r == 0 and c == 2) else f"{v:g}"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    def points(self) -> tuple[tuple[float, float, float], ...]:
        """The rows as numbers; raises ValueError naming the first bad cell."""
        out = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(3):
                item = self.table.item(r, c)
                text = item.text().strip() if item else ""
                if r == 0 and c == 2:
                    row.append(0.0)
                    continue
                try:
                    row.append(float(text))
                except ValueError:
                    name = ("station", "elevation", "n")[c]
                    raise ValueError(
                        f"point {r + 1}: {name} {text!r} is not a number"
                    ) from None
            out.append(tuple(row))
        return tuple(out)

    def _add(self) -> None:
        if self.table.rowCount() >= 50:
            return
        pts = list(self._safe_points())
        last = pts[-1] if pts else (0.0, 0.0, 0.0)
        pts.append((last[0] + 5.0, last[1], last[2] or 0.035))
        self.set_points(pts)
        self.table.cellChanged.emit(len(pts) - 1, 0)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0 and self.table.rowCount() > 3:
            self.table.removeRow(row)
            self.table.cellChanged.emit(0, 0)

    def _safe_points(self):
        try:
            return self.points()
        except ValueError:
            return ()


class ChannelPanel(CalculatorPanel):
    KIND = "channel"
    TITLE = "Channel"
    SUBTITLE = "Express · uniform flow in an open channel"
    INPUT_NOTE = (
        "Manning k = 1.486 (published Express reports reproduce with it; "
        "the manual prints 1.49). Gutters use the HEC-22 gutter equation."
    )

    def __init__(self, inputs: ChannelInputs = CHANNEL_EXAMPLE) -> None:
        super().__init__()
        self._points_error = ""
        self.load(inputs)

    def build_form(self, form: QFormLayout) -> None:
        self.form = form
        self.title = QLineEdit()
        self.section = QComboBox()
        for s in SECTIONS:
            self.section.addItem(SECTION_LABELS[s], s)
        self.bottom_width = number("ft", 2, 1e4)
        self.left_slope = number("H:1V", 2, 1e3)
        self.right_slope = number("H:1V", 2, 1e3)
        self.diameter = number("ft", 2, 100.0)
        self.cross_slope = number("ft/ft", 3, 1.0)
        self.gutter_slope = number("ft/ft", 3, 1.0)
        self.gutter_width = number("ft", 2, 100.0)
        self.points_table = PointsTable()
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
        self._row_widgets = {
            "bottom_width": self.bottom_width,
            "left_slope": self.left_slope,
            "right_slope": self.right_slope,
            "diameter": self.diameter,
            "cross_slope": self.cross_slope,
            "gutter_slope": self.gutter_slope,
            "gutter_width": self.gutter_width,
            "points": self.points_table,
            "invert": self.invert,
            "n": self.n,
        }
        for label, widget in (
            ("Title", self.title),
            ("Section", self.section),
            ("Bottom width", self.bottom_width),
            ("Left side slope", self.left_slope),
            ("Right side slope", self.right_slope),
            ("Diameter", self.diameter),
            ("Cross slope, Sx", self.cross_slope),
            ("Gutter slope, Sw", self.gutter_slope),
            ("Gutter width", self.gutter_width),
            ("Points", self.points_table),
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
        self.points_table.table.cellChanged.connect(lambda *_: self.recalculate())

    def _numbers(self):
        return (
            self.bottom_width, self.left_slope, self.right_slope, self.diameter,
            self.cross_slope, self.gutter_slope, self.gutter_width, self.total_depth,
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
        self.diameter.setValue(x.diameter)
        self.cross_slope.setValue(x.cross_slope)
        self.gutter_slope.setValue(x.gutter_slope)
        self.gutter_width.setValue(x.gutter_width)
        self.points_table.set_points(x.points)
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
        try:
            points = self.points_table.points()
            self._points_error = ""
        except ValueError as exc:
            points = ()
            self._points_error = str(exc)
        return ChannelInputs(
            title=self.title.text().strip(),
            section=self.section.currentData(),
            bottom_width=self.bottom_width.value(),
            left_slope=self.left_slope.value(),
            right_slope=self.right_slope.value(),
            diameter=self.diameter.value(),
            cross_slope=self.cross_slope.value(),
            gutter_slope=self.gutter_slope.value(),
            gutter_width=self.gutter_width.value(),
            points=points,
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
        for key, widget in self._row_widgets.items():
            self.form.setRowVisible(widget, x.section in _ROWS[key])
        uses_total = x.section in ("rectangular", "triangular", "trapezoidal") or (
            x.section == "gutter" and x.compute_by == "rating"
        )
        self.form.setRowVisible(self.total_depth, uses_total)
        index = COMPUTE_BY.index(x.compute_by)
        self.mode_value.setCurrentIndex(index)
        self.mode_label.setText(("Known Q", "Known depth", "Increments")[index])
        if x.section == "user" and self._points_error:
            return Calculation(
                "channel", x, Status.INVALID_INPUT, "", self._points_error,
                depth_reporting=DEPTH_LABELS[x.depth_reporting],
            )  # fmt: skip
        return calculate_channel(x)

    def depth_chip(self, calc: Calculation) -> str:
        if calc.inputs.depth_reporting == "exact":
            return "Exact depths"
        return "Express stepped depths"

    def state_note(self, state) -> str:
        return f"Flow regime: {state.regime}"
