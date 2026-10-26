import copy
import json
from pathlib import Path

import pytest

from proflow.calculate import calculate, results_document
from proflow.cli import EXIT_OK, main
from proflow.engine.unit_hydrograph import scs_runoff_hydrograph
from proflow.io.project_json import load_project
from proflow.model.project import Project, ProjectError, ScsCatchment

EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" / "scs-user-storm.proflow.json"
)


def _data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _problems(data):
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    return dict(info.value.problems)


def test_example_round_trips_exactly():
    project = load_project(EXAMPLE)
    assert project.to_dict() == _data()
    assert Project.from_dict(project.to_dict()) == project
    assert all(isinstance(c, ScsCatchment) for c in project.catchments)


def test_project_result_equals_direct_engine_call():
    project = load_project(EXAMPLE)
    results = calculate(project)
    c = project.catchments[0]
    direct = scs_runoff_hydrograph(
        area=50.0,
        cn=75,
        tc=20.0,
        storm=project.storm("five-point").mass_curve(),
        total_depth=3.0,
        dt=2.0,
        form="curvilinear",
    )
    (row,) = [r for r in results if r.catchment == c.id and r.event == 2]
    assert row.result.method == direct.method
    assert (row.result.value.flows == direct.value.hydrograph.flows).all()
    assert row.quantities["precipitation"] == (3.0, "in")


def test_both_unit_hydrograph_forms_reported_separately():
    results = calculate(load_project(EXAMPLE))
    methods = {(r.catchment, r.result.method) for r in results}
    assert methods == {
        ("A-nrcs", "scs.uh.curvilinear/1"),
        ("A-tri", "scs.uh.triangular/1"),
    }
    assert all(r.result.ok for r in results)


def test_storm_in_mm_and_minutes_gives_same_result():
    data = _data()
    storm = data["rainfall"]["storms"][0]
    storm["distribution"]["times"] = {
        "values": [t * 60 for t in storm["distribution"]["times"]["values"]],
        "unit": "min",
    }
    storm["depths"][0]["depth"] = {"value": 76.2, "unit": "mm"}
    metric = calculate(Project.from_dict(data))[0]
    base = calculate(load_project(EXAMPLE))[0]
    assert metric.result.value.peak == pytest.approx(base.result.value.peak)


def test_results_document_has_scs_quantities_and_mass_balance():
    project = load_project(EXAMPLE)
    row = results_document(project, calculate(project))["results"][0]
    assert row["precipitation"] == {"value": 3.0, "unit": "in"}
    assert row["runoff_depth"]["unit"] == "in"
    assert "mass_balance_residual_in" in row["diagnostics"]


def test_cli_runs_scs_example(capsys):
    assert main(["run", str(EXAMPLE)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "scs.uh.curvilinear/1" in out and "scs.uh.triangular/1" in out


def test_rational_and_scs_in_one_project():
    data = _data()
    data["rainfall"]["idf_sets"] = [
        {
            "id": "flat",
            "name": "constant 4 in/hr",
            "form": "fha",
            "curves": [
                {"return_period": 2, "b": 4, "d": 0, "e": 0},
                {"return_period": 100, "b": 6, "d": 0, "e": 0},
            ],
        }
    ]
    data["catchments"].append(
        {
            "id": "R",
            "name": "paved lot",
            "method": "rational",
            "idf": "flat",
            "area": {"value": 2, "unit": "ac"},
            "c": 0.9,
            "tc": {"value": 10, "unit": "min"},
        }
    )
    results = calculate(Project.from_dict(data))
    assert len(results) == 6 and all(r.result.ok for r in results)


def _scs(data):
    return data["catchments"][0]


@pytest.mark.parametrize(
    "mutate,path,message",
    [
        (lambda d: _scs(d).update(storm="nope"), "catchments[0].storm", "no storm"),
        (
            lambda d: d.update(events=[2, 10]),
            "catchments[0].storm",
            "no 10-yr depth",
        ),
        (lambda d: _scs(d).update(cn=0), "catchments[0].cn", "(0, 100]"),
        (
            lambda d: _scs(d).update(unit_hydrograph="snyder"),
            "catchments[0].unit_hydrograph",
            "expected one of",
        ),
        (
            lambda d: _scs(d).update(shape_factor=300),
            "catchments[0].shape_factor",
            "only for triangular",
        ),
        (
            lambda d: _scs(d).update(tp_equation="lag"),
            "catchments[0].tp_equation",
            "expected one of",
        ),
        (lambda d: _scs(d).update(ia_ratio=1.5), "catchments[0].ia_ratio", "[0, 1)"),
        (lambda d: _scs(d).update(c=0.5), "catchments[0].c", "unknown field"),
        (
            lambda d: d["rainfall"]["storms"][0]["distribution"].update(
                fractions=[0, 0.1, 0.2, 0.3, 0.9]
            ),
            "rainfall.storms[0].distribution",
            "must end at 1",
        ),
        (
            lambda d: d["rainfall"]["storms"][0]["distribution"]["times"].update(
                unit="%"
            ),
            "rainfall.storms[0].distribution",
            "not valid for time",
        ),
        (
            lambda d: d["rainfall"]["storms"][0]["depths"].append(
                copy.deepcopy(d["rainfall"]["storms"][0]["depths"][0])
            ),
            "rainfall.storms[0].depths",
            "unique",
        ),
    ],
)
def test_scs_validation_errors_name_the_field(mutate, path, message):
    data = _data()
    mutate(data)
    problems = _problems(data)
    assert path in problems, problems
    assert message in problems[path]


def test_triangular_shape_factor_round_trip():
    data = _data()
    data["catchments"][1]["shape_factor"] = 300
    project = Project.from_dict(data)
    assert project.catchments[1].shape_factor == 300
    assert Project.from_dict(project.to_dict()) == project
