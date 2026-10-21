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

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.server import build_server

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


@pytest.mark.anyio
async def test_bundle_lists_exactly_the_tools_the_server_registers(book: MailboxBook) -> None:
    async with Client(build_server(book)) as client:
        listed: ListToolsResult = await client.list_tools()
    declared: set[str] = {tool["name"] for tool in read_json("manifest.json")["tools"]}
    assert declared == {tool.name for tool in listed.tools}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
