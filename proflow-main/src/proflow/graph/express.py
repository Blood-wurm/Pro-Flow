"""Plot data for the Express channel and weir calculators.

A PlotSpec is UI-independent: series of (x, y) points with a drawing style.
proflow.gui.plots paints it with Qt, on screen and into reports.

Every channel section and weir shape gives its ground (or notch) profile as a
polyline; the water is that profile clipped at the water level, so one routine
draws pipes, gutters, user-defined sections and every weir type.
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine import channel
from proflow.model.express import (
    SECTION_LABELS,
    WEIR_LABELS,
    Calculation,
    ChannelInputs,
    WeirInputs,
)

STYLES = ("outline", "water", "line", "dash", "dot", "marker")
Point = tuple[float, float]


@dataclass(frozen=True)
class Series:
    name: str
    points: tuple[Point, ...]
    style: str  # one of STYLES


@dataclass(frozen=True)
class PlotSpec:
    title: str
    x_label: str
    y_label: str
    series: tuple[Series, ...]
    note: str = ""


def _xs(points) -> tuple[Point, ...]:
    return tuple((float(x), float(y)) for x, y in points)


def wet_polygons(profile: list[Point], level: float) -> list[list[Point]]:
    """Regions below `level` bounded by the profile, one polygon per pool."""
    pools, run = [], []
    for (x0, y0), (x1, y1) in zip(profile, profile[1:]):
        below0, below1 = y0 < level, y1 < level
        if below0 and not run:
            run = [(x0, level), (x0, y0)]
        if below0 != below1:
            cross = x0 + (x1 - x0) * (level - y0) / (y1 - y0)
            if below0:
                run.append((cross, level))
                pools.append(run)
                run = []
            else:
                run = [(cross, level)]
        if below1:
            run.append((x1, y1))
    if run:  # the profile ended under water: close at its last point
        run.append((profile[-1][0], level))
        pools.append(run)
    return [p for p in pools if len(p) >= 3]


def _span(profile: list[Point], level: float) -> tuple[float, float]:
    """Water-surface width at `level`: first to last waterline crossing.

    Each pool starts and ends on the waterline; its other vertices are the
    wetted boundary, which can bulge wider (a pipe below its crown).
    """
    pools = wet_polygons(profile, level)
    if not pools:
        xs = [x for x, _ in profile]
        return min(xs), max(xs)
    return pools[0][0][0], pools[-1][-1][0]


def _water_series(profile, depth, critical, egl, z0=0.0) -> list[Series]:
    def lift(pts):
        return _xs((x, y + z0) for x, y in pts)

    series = []
    pools = wet_polygons(profile, depth)
    for i, pool in enumerate(pools):
        series.append(Series("Water" if i == 0 else "", lift(pool), "water"))
    for i, pool in enumerate(pools):
        surface = [(pool[0][0], depth), (pool[-1][0], depth)]
        series.append(Series("W.S." if i == 0 else "", lift(surface), "line"))
    top = max(y for _, y in profile)
    for name, level, style in (
        ("Critical depth, Yc", critical, "dot"),
        ("EGL", egl, "dash"),
    ):
        if level is not None and 0 < level <= top * 1.5:
            a, b = _span(profile, min(level, top))
            series.append(Series(name, lift([(a, level), (b, level)]), style))
    return series


# --- channel -----------------------------------------------------------------


def _channel_depth(x: ChannelInputs, calc: Calculation) -> float:
    shape = x.shape()
    if shape.max_depth is not None:
        return shape.max_depth
    if x.section == "gutter":
        # Size the drawing to the flow, not to a total depth gutters don't use.
        s = calc.state
        if s is not None:
            return 1.5 * max(s.depth, s.critical_depth)
        return x.total_depth
    return x.total_depth


def channel_outline(x: ChannelInputs, depth: float | None = None) -> tuple[Point, ...]:
    """Section profile in station (ft) and depth above invert (ft)."""
    d = depth if depth is not None else (x.shape().max_depth or x.total_depth)
    return _xs(x.shape().profile(d))


def channel_section_plot(calc: Calculation) -> PlotSpec:
    x: ChannelInputs = calc.inputs
    z0 = x.invert
    depth = _channel_depth(x, calc)
    profile = x.shape().profile(depth)
    series = [Series("Channel", _xs((px, py + z0) for px, py in profile), "outline")]
    state = calc.state
    if state is not None:
        series += _water_series(
            profile, state.depth, state.critical_depth, state.egl, z0
        )
    title = x.title or f"{SECTION_LABELS.get(x.section, x.section)} channel"
    y_label = "Elev (ft)" if z0 else "Depth (ft)"
    return PlotSpec(title, "Station (ft)", y_label, tuple(series))


def channel_rating_plot(calc: Calculation, points: int = 50) -> PlotSpec | None:
    """Q vs. depth from zero to the section's depth, with the reported state marked."""
    x: ChannelInputs = calc.inputs
    if not calc.ok:
        return None
    shape, slope = x.shape(), x.slope_percent / 100
    top = _channel_depth(x, calc)
    curve = [
        (channel.manning_flow(shape, top * k / points, slope, x.n), top * k / points)
        for k in range(points + 1)
    ]
    series = [Series("Normal depth", _xs(curve), "line")]
    state = calc.state
    if state is not None:
        series.append(Series("Reported", _xs([(state.flow, state.depth)]), "marker"))
    law = {
        "hec22": "HEC-22 gutter, Kc = 0.56",
        "manning.composite": "Manning, composite n",
    }
    note = law.get(shape.flow_law, "Manning, k = 1.486")
    return PlotSpec("Rating curve", "Q (cfs)", "Depth (ft)", tuple(series), note)


# --- weir --------------------------------------------------------------------


def weir_outline(x: WeirInputs) -> tuple[Point, ...]:
    """Weir opening profile: crest at depth 0, up to the total depth."""
    return _xs(x.shape().profile(x.total_depth))


def weir_section_plot(calc: Calculation) -> PlotSpec:
    x: WeirInputs = calc.inputs
    profile = x.shape().profile(x.total_depth)
    series = [Series("Weir", _xs(profile), "outline")]
    state = calc.state
    if state is not None:
        series += _water_series(profile, state.depth, None, state.egl)
    label = WEIR_LABELS.get(x.weir_type, x.weir_type)
    title = x.title or f"{label} weir, {x.crest} crest"
    return PlotSpec(title, "Length (ft)", "Depth (ft)", tuple(series))


def weir_rating_plot(calc: Calculation, points: int = 50) -> PlotSpec | None:
    x: WeirInputs = calc.inputs
    if not calc.ok:
        return None
    shape = x.shape()
    top = min(x.total_depth, getattr(shape, "diameter", x.total_depth))
    low = shape.min_head()
    heads = [low + (top - low) * k / points for k in range(points + 1)]
    series = [Series("Q vs. head", _xs((shape.flow(h), h) for h in heads), "line")]
    state = calc.state
    if state is not None:
        series.append(Series("Reported", _xs([(state.flow, state.depth)]), "marker"))
    return PlotSpec(
        "Rating curve", "Q (cfs)", "Depth (ft)", tuple(series), f"Cw = {shape.cw:.4g}"
    )


def section_plot(calc: Calculation) -> PlotSpec:
    if calc.kind == "channel":
        return channel_section_plot(calc)
    return weir_section_plot(calc)


def rating_plot(calc: Calculation) -> PlotSpec | None:
    if calc.kind == "channel":
        return channel_rating_plot(calc)
    return weir_rating_plot(calc)
