"""Plot data for the Express channel and weir calculators.

A PlotSpec is UI-independent: series of (x, y) points with a drawing style.
proflow.gui.plots paints it with Qt, on screen and into reports.
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine import channel
from proflow.model.express import Calculation, ChannelInputs, WeirInputs

STYLES = ("outline", "water", "line", "dash", "dot", "marker")


@dataclass(frozen=True)
class Series:
    name: str
    points: tuple[tuple[float, float], ...]
    style: str  # one of STYLES


@dataclass(frozen=True)
class PlotSpec:
    title: str
    x_label: str
    y_label: str
    series: tuple[Series, ...]
    note: str = ""


def _xs(points) -> tuple[tuple[float, float], ...]:
    return tuple((float(x), float(y)) for x, y in points)


# --- channel -----------------------------------------------------------------


def channel_outline(x: ChannelInputs) -> tuple[tuple[float, float], ...]:
    """Bank-to-bank section, station from the left top of bank, depth above invert."""
    s, d = x.shape(), x.total_depth
    left_toe = s.left_slope * d
    right_toe = left_toe + s.bottom_width
    return _xs(
        [(0, d), (left_toe, 0), (right_toe, 0), (right_toe + s.right_slope * d, d)]
    )


def _banks(x: ChannelInputs, y: float) -> tuple[float, float]:
    s, d = x.shape(), x.total_depth
    left = s.left_slope * (d - y)
    right = s.left_slope * d + s.bottom_width + s.right_slope * y
    return left, right


def channel_section_plot(calc: Calculation) -> PlotSpec:
    x: ChannelInputs = calc.inputs
    z0 = x.invert_elevation
    elev = lambda pts: _xs((px, py + z0) for px, py in pts)  # noqa: E731
    series = [Series("Channel", elev(channel_outline(x)), "outline")]
    state = calc.state
    if state is not None:
        y = min(state.depth, x.total_depth)
        left, right = _banks(x, y)
        s = x.shape()
        toe_l, toe_r = (
            s.left_slope * x.total_depth,
            s.left_slope * x.total_depth + s.bottom_width,
        )
        water = [(left, y), (toe_l, 0), (toe_r, 0), (right, y)]
        series.append(Series("Water", elev(water), "water"))
        series.append(Series("W.S.", elev([(left, y), (right, y)]), "line"))
        for name, depth, style in (
            ("Critical depth, Yc", state.critical_depth, "dot"),
            ("EGL", state.egl, "dash"),
        ):
            if 0 < depth <= x.total_depth * 1.5:
                a, b = _banks(x, min(depth, x.total_depth))
                series.append(Series(name, elev([(a, depth), (b, depth)]), style))
    title = x.title or f"{x.section.capitalize()} channel"
    y_label = "Elev (ft)" if z0 else "Depth (ft)"
    return PlotSpec(title, "Station (ft)", y_label, tuple(series))


def channel_rating_plot(calc: Calculation, points: int = 50) -> PlotSpec | None:
    """Q vs. depth from zero to the total depth, with the reported state marked."""
    x: ChannelInputs = calc.inputs
    if not calc.ok:
        return None
    s, slope = x.shape(), x.slope_percent / 100
    curve = [
        (
            channel.manning_flow(s, x.total_depth * k / points, slope, x.n),
            x.total_depth * k / points,
        )
        for k in range(points + 1)
    ]
    series = [Series("Normal depth", _xs(curve), "line")]
    state = calc.state
    if state is not None:
        series.append(Series("Reported", _xs([(state.flow, state.depth)]), "marker"))
    note = "Manning, k = 1.486"
    return PlotSpec("Rating curve", "Q (cfs)", "Depth (ft)", tuple(series), note)


# --- weir --------------------------------------------------------------------


def weir_outline(x: WeirInputs) -> tuple[tuple[float, float], ...]:
    """Notch in a plate: crest at depth 0 from 0 to L, walls up to the total depth."""
    pad, d, length = max(0.25 * x.bottom_length, 0.5), x.total_depth, x.bottom_length
    return _xs([(-pad, d), (0, d), (0, 0), (length, 0), (length, d), (length + pad, d)])


def weir_section_plot(calc: Calculation) -> PlotSpec:
    x: WeirInputs = calc.inputs
    series = [Series("Weir", weir_outline(x), "outline")]
    state = calc.state
    if state is not None:
        h, length = state.depth, x.bottom_length
        series.append(
            Series("Water", _xs([(0, h), (0, 0), (length, 0), (length, h)]), "water")
        )
        series.append(Series("W.S.", _xs([(0, h), (length, h)]), "line"))
        if state.egl <= x.total_depth * 1.5:
            series.append(
                Series("EGL", _xs([(0, state.egl), (length, state.egl)]), "dash")
            )
    title = x.title or f"Rectangular weir, {x.crest} crest"
    return PlotSpec(title, "Length (ft)", "Depth (ft)", tuple(series))


def weir_rating_plot(calc: Calculation, points: int = 50) -> PlotSpec | None:
    x: WeirInputs = calc.inputs
    if not calc.ok:
        return None
    cw, length = x.weir_coefficient, x.bottom_length
    curve = [
        (cw * length * (x.total_depth * k / points) ** 1.5, x.total_depth * k / points)
        for k in range(points + 1)
    ]
    series = [Series("Q = Cw L H^1.5", _xs(curve), "line")]
    state = calc.state
    if state is not None:
        series.append(Series("Reported", _xs([(state.flow, state.depth)]), "marker"))
    return PlotSpec(
        "Rating curve", "Q (cfs)", "Depth (ft)", tuple(series), f"Cw = {cw:g}"
    )


def section_plot(calc: Calculation) -> PlotSpec:
    return (
        channel_section_plot(calc)
        if calc.kind == "channel"
        else weir_section_plot(calc)
    )


def rating_plot(calc: Calculation) -> PlotSpec | None:
    return (
        channel_rating_plot(calc) if calc.kind == "channel" else weir_rating_plot(calc)
    )
