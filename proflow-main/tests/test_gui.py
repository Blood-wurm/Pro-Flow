"""Offscreen smoke tests of the desktop app: shell, channel and weir panels.

Skipped when PySide6 is not installed, unless PROFLOW_REQUIRE_GUI is set (CI
sets it, so a missing GUI install fails the run instead of skipping).
"""

import os

import pytest

if os.environ.get("PROFLOW_REQUIRE_GUI"):
    import PySide6  # noqa: F401  (fail loudly)
else:
    pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from proflow.gui import style  # noqa: E402
from proflow.gui.app import MainWindow  # noqa: E402
from proflow.gui.channel_panel import CHANNEL_EXAMPLE, ChannelPanel  # noqa: E402
from proflow.gui.plots import nice_ticks  # noqa: E402
from proflow.gui.report import export_html, export_pdf  # noqa: E402
from proflow.gui.weir_panel import WEIR_EXAMPLE, WeirPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    style.apply(instance)
    return instance


@pytest.mark.parametrize(
    "low,high", [(6887.0, 6887.69), (0.0, 2.5), (-0.3, 5.1), (0.0, 1064.0)]
)
def test_ticks_cover_the_data(low, high):
    ticks = nice_ticks(low, high)
    assert ticks[0] <= low and ticks[-1] >= high


# --- shell -------------------------------------------------------------------


def test_shell_switches_between_calculators(app):
    w = MainWindow()
    assert isinstance(w.current, ChannelPanel)
    w.nav_buttons["Weir"].click()
    assert isinstance(w.current, WeirPanel)
    assert (
        w.nav_buttons["Weir"].isChecked() and not w.nav_buttons["Channel"].isChecked()
    )
    assert w.windowTitle() == "Pro-Flow · Express · Weir"


# --- channel -----------------------------------------------------------------


def test_channel_calculates_and_shows_mode(app):
    p = ChannelPanel()
    assert p.calc.ok
    assert p._value_labels["depth"].text() == "0.782"
    assert p.depth_chip_label.text() == "Exact depths"
    assert p.method_chip.text() == "channel.manning.known_q/1"
    p.depth_reporting.setCurrentIndex(1)
    assert p._value_labels["depth"].text() == "0.790"
    assert p.depth_chip_label.text() == "Express stepped depths"
    assert "stepped" in p.method_chip.text()


def test_channel_form_follows_section_and_mode(app):
    p = ChannelPanel()
    p.section.setCurrentIndex(1)  # triangular
    assert not p.bottom_width.isEnabled() and p.left_slope.isEnabled()
    p.compute_by.setCurrentIndex(2)  # Q vs. depth
    assert p.mode_label.text() == "Increments"
    assert p.table_card.isVisibleTo(p) and p.table.rowCount() == 10


def test_channel_rating_curve_on_screen(app):
    p = ChannelPanel()
    spec = p.rating_plot._spec
    assert spec.x_label == "Q (cfs)" and spec.y_label == "Depth (ft)"
    marker = next(s for s in spec.series if s.style == "marker")
    assert marker.points[0][0] == pytest.approx(21.33)
    assert [p.plot_tabs.tabText(i) for i in range(2)] == [
        "Cross-section",
        "Rating curve",
    ]


def test_channel_error_is_shown_not_hidden(app):
    p = ChannelPanel()
    p.known_q.setValue(5000.0)
    assert not p.calc.ok
    assert p.status.text().startswith("Not calculated")
    assert p._value_labels["depth"].text() == "–"
    assert p.rating_plot._spec is None


def test_selecting_a_table_row_moves_the_marker(app):
    p = ChannelPanel()
    p.compute_by.setCurrentIndex(2)
    p.table.selectRow(3)
    assert p.calc.highlighted == 3
    assert p._value_labels["depth"].text() == "1.000"
    marker = next(s for s in p.rating_plot._spec.series if s.style == "marker")
    assert marker.points[0][1] == pytest.approx(1.0)


# --- weir --------------------------------------------------------------------


def test_weir_reproduces_published_case(app):
    # Express "Forebay @ DP 4.3 Notch": depth 1.45, area 1.31, velocity 4.01.
    p = WeirPanel()
    assert p.calc.ok and p.method_chip.text() == "weir.rectangular/1"
    assert p._value_labels["depth"].text() == "1.453"
    assert p._value_labels["area"].text() == "1.308"
    assert p._value_labels["velocity"].text() == "4.014"
    assert p.depth_chip_label.text() == "Exact depths"


def test_weir_cw_default_and_override(app):
    p = WeirPanel()
    assert p.cw_default.isChecked() and not p.cw.isEnabled()
    p.crest.setCurrentIndex(1)  # broad
    assert p.cw.value() == pytest.approx(2.6)
    p.cw_default.setChecked(False)
    p.cw.setValue(3.5)  # head 1.41 ft, inside the 1.5 ft weir
    assert any("overridden" in w for w in p.calc.warnings)
    assert p.status.text() == "Calculated with warnings."
    p.cw.setValue(3.0)  # needs 1.56 ft: explicit failure, warning kept
    assert not p.calc.ok and any("overridden" in w for w in p.calc.warnings)


def test_weir_rating_table_and_curve(app):
    p = WeirPanel()
    p.compute_by.setCurrentIndex(2)
    assert p.table.rowCount() == 10
    headers = [
        p.table.horizontalHeaderItem(i).text() for i in range(p.table.columnCount())
    ]
    assert headers[0].startswith("Depth") and "Critical" not in " ".join(headers)
    assert p.rating_plot._spec.note == "Cw = 3.33"


def test_weir_head_over_total_depth_is_explicit(app):
    p = WeirPanel()
    p.known_q.setValue(50.0)
    assert not p.calc.ok and "total depth" in p.status.text()


# --- reports -----------------------------------------------------------------


@pytest.mark.parametrize("panel", [ChannelPanel, WeirPanel])
def test_report_preview_and_exports(app, tmp_path, panel):
    p = panel()
    p.tabs.setCurrentIndex(1)
    preview = p.preview.toPlainText()
    assert "Experimental: not validated for engineering use" in preview
    assert p.calc.method in preview
    export_pdf(p.calc, tmp_path / "r.pdf")
    export_html(p.calc, tmp_path / "r.html")
    assert (tmp_path / "r.pdf").read_bytes()[:5] == b"%PDF-"
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert html.count("data:image/png;base64,") == 2


def test_examples_are_the_published_cases():
    assert CHANNEL_EXAMPLE.known_q == 21.33 and WEIR_EXAMPLE.known_q == 5.25
