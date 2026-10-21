"""Every manifest carries the package version, so a release cannot ship mismatched numbers.

Standard: one source of truth (pyproject.toml) checked by a test, as PyPA's single-sourcing guide suggests.
Placement: tests/test_versions.py, run by CI with the rest of the suite.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT: Path = Path(__file__).resolve().parent.parent


def read_json(relative: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    return loaded


def package_version() -> str:
    project: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version: str = project["version"]
    return version


@pytest.mark.parametrize(
    ("relative", "path"),
    [
        ("manifest.json", ("version",)),
        (".claude-plugin/plugin.json", ("version",)),
        (".claude-plugin/marketplace.json", ("metadata", "version")),
    ],
)
def test_manifest_version_matches_the_package(relative: str, path: tuple[str, ...]) -> None:
    value: Any = read_json(relative)
    for key in path:
        value = value[key]
    assert value == package_version()
