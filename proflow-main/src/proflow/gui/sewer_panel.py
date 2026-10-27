"""Storm Sewers: a branching network, every pipe's flow, HGL/EGL and a profile.

The page edits a native project. A PFSUITE exchange is imported only when it
validates with no unresolved links; until then its report is shown and the
project is left as it was. Manning's n and the starting HGL are never
filled in for the user: the Carlson material n is offered with a Use button.

Edits apply to the selected pipe (n, junction K) and the structure at its
upstream end (catchment, known flow); the outfall's starting HGL and the
rainfall apply to the whole network.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from proflow.calculate import LineResult, calculate_network
from proflow.engine.result import Status
from proflow.engine.sewer import STANDARD_STEP, TAILWATER_LABELS, TAILWATER_MODES
from proflow.engine.sewer_network import RATIONAL_ACCUMULATE
from proflow.graph.sewer import route_profile
from proflow.gui.plots import PlotWidget
from proflow.gui.widgets import STATUS_TEXT, card, number
from proflow.io.pfsuite import read_exchange
from proflow.io.project_json import load_project, save_project
from proflow.io.units import Quantity
from proflow.model.network import Tailwater, mark_user
from proflow.model.project import (
    IdfCurveDef,
    IdfSetDef,
    Project,
    ProjectError,
    RationalCatchment,
)
from proflow.model.topology import network_topology

NEW_FHA = "__new_fha__"
SEWER_IDF = "sewer-fha"

# Selected pipe: label, key, unit.
RESULT_ROWS = (
    ("Sum C x A", "ca", "ac"),
    ("Time of conc., Tc", "tc", "min"),
    ("Intensity, i", "intensity", "in/hr"),
    ("Flow, Q", "flow", "cfs"),
    ("Full-flow capacity", "capacity", "cfs"),
    ("Q / Q full", "ratio", ""),
    ("Travel time", "travel_time", "min"),
    ("Normal / critical depth", "depths", "ft"),
    ("Velocity dn / up", "velocity", "ft/s"),
    ("HGL down", "hgl_down", "ft"),
    ("HGL up", "hgl_up", "ft"),
    ("HGL junction", "hgl_junction", "ft"),
    ("EGL down", "egl_down", "ft"),
    ("EGL up", "egl_up", "ft"),
    ("EGL junction", "egl_junction", "ft"),
    ("Friction / junction loss", "losses", "ft"),
)

# The all-pipes table: header, how to read it from (LineResult, hydraulics).
TABLE = (
    ("Pipe", None),
    ("Into", None),
    ("ΣCA\nac", lambda r, h: f"{r.quantities['ca'][0]:.3f}"),
    ("Tc\nmin", lambda r, h: _qv(r, "tc", 2)),
    ("i\nin/hr", lambda r, h: _qv(r, "intensity", 3)),
    ("Q\ncfs", lambda r, h: f"{r.quantities['flow'][0]:.2f}"),
    (
        "Capacity\ncfs",
        lambda r, h: "none" if h.capacity is None else f"{h.capacity:.2f}",
    ),
    ("Q/Qf", lambda r, h: "–" if h.capacity is None else f"{h.flow / h.capacity:.2f}"),
    ("Tt\nmin", lambda r, h: f"{r.quantities['travel_time'][0]:.2f}"),
    ("HGL dn\nft", lambda r, h: f"{h.down.hgl:.2f}"),
    ("HGL up\nft", lambda r, h: f"{h.up.hgl:.2f}"),
    ("HGL jct\nft", lambda r, h: f"{h.hgl_junction:.2f}"),
    ("EGL dn\nft", lambda r, h: f"{h.down.egl:.2f}"),
    ("EGL up\nft", lambda r, h: f"{h.up.egl:.2f}"),
    ("Notes", None),
)


def _qv(r: LineResult, key: str, places: int) -> str:
    v = r.quantities.get(key)
    return "–" if v is None else f"{v[0]:.{places}f}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'s' * (n != 1)}"


def _section(text: str) -> QLabel:
    return QLabel(text.upper(), objectName="navGroup")


class SewerPanel(QWidget):
    TITLE = "Sewer network"

    def __init__(self, project: Project | None = None) -> None:
        super().__init__(objectName="page")
        self.project = project or Project("Untitled", (), (), ())
        self.path: Path | None = None
        self.report: list[str] = []
        self.suggested_n: dict[str, tuple[float, str]] = {}
        self.selected: str | None = None
        self._fha_event: int | None = None  # event added by the FHA rows
        self.results: dict[str, LineResult] = {}
        self.result: LineResult | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 20)
        outer.setSpacing(12)
        outer.addLayout(self._header())
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._inputs_card(), 0)
        body.addLayout(self._output_column(), 1)
        outer.addLayout(body, 1)
        self.set_project(self.project)

    # --- layout -------------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(0)
        title.addWidget(QLabel("Sewer network", objectName="screenTitle"))
        title.addWidget(
            QLabel(
                "Storm Sewers · Rational flow by HEC-22 7.5, standard step HGL/EGL",
                objectName="muted",
            )
        )
        row.addLayout(title)
        row.addStretch(1)
        for text in (RATIONAL_ACCUMULATE, STANDARD_STEP):
            row.addWidget(QLabel(text, objectName="chipInfo"), 0, Qt.AlignVCenter)
        row.addWidget(QLabel("Experimental", objectName="chipWarn"), 0, Qt.AlignVCenter)
        return row

    def _inputs_card(self) -> QFrame:
        frame, layout = card("Network")
        frame.setFixedWidth(370)
        buttons = QHBoxLayout()
        for text, slot in (
            ("Import PFSUITE…", self._import_dialog),
            ("Open…", self._open_dialog),
            ("Save…", self._save_dialog),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.source_label = QLabel(objectName="muted")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setContentsMargins(0, 0, 6, 0)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(7)
        self.form = form

        form.addRow(_section("Selected pipe"))
        self.pipe_box = QComboBox()
        form.addRow("Pipe", self.pipe_box)
        self.line_label = QLabel(objectName="value")
        form.addRow("", self.line_label)
        self.geometry_label = QLabel(objectName="muted")
        form.addRow(self.geometry_label)
        self.n = number("", 4, 0.2)
        self.n.setSingleStep(0.001)
        self.n.setSpecialValueText("required")
        form.addRow("Manning's n", self.n)
        self.suggest = QWidget()
        srow = QHBoxLayout(self.suggest)
        srow.setContentsMargins(0, 0, 0, 0)
        self.suggest_label = QLabel(objectName="muted")
        self.suggest_label.setWordWrap(True)
        self.use_n = QPushButton("Use")
        self.use_n.clicked.connect(self._use_suggested_n)
        srow.addWidget(self.suggest_label, 1)
        srow.addWidget(self.use_n)
        form.addRow("", self.suggest)
        self.junction_k = number("", 2, 10.0)
        self.junction_k.setToolTip(
            "Junction loss K at this pipe's upstream end, times its velocity head "
            "(manual p. 65). 1.0 is the manual's conservative value."
        )
        form.addRow("Junction K", self.junction_k)

        form.addRow(_section("Its upstream structure"))
        self.structure_label = QLabel(objectName="muted")
        form.addRow(self.structure_label)
        self.area = number("ac", 3, 1e5)
        self.area.setSpecialValueText("none")
        self.c = number("", 2, 1.0)
        self.tc = number("min", 1, 1e4)
        self.known_q = number("cfs", 2, 1e6)
        self.known_q.setSpecialValueText("none")
        form.addRow("Area", self.area)
        form.addRow("Runoff coeff. C", self.c)
        form.addRow("Inlet time", self.tc)
        form.addRow("Known Q", self.known_q)

        form.addRow(_section("Outfall"))
        self.tw_mode = QComboBox()
        self.tw_mode.addItem("required", None)
        for m in TAILWATER_MODES:
            self.tw_mode.addItem(TAILWATER_LABELS[m], m)
        form.addRow("Starting HGL", self.tw_mode)
        self.tw_elev = number("ft", 2, 1e5, -1e5)
        form.addRow("Tailwater elev.", self.tw_elev)

        form.addRow(_section("Rainfall"))
        self.idf = QComboBox()
        self.event = QComboBox()
        form.addRow("IDF", self.idf)
        form.addRow("Event", self.event)
        self.fha_b = number("", 3, 1e4)
        self.fha_d = number("", 2, 1e3)
        self.fha_e = number("", 4, 5.0)
        self.fha_rp = number("yr", 0, 1000)
        for label, w in (
            ("FHA B", self.fha_b),
            ("FHA D", self.fha_d),
            ("FHA E", self.fha_e),
            ("Return period", self.fha_rp),
        ):
            form.addRow(label, w)
        self.fha_hint = QLabel(
            "i = B / (Tc + D)^E, in/hr with Tc in minutes", objectName="muted"
        )
        self.fha_hint.setWordWrap(True)
        form.addRow("", self.fha_hint)

        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        self.pipe_box.currentIndexChanged.connect(
            lambda: self.select(self.pipe_box.currentData())
        )
        for w in (self.n, self.junction_k):
            w.valueChanged.connect(self._pipe_edited)
        for w in (self.area, self.c, self.tc, self.known_q):
            w.valueChanged.connect(self._structure_edited)
        self.tw_mode.currentIndexChanged.connect(self._outfall_edited)
        self.tw_elev.valueChanged.connect(self._outfall_edited)
        for w in (self.fha_b, self.fha_d, self.fha_e, self.fha_rp):
            w.valueChanged.connect(self._rain_edited)
        self.idf.currentIndexChanged.connect(self._rain_edited)
        self.event.currentIndexChanged.connect(self.recalculate)
        return frame

    def _output_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)
        self.status = QLabel()
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        table_card, table_layout = card("Pipes")
        self.table = QTableWidget(0, len(TABLE))
        self.table.setHorizontalHeaderLabels([h for h, _ in TABLE])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._row_selected)
        table_layout.addWidget(self.table)
        table_card.setMinimumHeight(170)
        table_card.setMaximumHeight(230)
        col.addWidget(table_card)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        details, details_layout = card("Selected pipe")
        details.setFixedWidth(330)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.values: dict[str, QLabel] = {}
        for i, (label, key, unit) in enumerate(RESULT_ROWS):
            grid.addWidget(QLabel(label, objectName="valueLabel"), i, 0)
            v = QLabel("–", objectName="value")
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(v, i, 1)
            grid.addWidget(QLabel(unit, objectName="unit"), i, 2)
            self.values[key] = v
        details_layout.addLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.messages = QLabel(objectName="muted")
        self.messages.setWordWrap(True)
        self.messages.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.messages.setTextInteractionFlags(Qt.TextSelectableByMouse)
        scroll.setWidget(self.messages)
        details_layout.addWidget(scroll, 1)
        lower.addWidget(details)
        plot_card, plot_layout = card()
        plot_layout.setContentsMargins(8, 8, 8, 8)
        self.plot = PlotWidget()
        self.plot.empty_text = "Import a PFSUITE network exchange or open a project."
        plot_layout.addWidget(self.plot)
        lower.addWidget(plot_card, 1)
        col.addLayout(lower, 1)
        return col

    # --- loading -------------------------------------------------------------

    def set_project(self, project: Project, path: Path | None = None) -> None:
        self.project = project
        self.path = path
        net = project.network
        pipes = [p.id for p in net.pipes] if net is not None else []
        if self.selected not in pipes:
            self.selected = self._default_pipe()
        self._load_globals()
        self._load_selection()
        self.recalculate()

    def _default_pipe(self) -> str | None:
        """The first headwater pipe, so the profile shows a whole route."""
        net = self.project.network
        if net is None or not net.pipes:
            return None
        topo, _ = network_topology(net)
        if topo is not None:
            return topo.headwaters[0]
        return net.pipes[0].id

    def import_exchange_file(self, path: Path) -> bool:
        """Import a PFSUITE exchange; the project changes only if it validates."""
        result = read_exchange(path)
        self.report = [f"Import {Path(path).name}:", *result.report()]
        if not result.ok:
            self.report.append("Import failed: the project was not changed.")
            self._show_status(
                "statusError", "PFSUITE import failed; see the import report."
            )
            self._show_messages()
            return False
        self.suggested_n = dict(result.suggested_n)
        self.selected = None
        self.set_project(replace(self.project, network=result.network), self.path)
        return True

    def open_project(self, path: Path) -> bool:
        try:
            project = load_project(path)
        except ProjectError as exc:
            self.report = [f"Cannot open {Path(path).name}:"] + [
                f"{p}: {m}" for p, m in exc.problems
            ]
            self._show_status("statusError", "The project could not be opened.")
            self._show_messages()
            return False
        self.report, self.suggested_n, self.selected = [], {}, None
        self.set_project(project, Path(path))
        return True

    def save_to(self, path: Path) -> None:
        save_project(self.project, path)
        self.path = Path(path)
        self.recalculate()

    def build_project(self) -> Project:
        return self.project

    def _import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import PFSUITE network", "", "PFSUITE exchange (*.json)"
        )
        if path:
            self.import_exchange_file(Path(path))

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Pro-Flow project (*.proflow.json *.json)"
        )
        if path:
            self.open_project(Path(path))

    def _save_dialog(self) -> None:
        start = str(self.path) if self.path else "network.proflow.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", start, "Pro-Flow project (*.proflow.json)"
        )
        if path:
            self.save_to(Path(path))

    # --- widgets <-> project ---------------------------------------------------

    @staticmethod
    @contextmanager
    def _quiet(widgets):
        for w in widgets:
            w.blockSignals(True)
        try:
            yield
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _load_globals(self) -> None:
        p, net = self.project, self.project.network
        widgets = (self.pipe_box, self.tw_mode, self.tw_elev, self.idf, self.event)
        widgets += (self.fha_b, self.fha_d, self.fha_e, self.fha_rp)
        with self._quiet(widgets):
            self.pipe_box.clear()
            for pipe in net.pipes if net is not None else ():
                up = net.structure(pipe.upstream)
                self.pipe_box.addItem(f"{pipe.id} · from {up.name or up.id}", pipe.id)
            if self.selected is not None:
                self.pipe_box.setCurrentIndex(self.pipe_box.findData(self.selected))
            self.idf.clear()
            for s in p.idf_sets:
                self.idf.addItem(s.name or s.id, s.id)
            self.idf.addItem("New FHA curve…", NEW_FHA)
            used = {c.idf for c in self._catchments().values()}
            for s in p.idf_sets:
                if s.id in used:
                    self.idf.setCurrentIndex(self.idf.findData(s.id))
            self.event.clear()
            for e in p.events:
                self.event.addItem(f"{e}-yr", e)
            outfall = next(iter(net.outfalls()), None) if net is not None else None
            tw = outfall.tailwater if outfall is not None else None
            self.tw_mode.setCurrentIndex(
                0 if tw is None else TAILWATER_MODES.index(tw.mode) + 1
            )
            if tw is not None and tw.elevation is not None:
                self.tw_elev.setValue(tw.elevation.internal("length"))
            elif net is not None and net.pipes and outfall is not None:
                into = [q for q in net.pipes if q.downstream == outfall.id]
                pipe = into[0] if into else net.pipes[0]
                self.tw_elev.setValue(pipe.invert_down.internal("length"))
            self.fha_rp.setValue(self.fha_rp.value() or 10)

    def _catchments(self) -> dict[str, RationalCatchment]:
        """Structure id -> its Rational catchment."""
        net = self.project.network
        if net is None:
            return {}
        by_id = {c.id: c for c in self.project.catchments}
        return {
            s.id: by_id[s.catchment]
            for s in net.structures
            if s.catchment in by_id
            and isinstance(by_id[s.catchment], RationalCatchment)
        }

    def _load_selection(self) -> None:
        net = self.project.network
        widgets = (self.n, self.junction_k, self.area, self.c, self.tc, self.known_q)
        with self._quiet(widgets):
            if net is None or self.selected is None:
                self.n.setValue(0.0)
                self.junction_k.setValue(1.0)
                return
            pipe = net.pipe(self.selected)
            self.n.setValue(pipe.n or 0.0)
            self.junction_k.setValue(pipe.junction_k)
            up = net.structure(pipe.upstream)
            c = self._catchments().get(up.id)
            self.area.setValue(0.0 if c is None else c.area.internal("drainage_area"))
            self.c.setValue(0.5 if c is None else c.c)
            self.tc.setValue(10.0 if c is None else c.tc.internal("time"))
            self.known_q.setValue(
                0.0 if up.known_flow is None else up.known_flow.internal("flow")
            )

    def select(self, pipe_id: str | None) -> None:
        if pipe_id is None or pipe_id == self.selected:
            return
        self.selected = pipe_id
        with self._quiet((self.pipe_box,)):
            self.pipe_box.setCurrentIndex(self.pipe_box.findData(pipe_id))
        self._load_selection()
        self.recalculate()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            item = self.table.item(rows[0].row(), 0)
            if item is not None:
                self.select(item.text())

    def _use_suggested_n(self) -> None:
        if self.selected in self.suggested_n:
            self.n.setValue(self.suggested_n[self.selected][0])

    def _pipe_edited(self) -> None:
        net = self.project.network
        if net is None or self.selected is None:
            return
        pipe = net.pipe(self.selected)
        n, k = self.n.value() or None, self.junction_k.value()
        changed = [
            f for f, old, new in (("n", pipe.n, n), ("junction_k", pipe.junction_k, k))
            if old != new
        ]  # fmt: skip
        if changed:
            pipe = replace(
                pipe, n=n, junction_k=k, source=mark_user(pipe.source, *changed)
            )
            self.project = replace(self.project, network=net.with_pipe(pipe))
        self.recalculate()

    def _structure_edited(self) -> None:
        net = self.project.network
        if net is None or self.selected is None:
            return
        p = self.project
        up = net.structure(net.pipe(self.selected).upstream)
        cid = up.catchment or self._new_catchment_id(up)
        catchments = [c for c in p.catchments if c.id != cid]
        link = None
        if self.area.value() > 0:
            idf = self._idf_id()
            catchments.append(
                RationalCatchment(
                    id=cid,
                    name=f"Area to {up.name or up.id}",
                    method="rational",
                    idf=idf,
                    area=Quantity(self.area.value(), "ac"),
                    c=self.c.value(),
                    tc=Quantity(self.tc.value(), "min"),
                )
            )
            link = cid
        known = Quantity(self.known_q.value(), "cfs") if self.known_q.value() else None
        pairs = (
            ("catchment", link, up.catchment),
            ("known_flow", known, up.known_flow),
        )
        changed = [f for f, a, b in pairs if a != b]
        up = replace(
            up, catchment=link, known_flow=known, source=mark_user(up.source, *changed)
        )
        self.project = replace(
            p, catchments=tuple(catchments), network=net.with_structure(up)
        )
        self._rain_edited()

    def _new_catchment_id(self, structure) -> str:
        taken = {c.id for c in self.project.catchments}
        base = structure.name or structure.id
        cid, k = base, 2
        while cid in taken:
            cid, k = f"{base}-{k}", k + 1
        return cid

    def _idf_id(self) -> str:
        idf = self.idf.currentData()
        return SEWER_IDF if idf in (NEW_FHA, None) else idf

    def _outfall_edited(self) -> None:
        net = self.project.network
        outfall = next(iter(net.outfalls()), None) if net is not None else None
        if outfall is None:
            self.recalculate()
            return
        mode = self.tw_mode.currentData()
        tw = None
        if mode is not None:
            elev = Quantity(self.tw_elev.value(), "ft") if mode == "elevation" else None
            tw = Tailwater(mode, elev)
        if tw != outfall.tailwater:
            outfall = replace(
                outfall, tailwater=tw, source=mark_user(outfall.source, "tailwater")
            )
            self.project = replace(self.project, network=net.with_structure(outfall))
        self.recalculate()

    def _rain_edited(self) -> None:
        """Every network catchment uses the chosen IDF set (one per system)."""
        p = self.project
        idf_sets, events = p.idf_sets, p.events
        idf = self._idf_id()
        if idf == SEWER_IDF and self.idf.currentData() in (NEW_FHA, None):
            rp = int(self.fha_rp.value())
            coeffs = {
                "b": self.fha_b.value(),
                "d": self.fha_d.value(),
                "e": self.fha_e.value(),
            }
            new = IdfSetDef(
                SEWER_IDF,
                "Entered on the Sewer network page",
                "fha",
                (IdfCurveDef(rp, coeffs),),
            )
            idf_sets = tuple(s for s in idf_sets if s.id != SEWER_IDF) + (new,)
            # Replace the event this page added before, never one the
            # project already had.
            if self._fha_event is not None and self._fha_event != rp:
                events = tuple(e for e in events if e != self._fha_event)
                self._fha_event = None
            if rp not in events:
                events = (*events, rp)
                self._fha_event = rp
        ours = {c.id for c in self._catchments().values()}
        catchments = tuple(
            replace(c, idf=idf) if c.id in ours and c.idf != idf else c
            for c in p.catchments
        )
        self.project = replace(
            p, idf_sets=idf_sets, events=events, catchments=catchments
        )
        self.recalculate()

    def selected_event(self, project: Project) -> int | None:
        if self.idf.currentData() in (NEW_FHA, None):
            return int(self.fha_rp.value())
        e = self.event.currentData()
        if e in project.events:
            return e
        return project.events[0] if project.events else None

    # --- calculating ----------------------------------------------------------

    def recalculate(self) -> None:
        new_fha = self.idf.currentData() in (NEW_FHA, None)
        for w in (self.fha_b, self.fha_d, self.fha_e, self.fha_rp, self.fha_hint):
            self.form.setRowVisible(w, new_fha)
        self.form.setRowVisible(self.event, not new_fha)
        self.form.setRowVisible(self.tw_elev, self.tw_mode.currentData() == "elevation")

        net = self.project.network
        self.results, self.result = {}, None
        self._describe()
        if net is None or not net.pipes:
            self._show_status(
                "statusWarn",
                "No network yet: import a PFSUITE exchange or open a project.",
            )
            self.suggest.setVisible(False)
            self.table.setRowCount(0)
            self._fill(None)
            self.plot.set_spec(None)
            self._show_messages()
            return
        suggestion = self.suggested_n.get(self.selected)
        self.suggest.setVisible(suggestion is not None)
        if suggestion:
            material = net.pipe(self.selected).material or "this material"
            self.suggest_label.setText(
                f"{suggestion[1]} gives n = {suggestion[0]:g} for {material}"
            )

        # A new project has no event until rainfall is entered; the FHA
        # return period on this page is the event to report against.
        event = self.selected_event(self.project)
        run = self.project
        if event is not None and event not in run.events:
            run = replace(run, events=(*run.events, event))
        try:
            project = Project.from_dict(run.to_dict())
        except ProjectError as exc:
            problems = "; ".join(f"{p}: {m}" for p, m in exc.problems)
            self._show_status(
                "statusError", f"Not calculated, invalid input: {problems}"
            )
            self.table.setRowCount(0)
            self._fill(None)
            self._plot(project=None)
            self._show_messages()
            return
        self.results = {
            r.pipe: r for r in calculate_network(project) if r.event == event
        }
        self.result = self.results.get(self.selected)
        ok = [r for r in self.results.values() if r.result.ok]
        if not self.results:
            self._show_status("statusError", "Not calculated: no design event.")
        elif len(ok) == len(self.results):
            warned = sum(bool(r.result.warnings) for r in ok)
            text = f"Calculated {_count(len(ok), 'pipe')}, {event}-yr"
            self._show_status(
                "statusWarn" if warned else "statusOk",
                text + (f"; {warned} with warnings." if warned else "."),
            )
        else:
            r = next(r for r in self.results.values() if not r.result.ok)
            reason = STATUS_TEXT.get(str(r.result.status), str(r.result.status))
            self._show_status(
                "statusError", f"Not calculated, {reason}: {r.result.message}"
            )
        self._fill_table()
        self._fill(self.result)
        self._plot(project)
        self._show_messages(project)

    def _plot(self, project: Project | None) -> None:
        net = self.project.network
        topo, _ = network_topology(net)
        if topo is None or self.selected is None:
            self.plot.set_spec(None)
            self.plot.empty_text = "No profile: the network is not a single tree."
            return
        self.plot.set_spec(route_profile(net, topo, self.results, self.selected))

    def _describe(self) -> None:
        net = self.project.network
        if net is None:
            self.source_label.setText("No network.")
            return
        src = net.source
        parts = [
            f"{net.name}: {_count(len(net.pipes), 'pipe')}, "
            f"{_count(len(net.structures), 'structure')}"
        ]
        if src.get("format"):
            parts.append(
                f"from {src['format']}, exported {src.get('exported_at', '?')}"
            )
        if src.get("origin") == "example":
            parts.append("example inputs, not design values")
        parts.append(
            "plan coordinates: drawing"
            + (f", {net.crs}" if net.crs else ", no CRS on record")
        )
        self.source_label.setText("\n".join(parts))
        if self.selected is None:
            return
        pipe = net.pipe(self.selected)
        up, down = net.structure(pipe.upstream), net.structure(pipe.downstream)
        size = f"{pipe.diameter.value:g} {pipe.diameter.unit}"
        self.line_label.setText(f"{pipe.id} · {size} {pipe.material}".strip())
        length = pipe.length.internal("length")
        run = pipe.source.get("attributes", {}).get("drawn_run_ft")
        z_up = pipe.invert_up.internal("length")
        z_dn = pipe.invert_down.internal("length")
        drawn = f", drawn run {run:.2f}" if run else ""
        self.geometry_label.setText(
            f"{up.name or up.id} ({up.kind}) to {down.name or down.id} ({down.kind})\n"
            f"{length:.2f} ft centre to centre{drawn}\n"
            f"Inverts {z_up:.2f} / {z_dn:.2f} ft, "
            f"slope {(z_up - z_dn) / length * 100:.3f} %"
        )
        self.structure_label.setText(f"{up.name or up.id} ({up.kind})")
        self.n.setToolTip(
            f"source: {pipe.source.get('provenance', {}).get('n', 'not set')}"
        )

    def _show_status(self, name: str, text: str) -> None:
        self.status.setObjectName(name)
        self.status.setText(text)
        self.status.style().polish(self.status)

    def _fill_table(self) -> None:
        net = self.project.network
        topo, _ = network_topology(net)
        order = list(topo.downstream_first()) if topo else [p.id for p in net.pipes]
        with self._quiet((self.table,)):
            self.table.setRowCount(len(order))
            for row, pid in enumerate(order):
                r = self.results.get(pid)
                h = r.result.value if r is not None and r.result.ok else None
                for col, (header, read) in enumerate(TABLE):
                    if header == "Pipe":
                        text = pid
                    elif header == "Into":
                        text = r.downstream if r and r.downstream else "outfall"
                    elif header == "Notes":
                        if r is None or not r.result.ok:
                            text = "not calculated"
                        else:
                            n = len(r.result.warnings)
                            text = f"{n} warning{'s' * (n != 1)}" if n else ""
                    else:
                        text = "–" if h is None else read(r, h)
                    item = QTableWidgetItem(text)
                    if col > 1 and header != "Notes":
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(row, col, item)
                if pid == self.selected:
                    self.table.selectRow(row)

    def _fill(self, r: LineResult | None) -> None:
        h = r.result.value if r is not None and r.result.ok else None
        q = r.quantities if r is not None else {}
        values = dict.fromkeys(self.values, "–")
        for key, places in (("ca", 3), ("tc", 2), ("intensity", 3), ("flow", 3)):
            if key in q:
                values[key] = f"{q[key][0]:.{places}f}"
        if "travel_time" in q:
            values["travel_time"] = f"{q['travel_time'][0]:.2f}"
        if h is not None:
            yn = "none" if h.normal_depth is None else f"{h.normal_depth:.3f}"
            values |= {
                "capacity": "none" if h.capacity is None else f"{h.capacity:.3f}",
                "ratio": "–" if h.capacity is None else f"{h.flow / h.capacity:.2f}",
                "depths": f"{yn} / {h.critical_depth:.3f}",
                "velocity": f"{h.down.velocity:.2f} / {h.up.velocity:.2f}",
                "hgl_down": f"{h.down.hgl:.3f}" + (" c" if h.down.at_critical else ""),
                "hgl_up": f"{h.up.hgl:.3f}" + (" c" if h.up.at_critical else ""),
                "hgl_junction": f"{h.hgl_junction:.3f}",
                "egl_down": f"{h.down.egl:.3f}",
                "egl_up": f"{h.up.egl:.3f}",
                "egl_junction": f"{h.egl_junction:.3f}",
                "losses": f"{h.friction_loss:.3f} / {h.junction_loss:.3f}",
            }
        for key, text in values.items():
            self.values[key].setText(text)

    def _show_messages(self, project: Project | None = None) -> None:
        lines = []
        r = self.result
        if r is not None and r.result.ok:
            lines += [f"⚠ {w}" for w in r.result.warnings] or ["No warnings."]
            h = r.result.value
            if h.up.at_critical or h.down.at_critical:
                lines.append("c = at critical depth")
            into = r.downstream or "the outfall"
            joined = ", ".join(r.upstream) if r.upstream else "none (headwater)"
            lines.append(f"Flows into {into}; pipes joining upstream: {joined}.")
        elif r is not None:
            lines.append(r.result.message)
        net = (project or self.project).network
        if net is not None:
            _, issues = network_topology(net)
            lines += [str(i) for i in issues if i.level != "info"]
            missing = [m for _, m in net.missing_inputs()]
            if missing:
                lines.append("Missing: " + "; ".join(missing))
        lines.append(
            "Flow: sum C x A and the longest time to each pipe, travel time L / V "
            "at normal depth (HEC-22 3rd ed. 7.5). HGL: each line starts at the "
            "HGL in the junction it flows into (Storm Sewers manual p. 64); the "
            "profile is straight between line ends."
        )
        if self.report:
            lines.append("\n".join(self.report))
        self.messages.setText("\n\n".join(lines))

    @property
    def status_ok(self) -> bool:
        r = self.result
        return r is not None and r.result.status is Status.SUCCESS
