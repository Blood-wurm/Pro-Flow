"""Qt-free Express layers: calculations, plot data and report HTML."""

from dataclasses import replace

import pytest

from proflow.engine.result import Status
from proflow.graph.express import (
    channel_outline,
    channel_rating_plot,
    channel_section_plot,
    weir_rating_plot,
    weir_section_plot,
)
from proflow.model.express import (
    METHOD_STATUS,
    ChannelInputs,
    WeirInputs,
    calculate_channel,
    calculate_weir,
)
from proflow.reports.express import report_html

# Published Express case EX DRAINAGEWAY SEC B-B @ Q100 (fixtures/express).
B_B = ChannelInputs(
    title="Sec B-B",
    section="trapezoidal",
    bottom_width=5.0,
    left_slope=9.0,
    right_slope=9.0,
    total_depth=2.5,
    invert_elevation=6892.10,
    slope_percent=1.5,
    n=0.050,
    compute_by="known_q",
    known_q=21.33,
)
FOREBAY = WeirInputs(
    title="Forebay notch", bottom_length=0.9, total_depth=1.5, known_q=5.25
)


def test_exact_and_stepped_channel():
    exact = calculate_channel(B_B)
    stepped = calculate_channel(replace(B_B, depth_reporting="express_stepped"))
    assert exact.method == "channel.manning.known_q/1"
    assert exact.state.depth == pytest.approx(0.7819, abs=1e-4)
    assert stepped.method == "channel.manning.known_q.stepped/1"
    assert stepped.state.depth == pytest.approx(0.79)
    assert "Exact" in exact.depth_reporting
    assert "rounded up to the next 0.01 ft" in stepped.depth_reporting
    assert any("0.7819" in n for n in stepped.notes)


def test_channel_rating_highlights_last_row():
    calc = calculate_channel(replace(B_B, compute_by="rating", increments=5))
    assert len(calc.rows) == 5 and calc.highlighted == 4
    assert calc.state.depth == pytest.approx(2.5)


def test_section_shape_follows_section_type():
    tri = replace(B_B, section="triangular")
    rect = replace(B_B, section="rectangular")
    assert tri.shape().bottom_width == 0
    assert rect.shape().left_slope == rect.shape().right_slope == 0


@pytest.mark.parametrize(
    "change,status",
    [
        ({"known_q": 5000.0}, Status.UNSUPPORTED_REGIME),
        ({"slope_percent": 0.0}, Status.UNSUPPORTED_REGIME),
        ({"n": 0.0}, Status.INVALID_INPUT),
        ({"section": "parabolic"}, Status.INVALID_INPUT),
        ({"depth_reporting": "rounded"}, Status.INVALID_INPUT),
    ],
)
def test_channel_failures_are_explicit(change, status):
    calc = calculate_channel(replace(B_B, **change))
    assert calc.status is status and calc.state is None and calc.message


def test_weir_calculation_and_cw_override():
    calc = calculate_weir(FOREBAY)
    assert calc.state.depth == pytest.approx(1.4532, abs=1e-4)
    assert calc.warnings == ()
    over = calculate_weir(replace(FOREBAY, cw=3.0))
    assert any("overridden" in w for w in over.warnings)
    rating = calculate_weir(replace(FOREBAY, compute_by="rating", increments=10))
    assert len(rating.rows) == 10
    assert rating.rows[-1].egl > rating.rows[-1].depth


def test_channel_outline_and_section_plot():
    outline = channel_outline(B_B)
    assert outline == ((0.0, 2.5), (22.5, 0.0), (27.5, 0.0), (50.0, 2.5))
    spec = channel_section_plot(calculate_channel(B_B))
    names = [s.name for s in spec.series]
    assert names == ["Channel", "Water", "W.S.", "Critical depth, Yc", "EGL"]
    ws = next(s for s in spec.series if s.name == "W.S.")
    assert ws.points[0][1] == pytest.approx(6892.10 + 0.7819, abs=1e-4)
    assert spec.y_label == "Elev (ft)" and spec.x_label == "Station (ft)"


def test_plots_without_a_result_show_only_the_section():
    calc = calculate_channel(replace(B_B, known_q=5000.0))
    assert [s.name for s in channel_section_plot(calc).series] == ["Channel"]
    assert channel_rating_plot(calc) is None


def test_rating_plot_marks_reported_state():
    spec = channel_rating_plot(calculate_channel(B_B))
    marker = next(s for s in spec.series if s.style == "marker")
    assert marker.points == ((21.33, pytest.approx(0.7819, abs=1e-4)),)
    assert spec.x_label == "Q (cfs)"


def test_weir_plots():
    calc = calculate_weir(FOREBAY)
    assert [s.name for s in weir_section_plot(calc).series][:2] == ["Weir", "Water"]
    assert weir_rating_plot(calc).note == "Cw = 3.33"


def test_report_shows_status_method_depths_units_and_warnings():
    html = report_html(
        calculate_channel(replace(B_B, depth_reporting="express_stepped"))
    )
    for text in (
        METHOD_STATUS,
        "channel.manning.known_q.stepped/1",
        "rounded up to the next 0.01 ft",
        "cfs",
        "ft/s",
        "ft²",
        "Warnings: none.",
        "Exact normal depth 0.7819 ft",
        "k = 1.486",
    ):
        assert text in html, text


def test_report_for_a_failed_calculation():
    html = report_html(calculate_channel(replace(B_B, known_q=5000.0)))
    assert "unsupported_regime" in html and "capacity" in html
    assert "Cross-section" not in html  # no images supplied


def test_report_lists_warnings():
    calc = calculate_weir(replace(FOREBAY, cw=3.0))
    html = report_html(calc)
    assert "Warnings" in html and "overridden" in html
