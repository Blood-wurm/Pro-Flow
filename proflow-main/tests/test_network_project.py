"""Storm sewer network in the native project: validation, calculation, CLI."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from proflow.calculate import calculate, calculate_network, results_document
from proflow.cli import EXIT_FAILED, EXIT_OK, main
from proflow.cli_network import EXIT_INVALID
from proflow.engine.result import Status
from proflow.io.project_json import load_project, save_project
from proflow.io.units import Quantity
from proflow.model.network import Pipe, Tailwater
from proflow.model.project import Project, ProjectError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PROJECT = EXAMPLES / "storm-one-pipe.proflow.json"
EXCHANGE = EXAMPLES / "pfsuite" / "one-pipe.pfsuite.json"


def _project() -> Project:
    return load_project(PROJECT)


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_example_round_trips_exactly(tmp_path):
    project = _project()
    out = tmp_path / "saved.proflow.json"
    save_project(project, out)
    assert _json(out) == _json(PROJECT)
    assert load_project(out) == project


def test_one_pipe_example_flow_capacity_and_hgl():
    (r,) = calculate_network(_project())
    assert r.result.ok, r.result.message
    h = r.result.value
    # Q = C i A with the Sedgwick 100-yr FHA curve at Tc = 15 min.
    i = 62.2794 / (15 + 10.1) ** 0.6624
    assert r.quantities["flow"][0] == pytest.approx(0.48 * i * 2.0)
    # Full-flow Manning for a 15-in pipe on 1.5 ft over 150 ft.
    d = 1.25
    q_full = 1.486 / 0.013 * math.pi * d * d / 4 * (d / 4) ** (2 / 3) * 0.1
    assert h.capacity == pytest.approx(q_full)
    assert h.down.hgl == pytest.approx(752.8)  # known tailwater, above critical
    assert h.up.surcharged and h.egl_junction > h.hgl_junction > h.up.hgl
    assert any("exceeds the full-flow capacity" in w for w in r.result.warnings)


def test_results_document_carries_line_rows_with_units():
    project = _project()
    doc = results_document(project, calculate(project), calculate_network(project))
    (row,) = doc["network"]
    assert row["pipe"] == "3F7" and row["status"] == "success"
    assert row["method"] == "sewer.standard_step/1"
    assert row["method_status"] == "experimental"
    assert row["capacity"]["unit"] == "cfs"
    assert row["up"]["hgl"]["unit"] == "ft" and row["up"]["surcharged"] is True
    assert row["tailwater_mode"] == "elevation"


def test_missing_inputs_stop_the_calculation_and_name_themselves():
    project = _project()
    net = project.network
    pipe = replace(net.pipes[0], n=None)
    outfall = replace(net.structure("1C4"), tailwater=None)
    net = net.with_pipe(pipe).with_structure(outfall)
    (r,) = calculate_network(replace(project, network=net))
    assert r.result.status is Status.INVALID_INPUT
    assert "Manning's n" in r.result.message
    assert "starting HGL / tailwater" in r.result.message


def test_parallel_pipe_is_a_flow_split_and_unsupported_not_approximated():
    project = _project()
    net = project.network
    second = replace(net.pipes[0], id="3F8")
    results = calculate_network(
        replace(project, network=replace(net, pipes=(*net.pipes, second)))
    )
    assert [r.pipe for r in results] == ["3F7", "3F8"]
    for r in results:
        assert r.result.status is Status.UNSUPPORTED_REGIME
        assert "flow_split at 1C9" in r.result.message


def test_one_pipe_results_are_unchanged_by_the_network_solver():
    # Values the one-line solver produced before branching networks existed
    # (shown to 3 decimals on the Sewer line page, 2026-10-26).
    (r,) = calculate_network(_project())
    h = r.result.value
    q = r.quantities
    assert round(q["flow"][0], 3) == 7.071
    assert round(q["intensity"][0], 3) == 7.365
    assert round(q["ca"][0], 3) == 0.960
    assert round(h.capacity, 3) == 6.460
    got = [h.down.hgl, h.up.hgl, h.hgl_junction, h.down.egl, h.up.egl, h.egl_junction]
    expected = [752.800, 754.496, 755.012, 753.330, 755.012, 755.527]
    assert [round(v, 3) for v in got] == expected
    assert round(h.friction_loss, 3) == 1.681 and round(h.junction_loss, 3) == 0.516
    assert q["tc"] == q["inlet_time"] == (15.0, "min")  # a headwater pipe
    assert "system_time" not in q and r.downstream is None and r.upstream == ()


def test_hgl_above_the_rim_is_reported():
    project = _project()
    net = project.network
    inlet = replace(net.structure("1C9"), rim=Quantity(754.0, "ft"))
    (r,) = calculate_network(replace(project, network=net.with_structure(inlet)))
    assert r.result.ok
    assert any("water reaches the surface" in w for w in r.result.warnings)


def test_known_flow_adds_to_catchment_runoff():
    project = _project()
    net = project.network
    inlet = replace(net.structure("1C9"), known_flow=Quantity(1.5, "cfs"))
    (r,) = calculate_network(replace(project, network=net.with_structure(inlet)))
    assert r.quantities["flow"][0] == pytest.approx(r.quantities["runoff"][0] + 1.5)


def test_adverse_line_still_computes_from_a_known_tailwater():
    project = _project()
    net = project.network
    pipe = replace(net.pipes[0], invert_up=Quantity(751.4, "ft"))
    (r,) = calculate_network(replace(project, network=net.with_pipe(pipe)))
    assert r.result.ok and r.result.value.capacity is None
    assert any("adverse slope" in w for w in r.result.warnings)


def _mutated(change):
    data = _json(PROJECT)
    change(data["network"])
    return data


@pytest.mark.parametrize(
    "change, path",
    [
        (
            lambda n: n["structures"][1].update(catchment="nope"),
            "structures[1].catchment",
        ),
        (
            lambda n: n["structures"][1].update(tailwater={"mode": "crown"}),
            "structures[1].tailwater",
        ),
        (
            lambda n: n["structures"][0]["tailwater"].update(mode="pond"),
            "tailwater.mode",
        ),
        (
            lambda n: n["structures"][0].update(tailwater={"mode": "elevation"}),
            "tailwater.elevation",
        ),
        (lambda n: n["pipes"][0].update(downstream="ZZZ"), "pipes[0].downstream"),
        (lambda n: n["pipes"][0].update(n=0), "pipes[0].n"),
        (lambda n: n["pipes"][0].update(junction_k=-1), "pipes[0].junction_k"),
        (lambda n: n["pipes"][0]["diameter"].update(value=0), "pipes[0].diameter"),
        (lambda n: n["structures"][1].update(id="1C4"), "structures[1].id"),
        (lambda n: n["structures"][0].update(kind="pond"), "structures[0].kind"),
        (lambda n: n.update(plan_unit="m"), "network.plan_unit"),
        (lambda n: n["pipes"][0].update(colour="red"), "pipes[0].colour"),
    ],
)
def test_invalid_network_names_the_field(change, path):
    with pytest.raises(ProjectError) as info:
        Project.from_dict(_mutated(change))
    assert any(path in p for p, _ in info.value.problems), info.value.problems


def test_scs_catchment_cannot_drain_to_a_sewer_inlet():
    data = _json(EXAMPLES / "scs-user-storm.proflow.json")
    sewer = _json(PROJECT)["network"]
    sewer["structures"][1]["catchment"] = data["catchments"][0]["id"]
    data["network"] = sewer
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    assert any("Standard Rational" in m for _, m in info.value.problems)


def test_incomplete_network_saves_and_reopens(tmp_path):
    project = _project()
    net = project.network.with_pipe(replace(project.network.pipes[0], n=None))
    out = tmp_path / "incomplete.proflow.json"
    save_project(replace(project, network=net), out)
    assert load_project(out).network.pipes[0].n is None


def test_cli_import_into_project_marks_user_inputs(tmp_path, capsys):
    base = tmp_path / "p.proflow.json"
    data = _json(PROJECT)
    del data["network"]
    base.write_text(json.dumps(data), encoding="utf-8")
    code = main(
        [
            "network",
            "import",
            str(EXCHANGE),
            "--into",
            str(base),
            "--n",
            "0.012",
            "--tailwater",
            "crown",
            "--catchment",
            "BA-2",
        ]
    )
    assert code == EXIT_OK
    project = load_project(base)
    pipe: Pipe = project.network.pipes[0]
    assert pipe.n == 0.012 and pipe.source["provenance"]["n"] == "user"
    outfall = project.network.structure("1C4")
    assert outfall.tailwater == Tailwater("crown")
    assert project.network.structure("1C9").source["provenance"]["catchment"] == "user"
    assert main(["run", str(base)]) == EXIT_OK
    assert "line 3F7 100-yr" in capsys.readouterr().out


def test_cli_import_failure_writes_nothing(tmp_path, capsys):
    doc = _json(EXCHANGE)
    doc["pipes"][0]["upstream"]["sheet"]["x"] = 1120.0
    bad = tmp_path / "bad.pfsuite.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    base = tmp_path / "p.proflow.json"
    base.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    before = base.read_text(encoding="utf-8")
    assert main(["network", "import", str(bad), "--into", str(base)]) == EXIT_INVALID
    assert base.read_text(encoding="utf-8") == before
    assert "end_unlinked" in capsys.readouterr().out


def test_cli_run_fails_on_missing_inputs(tmp_path, capsys):
    project = _project()
    net = project.network.with_pipe(replace(project.network.pipes[0], n=None))
    out = tmp_path / "x.proflow.json"
    save_project(replace(project, network=net), out)
    assert main(["run", str(out)]) == EXIT_FAILED
    assert "missing: pipe 3F7: Manning's n" in capsys.readouterr().out
