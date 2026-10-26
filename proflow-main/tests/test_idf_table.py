from pathlib import Path

import numpy as np
import pytest

from proflow.engine.idf import FhaCurve
from proflow.fixtures import displayed_tolerance
from proflow.io.idf_table import (
    IdfTable,
    IdfTableError,
    read_noaa_pfds,
    read_proflow_table,
    read_table,
    table_from_curves,
    write_proflow_table,
)

DATA = Path(__file__).resolve().parent / "data"
DEPTH = DATA / "noaa-atlas14-wichita-ks-depth.csv"
INTENSITY = DATA / "noaa-atlas14-wichita-ks-intensity.csv"
METRIC = DATA / "noaa-atlas14-wichita-ks-depth-metric.csv"


def _raw_rows(path):
    """{duration label: [value text, ...]} as printed."""
    rows, started = {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("by duration"):
            started = True
            continue
        if started and line.strip():
            label, *values = (c.strip() for c in line.split(","))
            rows[label] = values
        elif started:
            break
    return rows


def test_noaa_depth_file_structure():
    table = read_table(DEPTH)
    assert table.return_periods == (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000)
    assert table.durations[:5].tolist() == [5, 10, 15, 30, 60]
    assert table.durations[-1] == 60 * 1440  # 60-day
    assert table.source["Data type"] == "Precipitation depth"
    assert table.source["Time series type"] == "Partial duration"
    # 5-min, 100-yr depth 0.942 in -> 11.304 in/hr.
    assert table.row(100)[0] == pytest.approx(0.942 * 12)


# Cells where NOAA's intensity file is not its depth file divided by the
# duration, even allowing for both files' rounding (all at 3, 6 and 12 h; the
# largest is 0.55 %, 6-hr 200-yr). Pro-Flow converts by definition, i = P / t.
NOAA_INCONSISTENT = {
    ("3-hr:", 5), ("6-hr:", 25), ("6-hr:", 50), ("6-hr:", 200), ("12-hr:", 2),
    ("12-hr:", 5), ("12-hr:", 10), ("12-hr:", 25), ("12-hr:", 50), ("12-hr:", 100),
    ("12-hr:", 200), ("12-hr:", 500),
}  # fmt: skip


def test_depth_conversion_matches_noaa_intensity_file():
    """NOAA's own intensity file is the check on depth / duration.

    Both files are rounded to 3 significant figures from the same estimates,
    so the allowed difference is half the intensity's last digit plus half the
    depth's last digit divided by the duration in hours. The cells in
    NOAA_INCONSISTENT break that bound in the source itself; they must stay
    within 0.6 % and stay the only ones.
    """
    from_depth = read_table(DEPTH)
    noaa = read_table(INTENSITY)
    np.testing.assert_array_equal(from_depth.durations, noaa.durations)
    depth_text, intensity_text = _raw_rows(DEPTH), _raw_rows(INTENSITY)
    outside = set()
    for j, label in enumerate(depth_text):
        hours = from_depth.durations[j] / 60
        for k, rp in enumerate(from_depth.return_periods):
            tol = (
                displayed_tolerance(intensity_text[label][k])
                + displayed_tolerance(depth_text[label][k]) / hours
            )
            got, want = from_depth.row(rp)[j], noaa.row(rp)[j]
            if abs(got - want) > tol * (1 + 1e-9):
                outside.add((label, rp))
                assert abs(got - want) / want < 0.006, (label, rp, got, want)
    assert outside == NOAA_INCONSISTENT


def test_metric_file_agrees_with_english():
    english, metric = read_table(DEPTH), read_table(METRIC)
    depth_text, mm_text = _raw_rows(DEPTH), _raw_rows(METRIC)
    for j, label in enumerate(depth_text):
        hours = english.durations[j] / 60
        for k, rp in enumerate(english.return_periods):
            tol = (
                displayed_tolerance(depth_text[label][k])
                + displayed_tolerance(mm_text[label][k]) / 25.4
            ) / hours
            assert abs(english.row(rp)[j] - metric.row(rp)[j]) <= tol * (1 + 1e-9)


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda t: t.replace("(inches)", "(furlongs)"), "title line"),
        (
            lambda t: t.replace("Precipitation depth", "Precipitation intensity"),
            "does not match",
        ),
        (lambda t: t.replace("ARI (years)", "AEP (1-in-Y)"), "unsupported header"),
        (lambda t: t.replace("5-min:", "5-minutes:"), "unrecognized duration"),
        (lambda t: t.replace("0.428,", "0.428,0.1,"), "values for"),
        (lambda t: t.replace("0.428", "n/a"), "not a number"),
    ],
)
def test_noaa_reader_rejects_unexpected_layout(mutate, message):
    with pytest.raises(IdfTableError, match=message):
        read_noaa_pfds(mutate(DEPTH.read_text(encoding="utf-8")))


def test_proflow_table_round_trip_in_other_units():
    table = read_table(DEPTH).window(5, 60)
    text = write_proflow_table(table, duration_unit="hr", intensity_unit="mm/hr")
    back = read_proflow_table(text)
    np.testing.assert_allclose(back.durations, table.durations)
    np.testing.assert_allclose(back.intensities, table.intensities, rtol=1e-5)
    assert back.return_periods == table.return_periods


def test_proflow_table_requires_units_and_format():
    good = "# proflow-idf-table/1\n# duration_unit: min\n# intensity_unit: in/hr\n"
    good += "duration,2,10\n5,5.5,7.4\n15,3.8,5.2\n"
    assert read_proflow_table(good).row(10)[1] == 5.2
    with pytest.raises(IdfTableError, match="intensity_unit"):
        read_proflow_table(good.replace("# intensity_unit: in/hr\n", ""))
    with pytest.raises(IdfTableError, match="first line"):
        read_proflow_table(good.replace("proflow-idf-table/1", "something-else"))
    with pytest.raises(IdfTableError, match="not valid for intensity"):
        read_proflow_table(good.replace("in/hr", "ft"))
    with pytest.raises(IdfTableError, match="values for"):
        read_proflow_table(good.replace("15,3.8,5.2", "15,3.8"))


def test_table_from_curves_matches_equation():
    curves = {2: FhaCurve(76.3137, 14.3, 0.8844), 100: FhaCurve(62.2794, 10.1, 0.6624)}
    table = table_from_curves(curves, [5, 30, 60])
    assert table.row(100)[1] == pytest.approx(62.2794 / 40.1**0.6624)


def test_window_and_shape_checks():
    table = read_table(DEPTH)
    assert table.window(5, 60).durations.tolist() == [5, 10, 15, 30, 60]
    with pytest.raises(IdfTableError):
        IdfTable(np.array([5.0, 10.0]), (2,), np.zeros((2, 2)))
    with pytest.raises(IdfTableError, match="no 3-yr"):
        table.row(3)
