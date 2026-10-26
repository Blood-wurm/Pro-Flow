import copy
import json
from pathlib import Path

import pytest

from proflow.calculate import calculate, results_document
from proflow.cli import EXIT_INVALID, EXIT_OK, main
from proflow.io.project_json import load_project, save_project
from proflow.model.project import Project, ProjectError

EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "hydrographs-rational-ex-dp-7.proflow.json"
)


def _data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _problems(data):
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    return dict(info.value.problems)


def test_open_save_open_preserves_inputs(tmp_path):
    project = load_project(EXAMPLE)
    save_project(project, tmp_path / "copy.proflow.json")
    again = load_project(tmp_path / "copy.proflow.json")
    assert again == project
    assert again.to_dict() == project.to_dict()


def test_entered_units_are_kept():
    data = _data()
    data["catchments"][0]["area"] = {"value": 3.3063, "unit": "ha"}
    data["catchments"][0]["tc"] = {"value": 840, "unit": "s"}
    project = Project.from_dict(data)
    assert project.to_dict()["catchments"][0]["area"] == {"value": 3.3063, "unit": "ha"}
    # Same catchment in SI-entered units gives the same peak.
    peak_si = calculate(project)[0].result.value.peak
    peak_us = calculate(load_project(EXAMPLE))[0].result.value.peak
    assert peak_si == pytest.approx(peak_us, rel=1e-4)


def test_modified_rational_round_trip():
    data = _data()
    data["catchments"].append(
        {
            "id": "2",
            "name": "Pond inflow",
            "method": "modified_rational",
            "idf": "printed-5yr",
            "area": {"value": 2, "unit": "ac"},
            "c": 0.9,
            "tc": {"value": 10, "unit": "min"},
            "storm_duration_factor": 2.0,
        }
    )
    project = Project.from_dict(data)
    assert Project.from_dict(project.to_dict()) == project
    result = calculate(project)[1]
    assert result.result.method == "rational.modified/2"
    hyd = result.result.value
    # Storm lasts 20 min; base = 20 + Tc = 30 min; trapezoid volume = Qp * 20 min.
    assert hyd.times[-1] == 30.0
    assert hyd.volume == pytest.approx(hyd.peak * 20 * 60)


def test_example_reproduces_public_hydrographs_case():
    (r,) = calculate(load_project(EXAMPLE))
    assert r.result.ok
    assert r.result.value.peak == pytest.approx(11.77, abs=0.005)
    assert r.result.value.volume == pytest.approx(9884, abs=0.5)


def test_results_document_records_method_and_versions():
    project = load_project(EXAMPLE)
    doc = results_document(project, calculate(project))
    assert doc["schema"] == "proflow-results"
    assert doc["project"]["schema_version"] == 3
    assert doc["proflow_version"]
    (row,) = doc["results"]
    assert row["method"] == "rational.standard/2"
    assert row["method_status"] == "experimental"
    assert row["peak"]["unit"] == "cfs"
    assert len(row["hydrograph"]["flows"]["values"]) == 29


def test_cli_run_writes_results(tmp_path, capsys):
    out = tmp_path / "results.json"
    assert main(["run", str(EXAMPLE), "-o", str(out)]) == EXIT_OK
    assert "Qp=11.77 cfs" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["results"][0]["status"] == (
        "success"
    )


def test_cli_rejects_invalid_project(tmp_path, capsys):
    data = _data()
    data["catchments"][0]["idf"] = "missing"
    bad = tmp_path / "bad.proflow.json"
    bad.write_text(json.dumps(data))
    assert main(["run", str(bad)]) == EXIT_INVALID
    assert "catchments[0].idf: no IDF set with id 'missing'" in capsys.readouterr().err


def test_cli_fixtures(capsys):
    assert main(["fixtures"]) == EXIT_OK
    summary = capsys.readouterr().out.splitlines()[-1]
    passed, complete = summary.split()[0].split("/")
    assert passed == complete and int(complete) >= 7, summary


@pytest.mark.parametrize(
    "mutate,path,message",
    [
        (
            lambda d: d.update(schema_version=4),
            "project.schema_version",
            "not supported",
        ),
        (lambda d: d.update(colour="blue"), "project.colour", "unknown field"),
        (lambda d: d.update(events=[5, 100]), "catchments[0].idf", "no 100-yr curve"),
        (
            lambda d: d["catchments"][0].update(tc={"value": 14, "unit": "%"}),
            "catchments[0].tc",
            "not valid for time",
        ),
        (
            lambda d: d["catchments"][0].update(c=1.2),
            "catchments[0].c",
            "(0, 1]",
        ),
        (
            lambda d: d["catchments"][0].update(method="modified_rational"),
            "catchments[0].storm_duration_factor",
            "required",
        ),
        (
            lambda d: d["catchments"].append(copy.deepcopy(d["catchments"][0])),
            "catchments[1].id",
            "duplicate",
        ),
        (
            lambda d: d["rainfall"]["idf_sets"][0].update(form="table"),
            "rainfall.idf_sets[0].form",
            "expected one of",
        ),
    ],
)
def test_validation_errors_name_the_field(mutate, path, message):
    data = _data()
    mutate(data)
    problems = _problems(data)
    assert path in problems, problems
    assert message in problems[path]


def test_all_problems_reported_together():
    data = _data()
    data["catchments"][0]["c"] = 0
    data["catchments"][0]["area"] = {"value": -1, "unit": "ac"}
    problems = _problems(data)
    assert {"catchments[0].c", "catchments[0].area"} <= set(problems)


def test_ascending_limb_factor_round_trip_and_calculation():
    data = _data()
    data["catchments"][0]["ascending_limb_factor"] = 1.5
    project = Project.from_dict(data)
    assert Project.from_dict(project.to_dict()) == project
    (r,) = calculate(project)
    assert r.result.value.time_to_peak == 21.0  # 1.5 x Tc of 14 min
    assert r.result.value.peak == pytest.approx(11.767, abs=0.001)


def test_limb_factors_only_for_standard_rational():
    data = _data()
    data["catchments"][0] |= {
        "method": "modified_rational",
        "storm_duration_factor": 2.0,
    }
    problems = _problems(data)
    assert "only for rational" in problems["catchments[0].ascending_limb_factor"]
    assert "only for rational" in problems["catchments[0].receding_limb_factor"]


def test_polynomial_idf_outside_manual_range_warns():
    data = _data()
    data["rainfall"]["idf_sets"].append(
        {
            "id": "poly",
            "name": "FLZone1H.IDF 5-yr coefficients (Express manual p. 57)",
            "form": "polynomial",
            "curves": [
                {"return_period": 5, "a": 11.82413, "b": -2.28931, "c": -0.07735,
                 "d": 0.02535}
            ],
        }
    )  # fmt: skip
    data["catchments"][0]["idf"] = "poly"
    data["catchments"][0]["tc"] = {"value": 5, "unit": "min"}
    (r,) = calculate(Project.from_dict(data))
    assert any("outside the 8-180 min range" in w for w in r.result.warnings)
    data["catchments"][0]["tc"] = {"value": 14, "unit": "min"}
    (r,) = calculate(Project.from_dict(data))
    assert not any("8-180" in w for w in r.result.warnings)
