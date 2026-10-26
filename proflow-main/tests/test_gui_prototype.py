"""Offscreen smoke test of the prototype Express channel screen."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from proflow.gui import style  # noqa: E402
from proflow.gui.channel_screen import EXAMPLE, ChannelScreen  # noqa: E402
from proflow.gui.plots import nice_ticks  # noqa: E402
from proflow.gui.report import export_html, export_pdf  # noqa: E402


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


def test_screen_calculates_and_shows_mode(app):
    w = ChannelScreen()
    assert w.calc.ok
    assert w._value_labels["depth"].text() == "0.782"
    assert w.depth_chip.text() == "Exact depths"
    assert w.method_chip.text() == "channel.manning.known_q/1"
    w.depth_reporting.setCurrentIndex(1)
    assert w._value_labels["depth"].text() == "0.790"
    assert w.depth_chip.text() == "Express stepped depths"
    assert "stepped" in w.method_chip.text()


def test_form_follows_section_and_mode(app):
    w = ChannelScreen()
    w.section.setCurrentIndex(1)  # triangular
    assert not w.bottom_width.isEnabled() and w.left_slope.isEnabled()
    w.compute_by.setCurrentIndex(2)  # Q vs. depth
    assert w.mode_label.text() == "Increments"
    assert w.table_card.isVisibleTo(w) and w.table.rowCount() == 10


def test_error_is_shown_not_hidden(app):
    w = ChannelScreen()
    w.known_q.setValue(5000.0)
    assert not w.calc.ok
    assert w.status.text().startswith("Not calculated")
    assert w._value_labels["depth"].text() == "–"


def test_report_exports(app, tmp_path):
    w = ChannelScreen(EXAMPLE)
    export_pdf(w.calc, tmp_path / "r.pdf")
    export_html(w.calc, tmp_path / "r.html")
    assert (tmp_path / "r.pdf").read_bytes()[:5] == b"%PDF-"
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert html.count("data:image/png;base64,") == 2
    assert "Experimental" in html
