"""Start a server the way an agent would and report the tools it serves.

Standard: the MCP SDK's stdio client (`mcp.Client` with `StdioServerParameters`).
Placement: tests/launch.py, shared by the bundle and Codex plugin launch tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp_types import ListToolsResult

ROOT: Path = Path(__file__).resolve().parent.parent


def declared_tool_names() -> set[str]:
    """The tool names manifest.json advertises."""
    manifest: dict[str, Any] = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    return {tool["name"] for tool in manifest["tools"]}


async def served_tool_names(command: str, arguments: list[str], environment: dict[str, str] | None) -> set[str]:
    """Launch `command` over stdio and return the names of the tools it lists."""
    server: StdioServerParameters = StdioServerParameters(command=command, args=arguments, env=environment)
    async with Client(server) as client:
        listed: ListToolsResult = await client.list_tools()
    return {tool.name for tool in listed.tools}
