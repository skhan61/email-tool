"""Every manifest carries the package version and the server's real tool list.

Standard: one source of truth (pyproject.toml) checked by a test, as PyPA's single-sourcing guide suggests.
Placement: tests/test_manifests.py, run by CI with the rest of the suite.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import ListToolsResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.server import build_server
from tests.launch import declared_tool_names

ROOT: Path = Path(__file__).resolve().parent.parent


def read_json(relative: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    return loaded


def package_license() -> str:
    license_id: str = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["license"]
    return license_id


@pytest.mark.parametrize(
    "path",
    [
        ("manifest.json", ("license",)),
        (".claude-plugin/plugin.json", ("license",)),
        (".codex-plugin/plugin.json", ("license",)),
        (".claude-plugin/marketplace.json", ("plugins", 0, "license")),
    ],
)
def test_manifest_license_matches_the_package(path: tuple[str, tuple[str | int, ...]]) -> None:
    value: Any = read_json(path[0])
    for key in path[1]:
        value = value[key]
    assert value == package_license()


def package_version() -> str:
    project: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version: str = project["version"]
    return version


@pytest.mark.parametrize(
    ("relative", "path"),
    [
        ("manifest.json", ("version",)),
        (".claude-plugin/plugin.json", ("version",)),
        (".codex-plugin/plugin.json", ("version",)),
        (".claude-plugin/marketplace.json", ("metadata", "version")),
    ],
)
def test_manifest_version_matches_the_package(relative: str, path: tuple[str, ...]) -> None:
    value: Any = read_json(relative)
    for key in path:
        value = value[key]
    assert value == package_version()


@pytest.mark.anyio
async def test_bundle_lists_exactly_the_tools_the_server_registers(book: MailboxBook, audit: AuditLog) -> None:
    async with Client(build_server(book, audit)) as client:
        listed: ListToolsResult = await client.list_tools()
    assert declared_tool_names() == {tool.name for tool in listed.tools}


def test_registry_entry_names_this_release_and_the_readme_proves_it() -> None:
    """The MCP Registry checks the `mcp-name` marker in the PyPI description (the README)."""
    server: dict[str, Any] = read_json("server.json")
    package: dict[str, Any] = server["packages"][0]
    assert server["version"] == package["version"] == package_version()
    project: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert package["identifier"] == project["name"]
    assert f"<!-- mcp-name: {server['name']} -->" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_codex_plugin_runs_the_release_matching_its_version() -> None:
    arguments: list[str] = read_json(".codex-mcp.json")["mcpServers"]["email"]["args"]
    assert f"git+https://github.com/skhan61/email-tool@v{package_version()}" in arguments
