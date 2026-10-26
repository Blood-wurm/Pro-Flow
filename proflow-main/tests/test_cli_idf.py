import json
from pathlib import Path

import pytest

from proflow.cli import EXIT_INVALID, EXIT_OK, main
from proflow.io.idf_table import read_table
from proflow.model.project import Project

HERE = Path(__file__).resolve().parent
NOAA = HERE / "data" / "noaa-atlas14-wichita-ks-depth.csv"
EXAMPLE = HERE.parent / "examples" / "hydrographs-rational-ex-dp-7.proflow.json"


def test_fit_writes_an_idf_set_a_project_accepts(tmp_path, capsys):
    out = tmp_path / "fit.json"
    code = main(
        ["idf", "fit", str(NOAA), "--return-periods", "2,100", "--id", "wichita",
         "--json", str(out)]
    )  # fmt: skip
    assert code == EXIT_OK
    printed = capsys.readouterr().out
    assert "over 5-60 min (5 points)" in printed
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["fit_report"]["window_min"] == [5.0, 60.0]
    assert doc["fit_report"]["fits"]["2"]["method_status"] == "experimental"
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["rainfall"]["idf_sets"].append(doc["idf_set"])
    data["events"] = [2]
    data["catchments"][0]["idf"] = "wichita"
    Project.from_dict(data)


def test_fit_reports_concave_warning(capsys):
    main(["idf", "fit", str(NOAA), "--return-periods", "2"])
    assert "concave" in capsys.readouterr().out


def test_fit_with_d_step(capsys):
    assert (
        main(["idf", "fit", str(NOAA), "--return-periods", "10", "--d-step", "0.1"])
        == 0
    )


def test_convert_round_trip(tmp_path):
    out = tmp_path / "wichita.csv"
    assert main(["idf", "convert", str(NOAA), "-o", str(out), "--unit", "mm/hr"]) == 0
    back, original = read_table(out), read_table(NOAA)
    assert back.return_periods == original.return_periods
    assert back.row(100)[0] == pytest.approx(original.row(100)[0], rel=1e-5)


def test_export_project_set(tmp_path):
    out = tmp_path / "set.csv"
    args = ["idf", "export", str(EXAMPLE), "--set", "printed-5yr", "-o", str(out)]
    assert main(args) == EXIT_OK
    table = read_table(out)
    assert table.durations.tolist() == [5.0 * k for k in range(1, 13)]
    assert set(table.row(5)) == {3.693}


def test_export_unknown_set(tmp_path):
    args = ["idf", "export", str(EXAMPLE), "--set", "nope", "-o", str(tmp_path / "x")]
    assert main(args) == EXIT_INVALID


def test_fit_rejects_unknown_file(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("hello\n", encoding="utf-8")
    assert main(["idf", "fit", str(bad)]) == EXIT_INVALID
