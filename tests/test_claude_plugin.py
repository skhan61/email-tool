"""Launch the Claude Code plugin's server with the command Claude Code runs.

Standard: the MCP SDK's stdio client against the real subprocess; skipped unless CI sets EMAIL_TOOL_CLAUDE_PLUGIN.
Placement: tests/test_claude_plugin.py; the `claude-plugin` CI job validates the plugin, then runs this file.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from tests.launch import ROOT, declared_tool_names, served_tool_names

pytestmark: list[pytest.MarkDecorator] = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("EMAIL_TOOL_CLAUDE_PLUGIN"), reason="run by the claude-plugin CI job"),
]


async def test_plugin_server_serves_every_declared_tool() -> None:
    server: dict[str, Any] = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["email"]
    arguments: list[str] = [argument.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)) for argument in server["args"]]
    assert await served_tool_names(server["command"], arguments, None) == declared_tool_names()
