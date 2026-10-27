"""PFSUITE network exchange import (docs/pfsuite-network-exchange.md)."""

import copy
import json
import math
from pathlib import Path

import pytest

from proflow.io.pfsuite import import_exchange, read_exchange
from proflow.io.units import Quantity
from proflow.model.network import Network
from proflow.model.project import Project

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "pfsuite"
ONE_PIPE = EXAMPLE / "one-pipe.pfsuite.json"


def _doc():
    return json.loads(ONE_PIPE.read_text(encoding="utf-8"))


def _codes(result, level):
    return [f.code for f in result.of(level)]


def test_one_pipe_example_imports_with_plan_and_profile_resolved():
    r = read_exchange(ONE_PIPE)
    assert r.ok, r.report()
    net = r.network
    out, cbi = net.structure("1C4"), net.structure("1C9")
    assert (out.kind, cbi.kind) == ("outfall", "inlet")
    # Plan coordinates are the plan inserts, not the profile sheet.
    assert (out.x, out.y) == (5000.0, 3000.0)
    assert (cbi.x, cbi.y) == pytest.approx((5129.9038, 3075.0), abs=1e-4)
    assert cbi.rim == Quantity(758.25, "ft")
    (pipe,) = net.pipes
    assert (pipe.upstream, pipe.downstream) == ("1C9", "1C4")
    # Sheet (1148, 2131) on a grid with datum 740, base y 2000, x10:
    # elevation = 740 + 131 / 10.
    assert pipe.invert_up.value == pytest.approx(753.10)
    assert pipe.invert_down.value == pytest.approx(751.60)
    # Length is centre to centre (stations 150 and 0), not the drawn run.
    assert pipe.length == Quantity(150.0, "ft")
    assert pipe.source["attributes"]["drawn_run_ft"] == pytest.approx(147.0)
    assert pipe.diameter == Quantity(15.0, "in")
    assert pipe.material == "RCP III"
    assert pipe.n is None  # never applied without the user
    assert r.suggested_n == {"3F7": (0.013, "pipen.dta")}
    assert set(r.missing) == {
        "pipe 3F7: Manning's n",
        "outfall 1C4: starting HGL / tailwater",
        "inlet 1C9: a catchment or known flow",
    }
    assert net.missing_inputs()  # the network agrees about what is missing


def test_every_supported_field_survives_import_save_and_reopen():
    doc = _doc()
    net = read_exchange(ONE_PIPE).network
    project = Project("p", (), (2,), (), network=net)
    data = json.loads(json.dumps(project.to_dict()))
    reopened = Project.from_dict(data).network
    assert reopened == net

    # Each exchange field lands in a modelled field or the source record.
    s_in = {s["id"]: s for s in doc["structures"]}
    for s in reopened.structures:
        src, raw = s.source, s_in[s.id]
        assert src["format"] == "pfsuite-network/1"
        assert src["id"] == raw["id"] and src["drawing"] == doc["drawing"]["name"]
        assert (s.x, s.y) == (raw["plan"]["x"], raw["plan"]["y"])
        assert s.name == raw["name"]
        assert s.rim.value == raw["rim"]["value"]
        attrs = src["attributes"]
        assert attrs["rim_source"] == raw["rim"]["source"]
        assert attrs["rotation_deg"] == raw["plan"]["rotation_deg"]
        for key in ("block", "type", "size", "position", "inlet", "library"):
            assert attrs[key] == raw[key]
        assert attrs["record_schema"] == raw["record_schema"]
        assert attrs["lines"] == raw["lines"]
    p_raw = doc["pipes"][0]
    (pipe,) = reopened.pipes
    a = pipe.source["attributes"]
    assert pipe.source["id"] == p_raw["id"] and a["grid"] == p_raw["grid"]
    assert a["upstream_sheet"] == [p_raw["upstream"]["sheet"][k] for k in "xy"]
    assert a["downstream_sheet"] == [p_raw["downstream"]["sheet"][k] for k in "xy"]
    assert a["wall_in"] == p_raw["wall_in"] and pipe.material == p_raw["material"]
    assert pipe.diameter.value == p_raw["size_in"]
    top = reopened.source
    assert top["producer"] == doc["producer"]
    assert top["exported_at"] == doc["exported_at"]
    assert top["drawing"] == doc["drawing"]
    assert top["settings"] == doc["settings"]
    assert [g["id"] for g in top["grids"]] == ["2A1"]
    assert top["lines"][0]["cl_file"] == "Storm_BA.cl"
    assert reopened.crs is None


def test_unknown_fields_are_kept_not_dropped():
    doc = _doc()
    doc["structures"][1]["pfface"] = "BF"
    doc["pipes"][0]["coating"] = "none"
    doc["survey_note"] = "checked"
    r = import_exchange(doc)
    assert r.ok
    assert r.network.structure("1C9").source["extra"] == {"pfface": "BF"}
    assert r.network.pipes[0].source["extra"] == {"coating": "none"}
    assert r.network.source["extra"] == {"survey_note": "checked"}
    assert _codes(r, "info").count("unknown_field") == 3


def test_end_too_far_from_any_structure_is_unresolved():
    doc = _doc()
    doc["pipes"][0]["upstream"]["sheet"]["x"] = 1130.0  # station 130: 20 ft short
    r = import_exchange(doc)
    assert not r.ok
    (f,) = r.of("unresolved")
    assert f.code == "end_unlinked" and f.ref == "3F7"
    assert "station 130.00" in f.message and "1C9 at 20.00 ft" in f.message


def test_two_equally_near_structures_are_ambiguous():
    doc = _doc()
    twin = copy.deepcopy(doc["structures"][1])
    twin["id"] = "1D0"
    doc["structures"].append(twin)
    r = import_exchange(doc)
    assert _codes(r, "unresolved") == ["end_ambiguous"] and not r.ok


def test_both_ends_on_one_structure_and_missing_grid_are_unresolved():
    doc = _doc()
    doc["pipes"][0]["downstream"]["sheet"]["x"] = 1145.0
    r = import_exchange(doc)
    assert _codes(r, "unresolved") == ["same_structure"]
    doc = _doc()
    doc["pipes"][0]["grid"] = "999"
    r = import_exchange(doc)
    assert _codes(r, "unresolved") == ["pipe_no_grid"]


def test_plan_points_that_disagree_with_stations_warn():
    doc = _doc()
    doc["structures"][1]["plan"]["x"] += 10.0
    r = import_exchange(doc)
    assert r.ok and "length_mismatch" in _codes(r, "warning")


def test_adverse_profile_imports_with_a_warning():
    doc = _doc()
    up, down = doc["pipes"][0]["upstream"], doc["pipes"][0]["downstream"]
    up["sheet"]["y"], down["sheet"]["y"] = 2110.0, 2116.0
    r = import_exchange(doc)
    assert r.ok and "adverse_slope" in _codes(r, "warning")


def test_rim_not_on_record_is_missing_not_zero():
    doc = _doc()
    doc["structures"][0]["rim"] = {"value": None, "source": "NONE"}
    r = import_exchange(doc)
    assert r.network.structure("1C4").rim is None
    assert any("rim (source NONE)" in m for m in r.missing)
    doc["structures"][0]["rim"] = {"value": 0.0, "source": "NONE"}
    assert not import_exchange(doc).ok


@pytest.mark.parametrize(
    "change, path",
    [
        (lambda d: d.update(format_version=2), "exchange.format_version"),
        (lambda d: d.update(format="stm"), "exchange.format"),
        (lambda d: d["units"].update(length="m"), "exchange.units"),
        (lambda d: d.update(structures=7), "exchange.structures"),
        (lambda d: d["grids"][0].update(vscale=0), "exchange.grids[0].vscale"),
        (lambda d: d["pipes"][0].pop("size_in"), "exchange.pipes[0].size_in"),
        (lambda d: d["structures"][0]["lines"][0].update(line="X"), "lines[0].line"),
        (lambda d: d["coordinates"].update(plan="sheet"), "exchange.coordinates.plan"),
    ],
)
def test_invalid_exchange_is_an_error_with_a_path(change, path):
    doc = _doc()
    change(doc)
    r = import_exchange(doc)
    assert not r.ok
    assert any(path in f.ref for f in r.of("error")), r.report()


def test_exporter_errors_stop_the_import():
    doc = _doc()
    doc["diagnostics"].append(
        {
            "level": "error",
            "code": "anchor_copy",
            "message": "copied anchor",
            "ref": "2A1",
        }
    )
    r = import_exchange(doc)
    assert not r.ok and _codes(r, "error") == ["exporter:anchor_copy"]


def test_unreadable_file_is_reported(tmp_path):
    bad = tmp_path / "x.pfsuite.json"
    bad.write_text("{not json", encoding="utf-8")
    r = read_exchange(bad)
    assert not r.ok and _codes(r, "error") == ["unreadable"]


def test_network_plan_length_matches_station_length_for_a_straight_line():
    net: Network = read_exchange(ONE_PIPE).network
    a, b = net.structure("1C4"), net.structure("1C9")
    assert math.dist((a.x, a.y), (b.x, b.y)) == pytest.approx(150.0)


def test_ansi_file_from_autolisp_is_read_as_windows_1252(tmp_path):
    doc = _doc()
    doc["structures"][1]["name"] = "BA-2 \u00b0"  # degree sign, cp1252 0xB0
    path = tmp_path / "ansi.pfsuite.json"
    path.write_bytes(json.dumps(doc, ensure_ascii=False).encode("cp1252"))
    r = read_exchange(path)
    assert r.ok and _codes(r, "info")[0] == "encoding"
    assert r.network.structure("1C9").name == "BA-2 \u00b0"
