import json
from pathlib import Path

import numpy as np
import pytest

from proflow.calculate import calculate, results_document
from proflow.cli import EXIT_INVALID, EXIT_OK, main
from proflow.engine.storm_library import HUFF_Q1_POINT_C173, STANDARD_DISTRIBUTIONS
from proflow.engine.unit_hydrograph import CUFT_PER_INCH_ACRE, scs_runoff_hydrograph
from proflow.io.cds import MAX_RATIOS, CdsError, read_cds, write_cds
from proflow.io.project_json import load_project
from proflow.model.project import Project, ProjectError

HERE = Path(__file__).resolve().parent
HUFF_EXAMPLE = HERE.parent / "examples" / "scs-huff-q1.proflow.json"
HUFF_ID = "huff-q1-point-median-isws-c173-1990"


def _data():
    return json.loads(HUFF_EXAMPLE.read_text(encoding="utf-8"))


# --- the distribution --------------------------------------------------------


def test_registry_holds_only_sourced_distributions():
    assert set(STANDARD_DISTRIBUTIONS) == {HUFF_ID}
    d = STANDARD_DISTRIBUTIONS[HUFF_ID]
    assert "Circular 173" in d.source and "Table 3" in d.source
    assert "Bulletin 75" in d.status_note


def test_huff_scales_to_duration():
    curve = HUFF_Q1_POINT_C173.mass_curve(6 * 60)
    assert curve.duration == 360
    assert curve.fraction(18) == pytest.approx(0.16)  # 5 % of 6 h
    assert curve.fraction(180) == pytest.approx(0.82)  # 50 %
    # Linear on the cumulative curve between printed points.
    assert curve.fraction(27) == pytest.approx((0.16 + 0.33) / 2)


def test_huff_is_front_loaded():
    curve = HUFF_Q1_POINT_C173.mass_curve(100)
    increments = np.diff(curve.fractions)
    assert increments.argmax() == 1  # 5-10 % of storm time
    assert curve.fraction(25) == pytest.approx(0.60)


def test_duration_guidance():
    assert HUFF_Q1_POINT_C173.duration_warnings(360) == ()
    (w,) = HUFF_Q1_POINT_C173.duration_warnings(12 * 60)
    assert "6 h or less" in w and "Bulletin 71" in w


def test_bad_duration():
    with pytest.raises(ValueError):
        HUFF_Q1_POINT_C173.mass_curve(0)


# --- .cds files --------------------------------------------------------------


CDS = "10\n0.2\n0.5\n0.9\n1.0\n"


def test_read_cds_adds_zero_at_start():
    curve, interval = read_cds(CDS)
    assert interval == 10
    np.testing.assert_allclose(curve.times, [0, 10, 20, 30, 40])
    np.testing.assert_allclose(curve.fractions, [0, 0.2, 0.5, 0.9, 1.0])


def test_cds_round_trip():
    curve, interval = read_cds(CDS)
    back, back_interval = read_cds(write_cds(curve, interval))
    assert back_interval == interval
    np.testing.assert_array_equal(back.fractions, curve.fractions)


def test_write_cds_from_huff_at_any_interval():
    curve = HUFF_Q1_POINT_C173.mass_curve(180)
    back, _ = read_cds(write_cds(curve, 7))
    assert back.duration == 182  # first 7-min step at or after 180 min
    # Exact at the times the file samples (every 7 min).
    np.testing.assert_allclose(back.fractions[:-1], curve.fraction(back.times[:-1]))
    assert back.fractions[-1] == 1.0


@pytest.mark.parametrize(
    "text,message",
    [
        ("10\n", "at least one ratio"),
        ("0\n1.0\n", "interval must be positive"),
        ("10\n0.5\nabc\n1.0\n", "line 3"),
        ("10\n0.5\n\n1.0\n", "line 3"),  # blank line inside the data
        ("10\n0.6\n0.4\n1.0\n", "never decrease"),
        ("10\n0.5\n0.8\n", "end at 1"),
        ("1\n" + "0.5\n" * MAX_RATIOS + "1.0\n", "allows 2880"),
    ],
)
def test_read_cds_rejects(text, message):
    with pytest.raises(CdsError, match=message):
        read_cds(text)


def test_trailing_blank_lines_allowed():
    curve, _ = read_cds(CDS + "\n\n")
    assert curve.duration == 40


def test_write_cds_too_many_ratios():
    with pytest.raises(CdsError, match="2880"):
        write_cds(HUFF_Q1_POINT_C173.mass_curve(3000), 1)


# --- projects ----------------------------------------------------------------


def test_example_round_trips_exactly():
    project = load_project(HUFF_EXAMPLE)
    assert project.to_dict() == _data()
    assert project.storms[0].standard == HUFF_ID


def test_project_equals_direct_engine_call():
    project = load_project(HUFF_EXAMPLE)
    row = calculate(project)[0]
    direct = scs_runoff_hydrograph(
        area=20.0,
        cn=80,
        tc=15.0,
        storm=HUFF_Q1_POINT_C173.mass_curve(180),
        total_depth=1.55,
        dt=1.0,
    )
    np.testing.assert_array_equal(row.result.value.flows, direct.value.hydrograph.flows)


@pytest.mark.parametrize("form", ["curvilinear", "triangular"])
def test_runoff_volume_matches_cn_equation(form):
    results = [
        r
        for r in calculate(load_project(HUFF_EXAMPLE))
        if r.result.method.endswith(f"{form}/1")
    ]
    assert len(results) == 3
    for r in results:
        depth_in = r.quantities["runoff_depth"][0]
        expected = depth_in * 20 * CUFT_PER_INCH_ACRE
        assert r.result.value.volume == pytest.approx(expected, rel=0.01)
        assert not any("unit hydrograph holds" in w for w in r.result.warnings)


def test_forms_stay_distinct_and_labeled():
    project = load_project(HUFF_EXAMPLE)
    rows = results_document(project, calculate(project))["results"]
    assert {r["method"] for r in rows} == {
        "scs.uh.curvilinear/1",
        "scs.uh.triangular/1",
    }
    for r in rows:
        assert r["storm_distribution"] == HUFF_ID
        assert "Circular 173" in r["storm_source"]
        assert "Bulletin 75" in r["storm_source_status"]


def test_long_huff_storm_warns():
    data = _data()
    data["rainfall"]["storms"][0]["distribution"]["duration"] = {
        "value": 12,
        "unit": "hr",
    }
    r = calculate(Project.from_dict(data))[0]
    assert r.result.ok and any("6 h or less" in w for w in r.result.warnings)


def test_metric_duration_and_depth():
    data = _data()
    storm = data["rainfall"]["storms"][0]
    storm["distribution"]["duration"] = {"value": 180, "unit": "min"}
    storm["depths"][0]["depth"] = {"value": 1.55 * 25.4, "unit": "mm"}
    a = calculate(Project.from_dict(data))[0].result.value.peak
    b = calculate(load_project(HUFF_EXAMPLE))[0].result.value.peak
    assert a == pytest.approx(b)


@pytest.mark.parametrize(
    "dist,path,message",
    [
        (
            {"standard": "type-ii", "duration": {"value": 24, "unit": "hr"}},
            ".standard",
            "unknown distribution",
        ),
        ({"standard": HUFF_ID}, ".duration", "required"),
        (
            {"standard": HUFF_ID, "duration": {"value": 0, "unit": "hr"}},
            ".duration",
            "positive",
        ),
        (
            {"standard": HUFF_ID, "duration": {"value": 3, "unit": "in"}},
            ".duration",
            "not valid for time",
        ),
        (
            {
                "standard": HUFF_ID,
                "duration": {"value": 3, "unit": "hr"},
                "fractions": [0, 1],
            },
            ".fractions",
            "unknown field",
        ),
    ],
)
def test_standard_storm_validation(dist, path, message):
    data = _data()
    data["rainfall"]["storms"][0]["distribution"] = dist
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    problems = dict(info.value.problems)
    key = "rainfall.storms[0].distribution" + path
    assert key in problems, problems
    assert message in problems[key]


# --- CLI ---------------------------------------------------------------------


def test_cli_lists_sources(capsys):
    assert main(["storm", "list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert HUFF_ID in out and "Circular 173" in out and "Bulletin 75" in out


def test_cli_import_cds_into_project(tmp_path):
    cds = tmp_path / "local.cds"
    cds.write_text(CDS, encoding="utf-8")
    out = tmp_path / "storm.json"
    args = ["storm", "import-cds", str(cds), "--id", "local", "--depth", "2=1.55",
            "--depth", "10=4.0", "--depth", "100=8", "-o", str(out)]  # fmt: skip
    assert main(args) == EXIT_OK
    storm = json.loads(out.read_text(encoding="utf-8"))
    assert storm["distribution"]["times"]["values"] == [0, 10, 20, 30, 40]
    data = _data()
    data["rainfall"]["storms"].append(storm)
    data["catchments"][0]["storm"] = "local"
    results = calculate(Project.from_dict(data))
    assert all(r.result.ok for r in results)


def test_cli_import_cds_rejects_bad_file(tmp_path):
    bad = tmp_path / "bad.cds"
    bad.write_text("10\n0.5\n0.4\n", encoding="utf-8")
    args = ["storm", "import-cds", str(bad), "--id", "x", "-o", str(tmp_path / "o")]
    assert main(args) == EXIT_INVALID


def test_cli_export_cds(tmp_path):
    out = tmp_path / "huff.cds"
    args = ["storm", "export-cds", str(HUFF_EXAMPLE), "--storm", "huff-q1-3h",
            "--interval", "5", "-o", str(out)]  # fmt: skip
    assert main(args) == EXIT_OK
    curve, interval = read_cds(out.read_text(encoding="utf-8"))
    assert interval == 5 and curve.duration == 180
    assert curve.fraction(45) == pytest.approx(0.60)  # 25 % of 3 h
    assert curve.fraction(90) == pytest.approx(0.82)  # 50 % of 3 h
