"""Open and save native .proflow.json project and results files."""

from __future__ import annotations

import json
from pathlib import Path

from proflow.model.project import Project, ProjectError


def read_project(path: Path) -> tuple[Project, object]:
    """Load a project; also return the schema version the file was written in."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError([("file", f"not valid JSON: {exc}")]) from None
    version = data.get("schema_version") if isinstance(data, dict) else None
    return Project.from_dict(data), version


def load_project(path: Path) -> Project:
    return read_project(path)[0]


def save_project(project: Project, path: Path) -> None:
    write_json(project.to_dict(), path)


def write_json(data: dict, path: Path) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")
