"""Launch an unpacked .mcpb with the manifest's own command, as Claude Desktop does.

Standard: the MCP SDK's stdio client against the real subprocess; skipped unless CI sets EMAIL_TOOL_BUNDLE_DIR.
Placement: tests/test_bundle.py; the `bundle` CI job unpacks the bundle and runs only this file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.launch import declared_tool_names, served_tool_names

BUNDLE_DIR: str = os.environ.get("EMAIL_TOOL_BUNDLE_DIR", "")

pytestmark: list[pytest.MarkDecorator] = [
    pytest.mark.anyio,
    pytest.mark.skipif(not BUNDLE_DIR, reason="set EMAIL_TOOL_BUNDLE_DIR to an unpacked .mcpb"),
]


async def test_unpacked_bundle_serves_every_declared_tool() -> None:
    bundle: Path = Path(BUNDLE_DIR).resolve()
    manifest: dict[str, Any] = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    config: dict[str, Any] = manifest["server"]["mcp_config"]
    arguments: list[str] = [argument.replace("${__dirname}", str(bundle)) for argument in config["args"]]
    # A blank form, as Claude Desktop sends it when the user fills nothing in.
    environment: dict[str, str] = {**os.environ, **{key: "" for key in config["env"]}}
    assert await served_tool_names(config["command"], arguments, environment) == declared_tool_names()
