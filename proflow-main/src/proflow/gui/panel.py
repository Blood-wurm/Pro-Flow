"""A calculator panel: inputs, results, plots, Q vs. depth table, report.

Subclasses supply the form, the result fields and the calculation; this class
lays them out the same way for every Express calculator and keeps the status,
method id, depth-reporting mode and Experimental label in view.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from proflow.graph.express import rating_plot, section_plot
from proflow.gui.plots import PlotWidget
from proflow.gui.report import export_html, export_pdf, report_document
from proflow.gui.widgets import STATUS_TEXT, card
from proflow.model.express import METHOD_STATUS, Calculation
from proflow.reports.express import result_fields


class CalculatorPanel(QWidget):
    KIND = ""  # "channel" or "weir"
    TITLE = ""
    SUBTITLE = ""
    SECTION_TAB = "Cross-section"
    INPUT_NOTE = ""

    def __init__(self) -> None:
        super().__init__(objectName="page")
        self.calc: Calculation | None = None
        self.fields = result_fields(self.KIND)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 20)
        outer.setSpacing(12)
        outer.addLayout(self._header())
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._inputs_card(), 0)
        body.addWidget(self._output_tabs(), 1)
        outer.addLayout(body, 1)

    # --- subclass hooks -----------------------------------------------------

    def build_form(self, form: QFormLayout) -> None:
        raise NotImplementedError

    def calculate(self) -> Calculation:
        raise NotImplementedError

    def depth_chip(self, calc: Calculation) -> str:
        return "Exact depths"

    def state_note(self, state) -> str:
        return ""

    # --- layout -------------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(0)
        title.addWidget(QLabel(self.TITLE, objectName="screenTitle"))
        title.addWidget(QLabel(self.SUBTITLE, objectName="muted"))
        row.addLayout(title)
        row.addStretch(1)
        self.method_chip = QLabel(objectName="chipInfo")
        self.depth_chip_label = QLabel(objectName="chipInfo")
        experimental = QLabel("Experimental", objectName="chipWarn")
        experimental.setToolTip(METHOD_STATUS)
        for chip in (self.method_chip, self.depth_chip_label, experimental):
            row.addWidget(chip, 0, Qt.AlignVCenter)
        return row

    def _inputs_card(self) -> QFrame:
        frame, layout = card("Inputs")
        frame.setFixedWidth(360)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.build_form(form)
        layout.addLayout(form)
        layout.addStretch(1)
        if self.INPUT_NOTE:
            note = QLabel(self.INPUT_NOTE, objectName="muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        return frame

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
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(12)
        values_card, values_layout = card("Results")
        values_card.setFixedWidth(330)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self._value_labels = {}
        for i, (label, key, unit) in enumerate(self.fields):
            grid.addWidget(QLabel(label, objectName="valueLabel"), i, 0)
            value = QLabel("–", objectName="value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(value, i, 1)
            grid.addWidget(QLabel(unit, objectName="unit"), i, 2)
            self._value_labels[key] = value
        self.state_label = QLabel("", objectName="muted")
        grid.addWidget(self.state_label, len(self.fields), 0, 1, 3)
        values_layout.addLayout(grid)
        left.addWidget(values_card)
        notes_card, notes_layout = card("Warnings and notes")
        notes_card.setFixedWidth(330)
        self.messages = QLabel(objectName="muted")
        self.messages.setWordWrap(True)
        self.messages.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        notes_layout.addWidget(self.messages, 1)
        left.addWidget(notes_card, 1)
        top.addLayout(left)

        plot_card, plot_layout = card()
        plot_layout.setContentsMargins(8, 4, 8, 8)
        self.plot_tabs = QTabWidget(objectName="plotTabs")
        self.section_plot = PlotWidget()
        self.rating_plot = PlotWidget()
        self.plot_tabs.addTab(self.section_plot, self.SECTION_TAB)
        self.plot_tabs.addTab(self.rating_plot, "Rating curve")
        plot_layout.addWidget(self.plot_tabs)
        top.addWidget(plot_card, 1)
        upper = QWidget()
        upper.setLayout(top)

        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(upper)
        table_card, table_layout = card("Q vs. depth")
        self.table = QTableWidget(0, len(self.fields))
        self.table.setHorizontalHeaderLabels(
            [f"{label}\n{unit}" if unit else label for label, _, unit in self.fields]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._row_selected)
        table_layout.addWidget(self.table)
        table_card.setMinimumHeight(160)
        self.table_card = table_card
        self.split.addWidget(table_card)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
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

    # --- behaviour ----------------------------------------------------------

    def recalculate(self) -> None:
        self.calc = self.calculate()
        self.show_calculation(self.calc)

    def show_calculation(self, calc: Calculation) -> None:
        self.method_chip.setText(calc.method or "no method")
        self.depth_chip_label.setText(self.depth_chip(calc))
        self.depth_chip_label.setToolTip(calc.depth_reporting)
        if calc.ok:
            name = "statusWarn" if calc.warnings else "statusOk"
            text = "Calculated with warnings." if calc.warnings else "Calculated."
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
        self.state_label.setText("" if state is None else self.state_note(state))

        rating = calc.ok and len(calc.rows) > 1
        self.table_card.setVisible(rating)
        if rating:
            self.table.blockSignals(True)
            self.table.setRowCount(len(calc.rows))
            for r, s in enumerate(calc.rows):
                for c, (_, key, _) in enumerate(self.fields):
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
        self.rating_plot.set_spec(rating_plot(calc))
        if self.tabs.currentIndex() == 1:
            self._refresh_report()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.calc is None or not self.calc.ok:
            return
        self.calc = replace(self.calc, highlighted=rows[0].row())
        self.show_calculation(self.calc)

    def _refresh_report(self) -> None:
        if self.calc is not None:
            report_document(self.calc, self.preview.document())

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", f"{self.KIND}-report.pdf", "PDF (*.pdf)"
        )
        if path and self.calc is not None:
            export_pdf(self.calc, Path(path))

    def _export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", f"{self.KIND}-report.html", "HTML (*.html)"
        )
        if path and self.calc is not None:
            export_html(self.calc, Path(path))

    def _print(self) -> None:
        if self.calc is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec():
            report_document(self.calc).print_(printer)
