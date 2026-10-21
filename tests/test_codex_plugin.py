"""Launch the server the Codex/ChatGPT plugin declares, built from this checkout.

Standard: the MCP SDK's stdio client against the real subprocess; skipped unless CI sets EMAIL_TOOL_CODEX_FROM.
Placement: tests/test_codex_plugin.py; the `codex-plugin` CI job runs it after installing the plugin with Codex.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from mcp_types import ListToolsResult

ROOT: Path = Path(__file__).resolve().parent.parent
SOURCE: str = os.environ.get("EMAIL_TOOL_CODEX_FROM", "")
GITHUB_SOURCE: str = "git+https://github.com/skhan61/email-tool"

pytestmark: list[pytest.MarkDecorator] = [
    pytest.mark.anyio,
    pytest.mark.skipif(not SOURCE, reason="set EMAIL_TOOL_CODEX_FROM to a checkout of this repo"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_codex_server_command_serves_every_declared_tool() -> None:
    declared: dict[str, Any] = json.loads((ROOT / ".codex-mcp.json").read_text(encoding="utf-8"))
    server: dict[str, Any] = declared["mcpServers"]["email"]
    assert GITHUB_SOURCE in server["args"], "the plugin must install from the published source"
    arguments: list[str] = [SOURCE if argument == GITHUB_SOURCE else argument for argument in server["args"]]
    params: StdioServerParameters = StdioServerParameters(command=server["command"], args=arguments)
    async with Client(params) as client:
        listed: ListToolsResult = await client.list_tools()
    manifest: dict[str, Any] = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert {tool.name for tool in listed.tools} == {tool["name"] for tool in manifest["tools"]}
