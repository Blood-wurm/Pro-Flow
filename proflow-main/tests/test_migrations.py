import copy
import json
from pathlib import Path

import pytest

from proflow.cli import EXIT_OK, main
from proflow.io.migrations import CURRENT_VERSION, migrate
from proflow.io.project_json import load_project, read_project, save_project
from proflow.model.project import SCHEMA_VERSION, Project, ProjectError

HERE = Path(__file__).resolve().parent
V1_FIRST_PASS = HERE / "data" / "v1-first-pass-rational.proflow.json"
V2_SCS = HERE / "data" / "v2-scs-user-storm.proflow.json"
V3_SCS = HERE / "data" / "v3-scs-user-storm.proflow.json"
EXAMPLES = HERE.parent / "examples"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_current_version_is_4():
    assert SCHEMA_VERSION == CURRENT_VERSION == 4


def test_first_pass_v1_file_migrates_with_explicit_defaults():
    v1 = _json(V1_FIRST_PASS)
    out, passed = migrate(v1)
    assert passed == [1, 2, 3]
    assert out["schema_version"] == CURRENT_VERSION
    assert out["rainfall"]["storms"] == []
    assert out["catchments"][0]["ascending_limb_factor"] == 1.0
    # The entered receding factor is kept, not replaced by the default.
    assert out["catchments"][0]["receding_limb_factor"] == 1


def test_migration_leaves_input_untouched():
    v1 = _json(V1_FIRST_PASS)
    before = copy.deepcopy(v1)
    migrate(v1)
    assert v1 == before


def test_current_document_passes_through_unchanged():
    current = _json(EXAMPLES / "scs-user-storm.proflow.json")
    out, passed = migrate(current)
    assert passed == [] and out == current


def test_v2_file_migrates_by_version_only():
    v2 = _json(V2_SCS)
    out, passed = migrate(v2)
    assert passed == [2, 3]
    assert out == {**v2, "schema_version": 4}
    assert Project.from_dict(v2) == load_project(
        EXAMPLES / "scs-user-storm.proflow.json"
    )


def test_v3_file_migrates_by_version_only():
    v3 = _json(V3_SCS)
    out, passed = migrate(v3)
    assert passed == [3]
    assert out == {**v3, "schema_version": 4}
    assert "network" not in out
    assert Project.from_dict(v3).network is None


def test_first_pass_v1_file_loads_same_as_current_example():
    old = load_project(V1_FIRST_PASS)
    new = load_project(EXAMPLES / "hydrographs-rational-ex-dp-7.proflow.json")
    assert old == new


def test_v1_file_with_new_fields_keeps_them():
    # Pre-release builds wrote storms, SCS catchments and non-default
    # optional values under v1.
    data = _json(V2_SCS)
    data["schema_version"] = 1
    data["catchments"][0]["tp_equation"] = "16A-7"
    data["catchments"][0]["ia_ratio"] = 0.05
    del data["catchments"][1]["tp_equation"]
    del data["catchments"][1]["ia_ratio"]
    project = Project.from_dict(data)
    nrcs, tri = project.catchments
    assert len(project.storms) == 1
    assert (nrcs.tp_equation, nrcs.ia_ratio) == ("16A-7", 0.05)
    assert (tri.tp_equation, tri.ia_ratio) == ("16A-10", 0.2)
    assert tri.shape_factor == 484


def test_v1_open_save_writes_current(tmp_path):
    project, version = read_project(V1_FIRST_PASS)
    assert version == 1
    out = tmp_path / "saved.proflow.json"
    save_project(project, out)
    saved = _json(out)
    assert saved["schema_version"] == CURRENT_VERSION
    assert saved["rainfall"]["storms"] == []
    assert read_project(out) == (project, CURRENT_VERSION)


@pytest.mark.parametrize("version", [0, 5, "2", None])
def test_unknown_versions_rejected(version):
    data = _json(V1_FIRST_PASS)
    data["schema_version"] = version
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    assert "project.schema_version" in dict(info.value.problems)


def test_migrated_file_still_validated():
    data = _json(V1_FIRST_PASS)
    data["catchments"][0]["c"] = 2.0
    with pytest.raises(ProjectError) as info:
        Project.from_dict(data)
    assert "catchments[0].c" in dict(info.value.problems)


def test_cli_notes_migration(capsys):
    assert main(["run", str(V1_FIRST_PASS)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "schema v1; read through migration, saving writes v4" in out
    assert "Qp=11.77 cfs" in out


def test_cli_quiet_for_current_version(capsys):
    main(["run", str(EXAMPLES / "scs-user-storm.proflow.json")])
    assert "migration" not in capsys.readouterr().out
