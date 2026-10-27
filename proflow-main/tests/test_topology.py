"""Directed sewer network topology, on synthetic links and a real .stm file.

The CA_CB data (tests/data/stm-system-ca-cb.topology.json) are a real
Hydraflow Storm Sewers project's line records, parsed by Storm-Profile.py
(tools/extract_stm_topology.py). Only topology and geometry are used: the
file's diameters, inverts, rims and areas are zero.
"""

import json
import math
from pathlib import Path

import pytest

from proflow.model.topology import Link, analyse

CA_CB = Path(__file__).resolve().parent / "data" / "stm-system-ca-cb.topology.json"


def _analyse(links, outfalls=("OUT",), extra=()):
    links = [Link(*x) for x in links]
    structures = {s for x in links for s in (x.upstream, x.downstream)} | set(extra)
    return analyse(links, structures, outfalls)


Y = [("P1", "J1", "OUT"), ("PA", "A1", "J1"), ("PB", "B1", "J1")]


def test_y_network_order_routes_and_junction():
    topo, issues = _analyse(Y)
    assert issues == []
    assert topo.outfall == "OUT" and topo.outfall_pipes == ("P1",)
    assert topo.order == ("P1", "PA", "PB")  # every pipe after its downstream
    assert topo.upstream == {"P1": ("PA", "PB"), "PA": (), "PB": ()}
    assert topo.downstream == {"P1": None, "PA": "P1", "PB": "P1"}
    assert topo.headwaters == ("PA", "PB")
    assert topo.junctions == {"J1": ("PA", "PB")}
    assert topo.route("PB") == ("PB", "P1")


def test_two_pipes_into_one_outfall_both_start_at_its_tailwater():
    topo, _ = _analyse([("P1", "A", "OUT"), ("P2", "B", "OUT")])
    assert topo.outfall_pipes == ("P1", "P2")


@pytest.mark.parametrize(
    "links, outfalls, code, ref",
    [
        ([("P1", "J1", "OUT"), ("P2", "J1", "X")], ("OUT",), "flow_split", "J1"),
        (
            [("P1", "A", "B"), ("P2", "B", "C"), ("P3", "C", "A"), ("P4", "D", "OUT")],
            ("OUT",),
            "cycle",
            "P1",
        ),
        ([("P1", "A", "OUT"), ("P2", "C", "D")], ("OUT",), "dead_end", "D"),
        ([("P1", "A", "OUT"), ("P2", "C", "D")], ("OUT",), "disconnected", "P2"),
        ([("P1", "A", "O1"), ("P2", "B", "O2")], ("O1", "O2"), "several_outfalls", ""),
        ([("P1", "A", "B")], (), "no_outfall", ""),
        (
            [("P1", "OUT", "A"), ("P2", "A", "OUT")],
            ("OUT",),
            "outfall_has_outlet",
            "OUT",
        ),
        ([("P1", "A", "A"), ("P2", "B", "OUT")], ("OUT",), "self_loop", "P1"),
    ],
)
def test_invalid_and_unsupported_topologies_are_named(links, outfalls, code, ref):
    topo, issues = _analyse(links, outfalls)
    assert topo is None
    hits = [i for i in issues if i.code == code]
    assert hits, [str(i) for i in issues]
    assert hits[0].ref == ref


def test_split_and_several_outfalls_are_unsupported_others_are_errors():
    _, issues = _analyse([("P1", "J1", "OUT"), ("P2", "J1", "OUT")])
    assert {i.level for i in issues if i.code == "flow_split"} == {"unsupported"}
    _, issues = _analyse([("P1", "A", "B"), ("P2", "B", "A")], ("OUT",), extra=("OUT",))
    assert {i.level for i in issues if i.code == "cycle"} == {"error"}


def test_unknown_structure_and_empty_network():
    topo, issues = analyse([Link("P1", "A", "OUT")], {"OUT"}, {"OUT"})
    assert topo is None and issues[0].code == "unknown_structure"
    topo, issues = analyse([], {"OUT"}, {"OUT"})
    assert topo is None and issues[0].code == "no_pipes"


def test_isolated_structure_is_only_noted():
    topo, issues = _analyse(Y, extra=("LONE",))
    assert topo is not None
    assert [(i.code, i.level, i.ref) for i in issues] == [
        ("isolated_structure", "info", "LONE")
    ]


# --- a real system: Hydraflow project file CA_CB ------------------------------


def _ca_cb():
    return json.loads(CA_CB.read_text(encoding="utf-8"))


def _ca_cb_links(doc):
    """Line records -> links. A line's upstream structure is its upstream
    junction (named by its Inlet ID); its downstream structure is the
    upstream junction of its downstream line, or the outfall for line 0."""
    lines = {x["line_no"]: x for x in doc["lines"]}
    links = []
    for n, x in lines.items():
        dn = x["downstream_line_no"]
        down = "OUTFALL" if dn == 0 else lines[dn]["inlet_id"]
        links.append(Link(x["line_id"], x["inlet_id"], down))
    return links, lines


def test_ca_cb_source_is_recorded():
    doc = _ca_cb()
    src = doc["source"]
    assert src["file"] == "System CA_CB_edited.stm" and len(src["sha256"]) == 64
    assert src["total_lines"] == len(doc["lines"]) == 6
    assert src["metric"] is False
    # What the file does not give: no sizes, inverts, rims or areas.
    for x in doc["lines"]:
        assert x["rise_in"] == x["invert_dn"] == x["invert_up"] == 0
        assert x["drainage_area"] == x["rim_up"] == 0


def test_ca_cb_topology_is_one_tree_with_one_branch_junction():
    links, _ = _ca_cb_links(_ca_cb())
    structures = {s for x in links for s in (x.upstream, x.downstream)}
    topo, issues = analyse(links, structures, {"OUTFALL"})
    assert issues == []
    assert topo.outfall_pipes == ("LINE CA-1",)
    # Lines 2 (CA-2) and 5 (CB-1) join at line 1's upstream junction, which
    # the file itself names "CA-2/CB-1".
    assert topo.junctions == {"CA-2/CB-1": ("LINE CA-2", "LINE CB-1")}
    assert set(topo.headwaters) == {"LINE CA-4", "LINE CB-2"}
    assert topo.route("LINE CA-4") == (
        "LINE CA-4",
        "LINE CA-3",
        "LINE CA-2",
        "LINE CA-1",
    )
    assert topo.route("LINE CB-2") == ("LINE CB-2", "LINE CB-1", "LINE CA-1")
    pos = {p: i for i, p in enumerate(topo.order)}
    for p, d in topo.downstream.items():
        assert d is None or pos[d] < pos[p]  # calculation order is valid


def test_ca_cb_line_ends_meet_their_downstream_lines():
    _, lines = _ca_cb_links(_ca_cb())
    for x in lines.values():
        dn = x["downstream_line_no"]
        if dn:
            below = lines[dn]
            assert (x["x_dn"], x["y_dn"]) == (below["x_up"], below["y_up"]), x[
                "line_id"
            ]


def _print_step(v: float) -> float:
    """Spacing of a value printed to 7 significant digits, as the file does."""
    return 10.0 ** (math.floor(math.log10(abs(v))) - 6)


def test_ca_cb_lengths_agree_with_coordinates_within_print_precision():
    # Coordinates are printed to 7 significant digits (x to the foot, y to
    # 0.1 ft here), so a length computed from them can be off by up to
    # (|dx| (ex_up + ex_dn) + |dy| (ey_up + ey_dn)) / L, each e being half a
    # printed step; the length itself is printed to 0.01 ft.
    _, lines = _ca_cb_links(_ca_cb())
    worst = 0.0
    for x in lines.values():
        for v in (x["x_dn"], x["y_dn"], x["x_up"], x["y_up"]):
            step = _print_step(v)
            assert round(v / step) * step == pytest.approx(v)  # 7 digits printed
        dx, dy = x["x_up"] - x["x_dn"], x["y_up"] - x["y_dn"]
        dist = math.hypot(dx, dy)
        ex = (_print_step(x["x_up"]) + _print_step(x["x_dn"])) / 2
        ey = (_print_step(x["y_up"]) + _print_step(x["y_dn"])) / 2
        bound = (abs(dx) * ex + abs(dy) * ey) / dist + 0.005
        assert abs(dist - x["length_ft"]) <= bound, x["line_id"]
        worst = max(worst, abs(dist - x["length_ft"]))
    assert worst == pytest.approx(0.27, abs=0.01)  # line CA-1: 39.74 vs 40.01
