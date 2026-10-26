"""Prototype Express screen: channel inputs, results, cross-section, report preview.

Run: python -m proflow.gui.channel_screen
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from proflow.graph.express import section_plot
from proflow.gui import style
from proflow.gui.plots import PlotWidget
from proflow.gui.report import export_html, export_pdf, report_document
from proflow.model.express import (
    COMPUTE_BY,
    COMPUTE_LABELS,
    DEPTH_LABELS,
    METHOD_STATUS,
    SECTIONS,
    Calculation,
    ChannelInputs,
    calculate_channel,
)
from proflow.reports.express import RESULT_FIELDS

# The published Express case "EX DRAINAGEWAY SEC B-B @ Q100" (fixtures/express).
EXAMPLE = ChannelInputs(
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


STATUS_TEXT = {
    "invalid_input": "invalid input",
    "unsupported_regime": "outside the supported range",
    "no_convergence": "no convergence",
}


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    if title:
        layout.addWidget(QLabel(title, objectName="cardTitle"))
    return frame, layout


def _number(
    suffix: str, decimals: int, maximum: float, minimum: float = 0.0
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSuffix(f"  {suffix}" if suffix else "")
    box.setAlignment(Qt.AlignRight)
    box.setKeyboardTracking(False)
    return box


class ChannelScreen(QMainWindow):
    def __init__(self, inputs: ChannelInputs = EXAMPLE) -> None:
        super().__init__()
        self.setWindowTitle("Pro-Flow · Express · Channel")
        self.calc: Calculation | None = None
        page = QWidget(objectName="page")
        self.setCentralWidget(page)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 14, 18, 18)
        outer.setSpacing(12)
        outer.addLayout(self._header())
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._inputs_card(), 0)
        body.addWidget(self._output_tabs(), 1)
        outer.addLayout(body, 1)
        self._load(inputs)
        available = self.screen().availableGeometry()
        self.resize(
            min(1320, int(available.width() * 0.9)),
            min(860, int(available.height() * 0.9)),
        )

    # --- layout ---------------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(0)
        title.addWidget(QLabel("Channel", objectName="screenTitle"))
        title.addWidget(
            QLabel("Express · uniform flow by Manning's equation", objectName="muted")
        )
        row.addLayout(title)
        row.addStretch(1)
        self.method_chip = QLabel(objectName="chipInfo")
        self.depth_chip = QLabel(objectName="chipInfo")
        experimental = QLabel("Experimental", objectName="chipWarn")
        experimental.setToolTip(METHOD_STATUS)
        for chip in (self.method_chip, self.depth_chip, experimental):
            row.addWidget(chip, 0, Qt.AlignVCenter)
        return row

    def _inputs_card(self) -> QFrame:
        card, layout = _card("Inputs")
        card.setFixedWidth(360)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.title = QLineEdit()
        self.section = QComboBox()
        for s in SECTIONS:
            self.section.addItem(s.capitalize(), s)
        self.bottom_width = _number("ft", 2, 1e4)
        self.left_slope = _number("H:1V", 2, 1e3)
        self.right_slope = _number("H:1V", 2, 1e3)
        self.total_depth = _number("ft", 2, 1e3)
        self.invert = _number("ft", 2, 1e5, -1e5)
        self.slope = _number("%", 3, 100.0, -100.0)
        self.n = _number("", 3, 1.0)
        self.compute_by = QComboBox()
        for m in COMPUTE_BY:
            self.compute_by.addItem(COMPUTE_LABELS[m], m)
        self.known_q = _number("cfs", 2, 1e7)
        self.known_depth = _number("ft", 3, 1e3)
        self.increments = QSpinBox()
        self.increments.setRange(1, 50)
        self.increments.setAlignment(Qt.AlignRight)
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

        self._rows = {}
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
            self._rows[label] = widget
        form.addRow(self.mode_label, self.mode_value)
        form.addRow("Depths", self.depth_reporting)
        layout.addLayout(form)
        layout.addStretch(1)
        note = QLabel(
            "Manning k = 1.486 (published Express reports reproduce with it; "
            "the manual prints 1.49).",
            objectName="muted",
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self._form = form

        for w in (self.title,):
            w.editingFinished.connect(self.recalculate)
        for w in (self.section, self.compute_by, self.depth_reporting):
            w.currentIndexChanged.connect(self.recalculate)
        for w in (
            self.bottom_width, self.left_slope, self.right_slope,
            self.total_depth, self.invert, self.slope, self.n,
            self.known_q, self.known_depth, self.increments,
        ):  # fmt: skip
            w.valueChanged.connect(self.recalculate)
        return card

    def _output_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.addTab(self._results_page(), "Results")
        tabs.addTab(self._report_page(), "Report preview")
        tabs.currentChanged.connect(lambda i: i == 1 and self._refresh_report())
        self.tabs = tabs
        return tabs

    def _results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        top = QHBoxLayout()
        top.setSpacing(12)
        values_card, values_layout = _card("Results")
        values_card.setFixedWidth(330)
        self.values_grid = QGridLayout()
        self.values_grid.setHorizontalSpacing(10)
        self.values_grid.setVerticalSpacing(5)
        self._value_labels = {}
        for i, (label, key, unit) in enumerate(RESULT_FIELDS):
            self.values_grid.addWidget(QLabel(label, objectName="valueLabel"), i, 0)
            value = QLabel("–", objectName="value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.values_grid.addWidget(value, i, 1)
            self.values_grid.addWidget(QLabel(unit, objectName="unit"), i, 2)
            self._value_labels[key] = value
        self.regime = QLabel("", objectName="muted")
        self.values_grid.addWidget(self.regime, len(RESULT_FIELDS), 0, 1, 3)
        values_layout.addLayout(self.values_grid)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(values_card)
        notes_card, notes_layout = _card("Warnings and notes")
        notes_card.setFixedWidth(330)
        self.messages = QLabel(objectName="muted")
        self.messages.setWordWrap(True)
        self.messages.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        notes_layout.addWidget(self.messages, 1)
        left.addWidget(notes_card, 1)
        top.addLayout(left)

        plot_card, plot_layout = _card("")
        self.section_plot = PlotWidget()
        plot_layout.addWidget(self.section_plot)
        top.addWidget(plot_card, 1)
        upper = QWidget()
        upper.setLayout(top)
        top.setContentsMargins(0, 0, 0, 0)
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(upper)

        table_card, table_layout = _card("Q vs. depth")
        self.table = QTableWidget(0, len(RESULT_FIELDS))
        self.table.setHorizontalHeaderLabels(
            [f"{label}\n{unit}" if unit else label for label, _, unit in RESULT_FIELDS]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._row_selected)
        table_layout.addWidget(self.table)
        self.table_card = table_card
        self.split.addWidget(table_card)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        table_card.setMinimumHeight(160)
        layout.addWidget(self.split, 1)
        return page

    def _report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for text, slot, primary in (
            ("Print…", self._print, False),
            ("Export HTML…", self._export_html, False),
            ("Export PDF…", self._export_pdf, True),
        ):
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(slot)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.preview = QTextBrowser()
        self.preview.document().setDocumentMargin(28)
        layout.addWidget(self.preview, 1)
        return page

    # --- behaviour ------------------------------------------------------------

    def _load(self, x: ChannelInputs) -> None:
        widgets = [
            self.title, self.section, self.bottom_width, self.left_slope,
            self.right_slope, self.total_depth, self.invert, self.slope, self.n,
            self.compute_by,
            self.known_q, self.known_depth, self.increments, self.depth_reporting,
        ]  # fmt: skip
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

    def _sync_form(self, x: ChannelInputs) -> None:
        self.bottom_width.setEnabled(x.section != "triangular")
        for w in (self.left_slope, self.right_slope):
            w.setEnabled(x.section != "rectangular")
        index = COMPUTE_BY.index(x.compute_by)
        self.mode_value.setCurrentIndex(index)
        self.mode_label.setText(("Known Q", "Known depth", "Increments")[index])

    def recalculate(self) -> None:
        x = self.inputs()
        self._sync_form(x)
        self.calc = calculate_channel(x)
        self._show(self.calc)

    def _show(self, calc: Calculation) -> None:
        self.method_chip.setText(calc.method or "no method")
        mode = (
            "Exact depths"
            if calc.inputs.depth_reporting == "exact"
            else "Express stepped depths"
        )
        self.depth_chip.setText(mode)
        self.depth_chip.setToolTip(calc.depth_reporting)
        if calc.ok:
            name = "statusWarn" if calc.warnings else "statusOk"
            text = "Calculated." if not calc.warnings else "Calculated with warnings."
        else:
            name = "statusError"
            reason = STATUS_TEXT.get(str(calc.status), str(calc.status))
            text = f"Not calculated, {reason}: {calc.message}"
        self.status.setObjectName(name)
        self.status.setText(text)
        self.status.style().polish(self.status)

        state = calc.state
        for key, label in self._value_labels.items():
            label.setText("–" if state is None else f"{getattr(state, key):,.3f}")
        self.regime.setText("" if state is None else f"Flow regime: {state.regime}")

        rating = calc.ok and len(calc.rows) > 1
        self.table_card.setVisible(rating)
        if rating:
            self.table.blockSignals(True)
            self.table.setRowCount(len(calc.rows))
            for r, s in enumerate(calc.rows):
                for c, (_, key, _) in enumerate(RESULT_FIELDS):
                    item = QTableWidgetItem(f"{getattr(s, key):,.3f}")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(r, c, item)
            self.table.resizeColumnsToContents()
            self.table.selectRow(calc.highlighted)
            self.table.blockSignals(False)

        warnings = [f"⚠ {w}" for w in calc.warnings] or ["No warnings."]
        lines = [*warnings, f"Depths: {calc.depth_reporting}.", *calc.notes]
        self.messages.setText("\n\n".join(lines))
        self.section_plot.set_spec(section_plot(calc))
        if self.tabs.currentIndex() == 1:
            self._refresh_report()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.calc is None or not self.calc.ok:
            return
        self.calc = replace(self.calc, highlighted=rows[0].row())
        self._show(self.calc)

    def _refresh_report(self) -> None:
        if self.calc is not None:
            report_document(self.calc, self.preview.document())

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", "channel-report.pdf", "PDF (*.pdf)"
        )
        if path and self.calc is not None:
            export_pdf(self.calc, Path(path))

    def _export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", "channel-report.html", "HTML (*.html)"
        )
        if path and self.calc is not None:
            export_html(self.calc, Path(path))

    def _print(self) -> None:
        if self.calc is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec():
            report_document(self.calc).print_(printer)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    style.apply(app)
    window = ChannelScreen()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
