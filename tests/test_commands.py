"""The plugin's slash commands (/inbox, /email-search, /email-send) name only real tools and arguments.

Standard: the commands are Markdown prompts with YAML front matter (Claude Code plugin commands);
checked against the tools the server really lists, through the MCP SDK's in-process client.
Placement: tests/test_commands.py, beside the other tests (pytest's tests/ layout).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest
from mcp import Client
from mcp_types import ListToolsResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.server import build_server

COMMANDS: Final[Path] = Path(__file__).resolve().parent.parent / "commands"
_NAMED: Final[re.Pattern[str]] = re.compile(r"`([a-z][a-z_]+)`")


def command_files() -> list[Path]:
    found: list[Path] = sorted(COMMANDS.glob("*.md"))
    assert {path.stem for path in found} == {"inbox", "email-search", "email-send"}
    return found


@pytest.mark.parametrize("command", command_files(), ids=lambda path: path.stem)
def test_each_command_says_what_it_does(command: Path) -> None:
    text: str = command.read_text(encoding="utf-8")
    assert text.startswith("---\n") and re.search(r"^description: \S", text, re.MULTILINE), command.name


@pytest.mark.anyio
async def test_commands_name_only_tools_and_arguments_the_server_has(book: MailboxBook, audit: AuditLog) -> None:
    async with Client(build_server(book, audit)) as client:
        listed: ListToolsResult = await client.list_tools()
    known: set[str] = {tool.name for tool in listed.tools}
    known |= {argument for tool in listed.tools for argument in tool.input_schema.get("properties", {})}
    command: Path
    for command in command_files():
        named: set[str] = set(_NAMED.findall(command.read_text(encoding="utf-8")))
        assert named, f"{command.name} names no tool"
        assert named <= known, f"{command.name} names {sorted(named - known)}, which the server does not have"
