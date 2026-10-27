"""A branching sewer: Rational accumulation downstream, HGL/EGL upstream.

The Y example (examples/storm-y-network.proflow.json) has example hydraulic
inputs, not design values. Expected numbers here are computed in the test,
from the IDF equation, segment geometry and Manning, with their own root
finding: not by calling the solver.
"""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from proflow.calculate import calculate, calculate_network, results_document
from proflow.cli import main
from proflow.engine.result import Status
from proflow.engine.sewer import Line
from proflow.engine.sewer_network import Inflow, network_hydraulics, rational_flows
from proflow.io.project_json import load_project
from proflow.io.units import Quantity
from proflow.model.project import IdfCurveDef, IdfSetDef

G = 32.174
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
Y = EXAMPLES / "storm-y-network.proflow.json"


def _i(t):  # the example's IDF: Sedgwick 100-yr FHA coefficients
    return 62.2794 / (t + 10.1) ** 0.6624


def _seg(d, y):
    y = min(y, d)
    t = 2 * math.acos(1 - 2 * y / d)
    return d * d / 8 * (t - math.sin(t)), d * t / 2, d * math.sin(t / 2)


def _normal_velocity(d, s, n, q):
    lo, hi = 1e-9, 0.93 * d
    for _ in range(200):
        y = (lo + hi) / 2
        a, p, _ = _seg(d, y)
        if 1.486 / n * a * (a / p) ** (2 / 3) * math.sqrt(s) < q:
            lo = y
        else:
            hi = y
    a, _, _ = _seg(d, (lo + hi) / 2)
    return q / a


def _results():
    return {r.pipe: r for r in calculate_network(load_project(Y))}


# --- flow ----------------------------------------------------------------------


def test_branch_flows_and_section_times():
    r = _results()
    qa, qb = 0.5 * 1.5 * _i(10), 0.7 * 1.0 * _i(15)
    assert r["PA"].quantities["flow"][0] == pytest.approx(qa)
    assert r["PB"].quantities["flow"][0] == pytest.approx(qb)
    ta = 250 / _normal_velocity(1.5, (102.09 - 100.84) / 250, 0.013, qa) / 60
    tb = 120 / _normal_velocity(1.5, (101.44 - 100.84) / 120, 0.013, qb) / 60
    assert r["PA"].quantities["travel_time"][0] == pytest.approx(ta, rel=1e-6)
    assert r["PB"].quantities["travel_time"][0] == pytest.approx(tb, rel=1e-6)


def test_junction_carries_sum_ca_and_the_longest_time_not_the_sum_of_peaks():
    r = _results()
    qa, qb = 0.75 * _i(10), 0.7 * _i(15)
    ta = 250 / _normal_velocity(1.5, 1.25 / 250, 0.013, qa) / 60
    tb = 120 / _normal_velocity(1.5, 0.6 / 120, 0.013, qb) / 60
    tc = max(10 + ta, 15 + tb)
    assert tc == 15 + tb  # branch B's route is the longer one
    p1 = r["P1"].quantities
    assert p1["ca"][0] == pytest.approx(0.75 + 0.70)
    assert p1["system_time"][0] == pytest.approx(tc, rel=1e-6)
    assert p1["tc"][0] == pytest.approx(tc, rel=1e-6)
    assert p1["intensity"][0] == pytest.approx(_i(tc), rel=1e-6)
    assert p1["flow"][0] == pytest.approx(1.45 * _i(tc), rel=1e-6)
    assert p1["flow"][0] < qa + qb - 0.9  # not the added branch peaks
    assert r["P1"].upstream == ("PA", "PB") and r["PA"].downstream == "P1"


def test_known_flow_is_carried_downstream():
    project = load_project(Y)
    net = project.network
    b1 = replace(net.structure("B1"), known_flow=Quantity(2.0, "cfs"))
    r = {
        x.pipe: x
        for x in calculate_network(replace(project, network=net.with_structure(b1)))
    }
    assert r["PB"].quantities["known_flow"] == (2.0, "cfs")
    p1 = r["P1"].quantities
    assert p1["flow"][0] == pytest.approx(p1["ca"][0] * p1["intensity"][0] + 2.0)


def test_lower_flow_than_an_incoming_pipe_is_kept_and_warned():
    # A small, quick area joined by a long, slow pipe: the junction's longer
    # time lowers the intensity more than the extra area adds.
    lines = {p: Line(1.5, 2000.0, 110.0, 100.0, 0.013) for p in ("A", "J")}
    lines["B"] = Line(1.5, 20.0, 100.2, 100.0, 0.013)
    flows = rational_flows(
        ("A", "B", "J"),
        {"J": ("A", "B")},
        {"A": Inflow(3.0, 5.0), "B": Inflow(0.05, 60.0), "J": Inflow()},
        lines,
        _i,
    )
    j = flows["J"]
    assert j.ok and j.value.flow < flows["A"].value.flow
    assert any("less than" in w for w in j.warnings)


def test_full_pipe_velocity_is_used_and_said_when_there_is_no_normal_depth():
    flows = rational_flows(
        ("A",),
        {},
        {"A": Inflow(10.0, 10.0)},
        {"A": Line(1.0, 100.0, 100.1, 100.0, 0.013)},
        _i,
    )
    f = flows["A"]
    assert f.value.velocity_basis == "full pipe"
    assert f.value.velocity == pytest.approx(f.value.flow / (math.pi / 4))
    assert any("full-pipe velocity" in w for w in f.warnings)


# --- hydraulics ------------------------------------------------------------------


def _energy_residual(line: Line, q, y_dn, y_up):
    def state(y):
        a, p, _ = _seg(line.diameter, y)
        sf = (q * line.n / (1.486 * a * (a / p) ** (2 / 3))) ** 2
        return (q / a) ** 2 / (2 * G), sf

    hv_dn, sf_dn = state(y_dn)
    hv_up, sf_up = state(y_up)
    up = line.invert_up + y_up + hv_up
    dn = line.invert_down + y_dn + hv_dn + line.length * (sf_dn + sf_up) / 2
    return up - dn


def test_hgl_runs_from_the_outfall_and_branches_start_at_the_junction():
    project = load_project(Y)
    r = _results()
    p1, pa, pb = (r[k].result.value for k in ("P1", "PA", "PB"))
    assert all(r[k].result.ok for k in r)
    assert p1.down.hgl == pytest.approx(101.8)  # the outfall's tailwater
    # Junction loss belongs to the line leaving J1, at its upstream end.
    a1, _, _ = _seg(2.0, p1.up.depth)
    v1 = p1.flow / a1
    assert p1.hgl_junction == pytest.approx(p1.up.hgl + 1.0 * v1 * v1 / (2 * G))
    for branch in (pa, pb):
        assert branch.down.hgl == pytest.approx(p1.hgl_junction)
        assert not branch.down.at_critical
    for pid, h in (("P1", p1), ("PA", pa), ("PB", pb)):
        pipe = project.network.pipe(pid)
        line = Line(
            pipe.diameter.internal("length"),
            pipe.length.internal("length"),
            pipe.invert_up.internal("length"),
            pipe.invert_down.internal("length"),
            pipe.n,
        )
        assert _energy_residual(line, h.flow, h.down.depth, h.up.depth) == (
            pytest.approx(0, abs=1e-6)
        )


def test_a_branch_above_the_junction_hgl_starts_at_critical_depth():
    project = load_project(Y)
    net = project.network
    pb = net.pipe("PB")
    raised = replace(
        pb, invert_down=Quantity(103.0, "ft"), invert_up=Quantity(103.6, "ft")
    )
    r = {
        x.pipe: x
        for x in calculate_network(replace(project, network=net.with_pipe(raised)))
    }
    h = r["PB"].result.value
    assert h.down.at_critical and h.down.depth == pytest.approx(h.critical_depth)
    assert any(
        "discharges freely into the junction" in w for w in r["PB"].result.warnings
    )
    # Its own flow and HGL do not change the line it drops into.
    assert r["P1"].result.value.down.hgl == pytest.approx(101.8)


def test_a_failed_line_stops_the_lines_upstream_of_it():
    lines = {
        "P1": Line(0.0, 100.0, 101.0, 100.0, 0.013),  # invalid diameter
        "PA": Line(1.5, 100.0, 102.0, 101.0, 0.013),
    }
    out = network_hydraulics(
        ("P1", "PA"),
        {"P1": None, "PA": "P1"},
        lines,
        {"P1": 5.0, "PA": 3.0},
        {},
        "crown",
        None,
    )
    assert out["P1"].status is Status.INVALID_INPUT
    assert "downstream pipe P1 failed" in out["PA"].message


# --- project level -----------------------------------------------------------------


def test_missing_input_in_one_branch_stops_the_network_and_names_it():
    project = load_project(Y)
    net = project.network.with_pipe(replace(project.network.pipe("PB"), n=None))
    results = calculate_network(replace(project, network=net))
    assert {r.pipe for r in results} == {"P1", "PA", "PB"}
    for r in results:
        assert r.result.status is Status.INVALID_INPUT
        assert "pipe PB: Manning's n" in r.result.message


def test_cycle_is_reported_for_every_pipe():
    project = load_project(Y)
    net = project.network
    loop = replace(net.pipe("P1"), downstream="A1")  # J1 -> A1 -> J1
    results = calculate_network(replace(project, network=net.with_pipe(loop)))
    for r in results:
        assert r.result.status is Status.INVALID_INPUT
        assert "cycle" in r.result.message


def test_catchments_on_different_idf_sets_are_refused():
    project = load_project(Y)
    other = IdfSetDef(
        "other", "", "fha", (IdfCurveDef(100, {"b": 50, "d": 10, "e": 0.7}),)
    )
    a, b = project.catchments
    project = replace(
        project,
        idf_sets=(*project.idf_sets, other),
        catchments=(a, replace(b, idf="other")),
    )
    (r, *_) = calculate_network(project)
    assert "different IDF sets" in r.result.message


def test_results_document_and_cli_show_every_pipe(capsys, tmp_path):
    project = load_project(Y)
    doc = results_document(project, calculate(project), calculate_network(project))
    rows = {row["pipe"]: row for row in doc["network"]}
    assert set(rows) == {"P1", "PA", "PB"}
    assert rows["P1"]["upstream_pipes"] == ["PA", "PB"]
    assert rows["PA"]["downstream_pipe"] == "P1"
    assert rows["P1"]["flow_method"] == "sewer.rational.accumulate/1"
    assert rows["PB"]["travel_time"]["unit"] == "min"
    assert rows["PB"]["down"]["hgl"]["value"] == pytest.approx(
        rows["P1"]["hgl_junction"]["value"]
    )
    out = tmp_path / "r.json"
    assert main(["run", str(Y), "-o", str(out)]) == 0
    text = capsys.readouterr().out
    for pid in ("P1", "PA", "PB"):
        assert f"line {pid} 100-yr" in text
    assert "Tt=" in text and "Tc=" in text
    assert json.loads(out.read_text(encoding="utf-8"))["network"]


def test_example_inputs_are_labelled_as_examples():
    net = load_project(Y).network
    assert net.source["origin"] == "example"
    for item in (*net.structures, *net.pipes):
        assert item.source["origin"] == "example"
        assert set(item.source["provenance"].values()) == {"example"}
