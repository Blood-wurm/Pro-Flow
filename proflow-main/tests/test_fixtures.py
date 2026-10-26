import json

import pytest

from proflow import fixtures
from proflow.fixtures import (
    FixtureError,
    discover,
    displayed_tolerance,
    failed,
    load_fixture,
    run_fixture,
)

PUBLIC = {f.id: f for f in discover(fixtures.FIXTURE_DIR / "public")}


@pytest.mark.parametrize(
    "fixture_id",
    ["express-rectangular-weir-forebay", "hydrographs-rational-ex-dp-7-5yr"],
)
def test_complete_public_cases_pass(fixture_id):
    result = run_fixture(PUBLIC[fixture_id])
    assert result.fixture.completeness == "complete"
    assert result.status == "pass", fixtures.format_results([result])


def test_storm_sewers_case_is_informational():
    result = run_fixture(PUBLIC["storm-one-line-outfall-100yr"])
    assert result.status == "informational"
    assert {c.status for c in result.checks} == {"info", "not_computed"}
    assert not failed([result])


def test_every_public_fixture_records_its_source():
    for f in PUBLIC.values():
        assert f.source["url"].startswith("https://")
        assert f.source["local_pdf"].startswith("reference/public_cases/")
        assert len(f.source["sha256"]) == 64
        assert f.completeness == "complete" or f.missing


@pytest.mark.parametrize(
    "text,tol", [("1.45", 0.005), ("5.250", 0.0005), ("9884", 0.5), ("7.4", 0.05)]
)
def test_displayed_tolerance(text, tol):
    assert displayed_tolerance(text) == pytest.approx(tol)


def _write(tmp_path, **overrides):
    data = json.loads(
        (fixtures.FIXTURE_DIR / "public" / "express-rectangular-weir.json").read_text()
    )
    data.update(overrides)
    path = tmp_path / "case.json"
    path.write_text(json.dumps(data))
    return path


def test_wrong_expected_value_fails(tmp_path):
    expected = {"depth": {"value": "1.50", "unit": "ft"}}
    result = run_fixture(load_fixture(_write(tmp_path, expected=expected)))
    assert result.status == "fail"
    assert failed([result])


def test_expected_value_in_other_unit(tmp_path):
    # 1.453 ft = 17.44 in.
    expected = {"depth": {"value": "17.4", "unit": "in"}}
    assert run_fixture(load_fixture(_write(tmp_path, expected=expected))).status == (
        "pass"
    )


def test_complete_case_cannot_omit_inputs(tmp_path):
    with pytest.raises(FixtureError, match="lacks inputs"):
        load_fixture(_write(tmp_path, inputs={"crest": "sharp"}))


def test_expected_values_must_keep_displayed_precision(tmp_path):
    with pytest.raises(FixtureError, match="string"):
        load_fixture(
            _write(tmp_path, expected={"depth": {"value": 1.45, "unit": "ft"}})
        )


def test_solver_refusal_is_an_error(tmp_path):
    inputs = json.loads(
        (fixtures.FIXTURE_DIR / "public" / "express-rectangular-weir.json").read_text()
    )["inputs"]
    inputs["flow"] = {"value": 50, "unit": "cfs"}  # needs more than 1.5 ft of head
    result = run_fixture(load_fixture(_write(tmp_path, inputs=inputs)))
    assert result.status == "error" and "unsupported_regime" in result.message
