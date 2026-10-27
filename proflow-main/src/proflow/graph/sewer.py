"""Profile plot data along a storm sewer route.

A route runs from a chosen pipe down to the outfall. Distance is measured
between junction centres from the outfall; when every pipe on the route lies
on one PFSUITE line with membership stations, the line's stations are used
instead. The standard step solves the two ends of each line only, so the
HGL and EGL are straight along a line; the step at each upstream end is that
line's junction loss, and the next line upstream starts from it.
"""

from __future__ import annotations

from proflow.calculate import LineResult
from proflow.engine.sewer import TAILWATER_LABELS
from proflow.graph.express import PlotSpec, Series
from proflow.model.network import Network
from proflow.model.topology import Topology


def _station(structure, line: str) -> float | None:
    for m in structure.source.get("attributes", {}).get("lines", []):
        if m.get("line") == line:
            return m.get("station")
    return None


def _positions(net: Network, route: list[str]) -> tuple[dict[str, float], str]:
    """Structure id -> x along the route (outfall pipe first), and the label."""
    ids = [net.pipe(route[0]).downstream] + [net.pipe(p).upstream for p in route]
    lines = {net.pipe(p).source.get("attributes", {}).get("line") for p in route}
    if len(lines) == 1 and None not in lines:
        (line,) = lines
        stations = {sid: _station(net.structure(sid), line) for sid in ids}
        if None not in stations.values():
            return stations, f"Station on {line} (ft)"
    x, out = 0.0, {ids[0]: 0.0}
    for pid in route:
        x += net.pipe(pid).length.internal("length")
        out[net.pipe(pid).upstream] = x
    return out, "Distance from outfall (ft)"


def route_profile(
    net: Network,
    topo: Topology,
    results: dict[str, LineResult],
    pipe_id: str,
) -> PlotSpec:
    route = list(reversed(topo.route(pipe_id)))  # outfall pipe first
    xs, x_label = _positions(net, route)
    water, outline, hgl, egl, critical, rims = [], [], [], [], [], []
    start = None
    for k, pid in enumerate(route):
        pipe = net.pipe(pid)
        up, down = net.structure(pipe.upstream), net.structure(pipe.downstream)
        d = pipe.diameter.internal("length")
        z_dn = pipe.invert_down.internal("length")
        z_up = pipe.invert_up.internal("length")
        x_dn, x_up = xs[down.id], xs[up.id]
        outline.append(
            Series("Pipe" if k == 0 else "", ((x_dn, z_dn), (x_up, z_up)), "outline")
        )
        outline.append(Series("", ((x_dn, z_dn + d), (x_up, z_up + d)), "outline"))
        if k == 0:
            top = down.rim.internal("length") if down.rim is not None else z_dn + d
            outline.append(Series("", ((x_dn, z_dn - 0.3), (x_dn, top)), "outline"))
            if down.rim is not None:
                rims.append((x_dn, top))
        top = up.rim.internal("length") if up.rim is not None else z_up + d
        outline.append(Series("", ((x_up, z_up - 0.3), (x_up, top)), "outline"))
        if up.rim is not None:
            rims.append((x_up, top))
        r = results.get(pid)
        h = r.result.value if r is not None and r.result.ok else None
        if h is None:
            continue
        if k == 0:
            start = h.tailwater_mode
        water.append(
            Series(
                "Water" if not water else "",
                (
                    (x_dn, z_dn),
                    (x_up, z_up),
                    (x_up, min(h.up.hgl, z_up + d)),
                    (x_dn, min(h.down.hgl, z_dn + d)),
                ),
                "water",
            )
        )
        hgl += [(x_dn, h.down.hgl), (x_up, h.up.hgl), (x_up, h.hgl_junction)]
        egl += [(x_dn, h.down.egl), (x_up, h.up.egl), (x_up, h.egl_junction)]
        dc = h.critical_depth
        critical.append(
            Series(
                "Yc" if not critical else "",
                ((x_dn, z_dn + dc), (x_up, z_up + dc)),
                "dot",
            )
        )
    series = [*water, *outline]
    if rims:
        series.append(Series("Rim", tuple(rims), "marker"))
    if hgl:
        series += [Series("HGL", tuple(hgl), "line"), Series("EGL", tuple(egl), "dash")]
    series += critical
    head = net.pipe(pipe_id)
    first = net.structure(head.upstream)
    outfall = net.structure(topo.outfall)
    kind = "Line" if len(route) == 1 else "Route"
    title = (
        f"{kind} {pipe_id}: {first.name or first.id} to {outfall.name or outfall.id}"
    )
    if start is not None:
        title += f" (start: {TAILWATER_LABELS[start].lower()})"
    note = "" if hgl else "inputs incomplete"
    return PlotSpec(title, x_label, "Elevation (ft)", tuple(series), note)
