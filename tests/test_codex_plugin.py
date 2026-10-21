"""Launch the server Codex registered for the plugin, built from this checkout.

Standard: the MCP SDK's stdio client against the command `codex mcp get email --json` reports.
Placement: tests/test_codex_plugin.py; the `codex-plugin` CI job installs the plugin, then runs this file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.launch import declared_tool_names, served_tool_names

REGISTERED: str = os.environ.get("EMAIL_TOOL_CODEX_SERVER", "")
CHECKOUT: str = os.environ.get("EMAIL_TOOL_CODEX_FROM", "")
GITHUB_SOURCE: str = "git+https://github.com/skhan61/email-tool@"

pytestmark: list[pytest.MarkDecorator] = [
    pytest.mark.anyio,
    pytest.mark.skipif(not (REGISTERED and CHECKOUT), reason="run by the codex-plugin CI job"),
]


async def test_registered_server_serves_every_declared_tool() -> None:
    transport: dict[str, Any] = json.loads(Path(REGISTERED).read_text(encoding="utf-8"))["transport"]
    sources: list[str] = [argument for argument in transport["args"] if argument.startswith(GITHUB_SOURCE)]
    assert len(sources) == 1, f"Codex registered an unexpected source: {transport['args']}"
    # The pinned release tag does not exist for an unmerged PR, so build this checkout in its place.
    arguments: list[str] = [CHECKOUT if argument in sources else argument for argument in transport["args"]]
    assert await served_tool_names(transport["command"], arguments, None) == declared_tool_names()
