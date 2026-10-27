"""Offscreen smoke tests of the Storm Sewers page (import, edit, calculate, save).

Skipped when PySide6 is not installed, unless PROFLOW_REQUIRE_GUI is set.
"""

import json
import os
from pathlib import Path

import pytest

if os.environ.get("PROFLOW_REQUIRE_GUI"):
    import PySide6  # noqa: F401  (fail loudly)
else:
    pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from proflow.gui import style  # noqa: E402
from proflow.gui.app import MainWindow  # noqa: E402
from proflow.gui.sewer_panel import SewerPanel  # noqa: E402
from proflow.io.project_json import load_project  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXCHANGE = EXAMPLES / "pfsuite" / "one-pipe.pfsuite.json"
PROJECT = EXAMPLES / "storm-one-pipe.proflow.json"


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    style.apply(instance)
    yield instance
    for widget in instance.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    instance.processEvents()


def test_shell_has_a_storm_sewers_page(app):
    w = MainWindow()
    w.nav_buttons["Sewer network"].click()
    assert isinstance(w.current, SewerPanel)
    assert w.windowTitle() == "Pro-Flow · Storm Sewers · Sewer network"


def test_empty_page_asks_for_a_network(app):
    p = SewerPanel()
    assert p.result is None
    assert "No network yet" in p.status.text()


def test_import_lists_missing_inputs_and_does_not_apply_n(app):
    p = SewerPanel()
    assert p.import_exchange_file(EXCHANGE)
    assert p.project.network.pipes[0].n is None
    assert p.n.text() == "required"
    assert "Missing:" in p.messages.text() and "Manning's n" in p.messages.text()
    assert p.suggest.isVisibleTo(p) and "0.013" in p.suggest_label.text()
    assert p.result is not None and not p.result.result.ok


def test_entering_n_tailwater_and_rainfall_calculates(app):
    p = SewerPanel()
    p.import_exchange_file(EXCHANGE)
    p.use_n.click()  # the user's explicit choice of the suggested n
    p.tw_mode.setCurrentIndex(p.tw_mode.findData("crown"))
    p.fha_b.setValue(62.2794)
    p.fha_d.setValue(10.1)
    p.fha_e.setValue(0.6624)
    p.fha_rp.setValue(100)
    p.area.setValue(2.0)
    p.c.setValue(0.48)
    p.tc.setValue(15.0)
    assert p.status_ok, p.status.text()
    assert p.values["flow"].text() == "7.071"
    assert p.values["hgl_down"].text() == "752.850"  # crown: 751.60 + 1.25
    built = p.build_project()
    pipe = built.network.pipes[0]
    assert pipe.n == 0.013 and pipe.source["provenance"]["n"] == "user"
    outfall = built.network.structure("1C4")
    assert outfall.source["provenance"]["tailwater"] == "user"


def test_failed_import_leaves_the_project_alone(app, tmp_path):
    doc = json.loads(EXCHANGE.read_text(encoding="utf-8"))
    doc["pipes"][0]["grid"] = "nope"
    bad = tmp_path / "bad.pfsuite.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    p = SewerPanel()
    p.open_project(PROJECT)
    before = p.project
    assert not p.import_exchange_file(bad)
    assert p.project is before
    assert "pipe_no_grid" in p.messages.text()
    assert "project was not changed" in p.messages.text()


def test_open_calculate_save_and_reopen(app, tmp_path):
    p = SewerPanel()
    assert p.open_project(PROJECT)
    assert p.status_ok
    assert p.values["hgl_down"].text() == "752.800"
    assert "Line 3F7" in p.plot._spec.title
    names = [s.name for s in p.plot._spec.series if s.name]
    assert names == ["Water", "Pipe", "Rim", "HGL", "EGL", "Yc"]
    p.n.setValue(0.015)
    out = tmp_path / "saved.proflow.json"
    p.save_to(out)
    reopened = load_project(out)
    assert reopened.network.pipes[0].n == 0.015
    assert reopened.network == p.project.network
    q = SewerPanel()
    q.open_project(out)
    assert q.values["hgl_down"].text() == p.values["hgl_down"].text()


Y = EXAMPLES / "storm-y-network.proflow.json"


def _cell(p, row, header):
    from proflow.gui.sewer_panel import TABLE

    col = [h for h, _ in TABLE].index(header)
    return p.table.item(row, col).text()


def test_y_network_table_shows_every_pipe(app):
    p = SewerPanel()
    assert p.open_project(Y)
    assert p.status_ok, p.status.text()
    assert p.table.rowCount() == 3
    rows = {_cell(p, r, "Pipe"): r for r in range(3)}
    assert set(rows) == {"P1", "PA", "PB"}
    assert _cell(p, rows["PA"], "Into") == "P1"
    assert _cell(p, rows["P1"], "Into") == "outfall"
    for pid, r in rows.items():
        q = p.results[pid].quantities
        assert _cell(p, r, "Q\ncfs") == f"{q['flow'][0]:.2f}"
        assert _cell(p, r, "Tt\nmin") == f"{q['travel_time'][0]:.2f}"
        h = p.results[pid].result.value
        assert _cell(p, r, "HGL jct\nft") == f"{h.hgl_junction:.2f}"
    # Opens on a headwater pipe so the profile shows a whole route.
    assert p.selected == "PA"
    assert p.plot._spec.title.startswith("Route PA: Inlet A to Outfall")
    assert p.plot._spec.x_label == "Distance from outfall (ft)"


def test_selecting_and_editing_a_branch_changes_only_that_pipe(app):
    p = SewerPanel()
    p.open_project(Y)
    rows = {_cell(p, r, "Pipe"): r for r in range(3)}
    p.table.selectRow(rows["PB"])
    assert p.selected == "PB" and p.pipe_box.currentData() == "PB"
    assert p.values["flow"].text() == f"{p.results['PB'].quantities['flow'][0]:.3f}"
    pa_flow = p.results["PA"].quantities["flow"]
    p1_tc = p.results["P1"].quantities["tc"][0]
    p.n.setValue(0.015)
    pipes = {x.id: x for x in p.project.network.pipes}
    assert pipes["PB"].n == 0.015 and pipes["PB"].source["provenance"]["n"] == "user"
    assert pipes["PA"].n == 0.013
    # PB is not upstream of PA, so PA's flow is unchanged; but PB's slower
    # route sets P1's time, so P1 (and the junction PA starts from) moves.
    assert p.results["PA"].quantities["flow"] == pa_flow
    assert p.results["P1"].quantities["tc"][0] > p1_tc
