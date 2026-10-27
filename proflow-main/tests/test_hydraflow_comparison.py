"""The opt-in, documented Hydraflow comparison path stays distinct from HEC-22."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from proflow.calculate import calculate_network, network_rows
from proflow.cli import main
from proflow.engine.junction import automatic_k, deflection_degrees
from proflow.io.project_json import load_project

EXAMPLE = (
    Path(__file__).resolve().parent.parent / "examples" / "storm-y-network.proflow.json"
)


def test_documented_automatic_junction_coefficients():
    assert automatic_k(0, "manhole") == pytest.approx(0.15)
    assert automatic_k(0, "inlet") == pytest.approx(0.5)
    assert automatic_k(45, "manhole") == pytest.approx(0.75)
    assert automatic_k(45, "inlet") == pytest.approx(1.125)
    assert automatic_k(90, "manhole") == 1.0
    assert automatic_k(90, "inlet") == 1.5
    assert automatic_k(135, "inlet") == 1.5
    assert deflection_degrees((2, 0), (1, 0), (0, 0)) == pytest.approx(0)
    assert deflection_degrees((1, 1), (1, 0), (0, 0)) == pytest.approx(90)


def test_automatic_k_discloses_ambiguous_branch_rule_and_requires_geometry():
    project = load_project(EXAMPLE)
    by_id = {r.pipe: r for r in calculate_network(project, junction_losses="automatic")}
    assert by_id["P1"].result.value.junction_k == 1.0  # largest angle is 90
    assert "largest of 2" in " ".join(by_id["P1"].result.warnings)
    assert by_id["PA"].result.value.junction_k == 1.0  # end of branch

    net = project.network
    at = net.structure("A1")
    collapsed = net.with_structure(replace(at, x=180.0, y=0.0))
    bad = calculate_network(
        replace(project, network=collapsed), junction_losses="automatic"
    )
    assert all(not r.result.ok for r in bad)
    assert all("plan coordinates coincide" in r.result.message for r in bad)


def test_three_passes_use_hydraulic_average_velocity_and_keep_default_method():
    project = load_project(EXAMPLE)
    base = {r.pipe: r for r in calculate_network(project)}
    ems = {
        r.pipe: r
        for r in calculate_network(
            project, sewer_method="hydraflow_ems", design_velocity=5.0
        )
    }
    assert base["P1"].flow_method == "sewer.rational.accumulate/1"
    assert ems["P1"].flow_method == "sewer.rational.hydraflow_ems_3pass/1"
    row = next(r for r in network_rows(list(ems.values())) if r["pipe"] == "P1")
    assert row["design_velocity"] == {"value": 5.0, "unit": "ft/s"}
    assert row["junction_loss_method"] == "entered"
    assert ems["P1"].quantities["tc"][0] > base["P1"].quantities["tc"][0]
    assert ems["P1"].quantities["flow"][0] < base["P1"].quantities["flow"][0]

    branch_b = ems["PB"].quantities
    expected_tc = 15 + branch_b["travel_time"][0]
    assert ems["P1"].quantities["tc"][0] == pytest.approx(expected_tc)
    h = ems["PB"].result.value
    actual_average = (h.up.velocity + h.down.velocity) / 2
    assert branch_b["hydraulic_average_velocity"][0] == pytest.approx(actual_average)
    assert branch_b["travel_velocity"][0] == pytest.approx(actual_average, rel=1e-3)
    assert branch_b["travel_time"][0] == pytest.approx(
        120 / branch_b["travel_velocity"][0] / 60
    )


def test_comparison_inputs_are_explicit_and_cli_runs(capsys):
    project = load_project(EXAMPLE)
    with pytest.raises(ValueError, match="positive design_velocity"):
        calculate_network(
            project, sewer_method="hydraflow_ems", design_velocity=math.nan
        )
    with pytest.raises(ValueError, match="only applies"):
        calculate_network(project, design_velocity=5.0)
    assert main(["run", str(EXAMPLE), "--sewer-method", "hydraflow_ems"]) == 2
    assert "requires --design-velocity" in capsys.readouterr().err
    assert (
        main(
            [
                "run",
                str(EXAMPLE),
                "--sewer-method",
                "hydraflow_ems",
                "--design-velocity",
                "5",
                "--junction-losses",
                "automatic",
            ]
        )
        == 0
    )
    assert "sewer.rational.hydraflow_ems_3pass/1" in capsys.readouterr().out
