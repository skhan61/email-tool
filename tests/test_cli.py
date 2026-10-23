"""The installed command line, run as a new user runs it.

Standard: the real entry point in a subprocess (`python -m email_tool_mcp`), as `[project.scripts]` installs it.
Placement: tests/test_cli.py, beside __main__.py's other callers (pytest's tests/ layout).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

COMMANDS: tuple[str, ...] = ("add", "remove", "list", "check", "serve", "audit", "policy")


def help_text(*arguments: str) -> str:
    environment: dict[str, str] = {**os.environ, "PAGER": "cat"}
    finished: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-m", "email_tool_mcp", *arguments, "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    return finished.stdout + finished.stderr


def test_help_lists_every_command() -> None:
    names: set[str] = {line.strip() for line in help_text().splitlines()}
    command: str
    for command in COMMANDS:
        assert command in names, f"{command} missing from --help"


@pytest.mark.parametrize("group", ["audit", "policy"])
def test_help_of_a_group_lists_its_commands(group: str) -> None:
    assert "COMMANDS" in help_text(group)
