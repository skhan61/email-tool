"""Policy: read-only, allowed tools, recipient domains; administrator rules cannot be loosened.

Standard: pytest with policy files written to tmp_path; the server is driven through the SDK's in-process client.
Placement: tests/test_policy.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import (
    LINUX_ADMIN_DIRECTORY,
    MACOS_ADMIN_DIRECTORY,
    POLICY_FILE,
    Policy,
    PolicyRefusal,
    Rules,
    policy_paths,
)
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import SettingsError
from tests.fakes import FakeMailServer

TOOLS: frozenset[str] = frozenset({"list_emails", "get_email", "send_email", "delete_email", "list_mailboxes"})


def write_policy(tmp_path: Path, admin: str, user: str) -> Policy:
    admin_file: Path = tmp_path / "admin.toml"
    user_file: Path = tmp_path / "user.toml"
    admin_file.write_text(admin, encoding="utf-8")
    user_file.write_text(user, encoding="utf-8")
    return Policy([admin_file, user_file])


def test_no_policy_files_allow_everything(tmp_path: Path) -> None:
    rules: Policy = Policy([tmp_path / "absent.toml"])
    rules.check_call("work", "me@example.com", "send_email", True, TOOLS, keeps_sign_in=False)
    rules.check_message("work", "me@example.com", ["a@anywhere.com"], True, lambda: [])


def test_read_only_refuses_tools_that_change_mail(tmp_path: Path) -> None:
    rules: Policy = write_policy(tmp_path, "[mailboxes.work]\nread_only = true\n", "")
    rules.check_call("work", "me@example.com", "list_emails", False, TOOLS, keeps_sign_in=False)
    with pytest.raises(PolicyRefusal, match="read_only"):
        rules.check_call("work", "me@example.com", "delete_email", True, TOOLS, keeps_sign_in=False)
    rules.check_call("home", "me@example.com", "delete_email", True, TOOLS, keeps_sign_in=False)


def test_a_user_cannot_loosen_the_administrator(tmp_path: Path) -> None:
    rules: Policy = write_policy(tmp_path, "[default]\nread_only = true\n", "[default]\nread_only = false\n")
    with pytest.raises(PolicyRefusal):
        rules.check_call("work", "me@example.com", "send_email", True, TOOLS, keeps_sign_in=False)


def test_allowed_tools_take_the_overlap(tmp_path: Path) -> None:
    rules: Policy = write_policy(
        tmp_path,
        '[default]\nallowed_tools = ["list_emails", "get_email", "send_email"]\n',
        '[mailboxes.work]\nallowed_tools = ["list_emails", "send_email", "delete_email"]\n',
    )
    assert rules.rules_for("work", "me@example.com") == Rules(allowed_tools=["list_emails", "send_email"])
    with pytest.raises(PolicyRefusal, match="delete_email is not in allowed_tools"):
        rules.check_call("work", "me@example.com", "delete_email", True, TOOLS, keeps_sign_in=False)
    rules.check_call("work", "me@example.com", "list_mailboxes", False, TOOLS, keeps_sign_in=False)


def test_a_misspelled_tool_name_is_reported(tmp_path: Path) -> None:
    rules: Policy = write_policy(tmp_path, '[default]\nallowed_tools = ["list_email"]\n', "")
    with pytest.raises(SettingsError, match="list_email"):
        rules.check_call("work", "me@example.com", "list_emails", False, TOOLS, keeps_sign_in=False)


@pytest.mark.parametrize(
    ("recipients", "refused"),
    [
        (["a@example.com"], False),
        (["A@Example.COM"], False),
        (["a@example.com", "boss@gmail.com"], True),
        (["a@example.com.evil.net"], True),
        ([], True),
    ],
)
def test_recipients_outside_the_allowed_domains_are_refused(
    tmp_path: Path, recipients: list[str], refused: bool
) -> None:
    rules: Policy = write_policy(tmp_path, '[default]\nallowed_recipient_domains = ["Example.com"]\n', "")
    if refused:
        with pytest.raises(PolicyRefusal):
            rules.check_message("work", "me@example.com", recipients, True, lambda: [])
    else:
        rules.check_message("work", "me@example.com", recipients, True, lambda: [])


@pytest.mark.parametrize(
    "text",
    ["[defaults]\nread_only = true\n", '[default]\nread_only = "yes"\n', "mailboxes = 5\n", "[mailboxes]\nwork = 1\n"],
)
def test_a_malformed_policy_is_an_error_not_ignored(tmp_path: Path, text: str) -> None:
    with pytest.raises(SettingsError):
        write_policy(tmp_path, text, "").rules_for("work", "me@example.com")


@pytest.mark.parametrize(
    "to", ["<evil@gmail.com", "a@example.com, <evil@gmail.com", "evil@gmail.com (x@example.com", "x <evil@gmail.com>> "]
)
@pytest.mark.parametrize("tool", ["send_email", "create_draft"])
@pytest.mark.anyio
async def test_malformed_addresses_cannot_slip_past_the_allow_list(
    settings_file: Path, audit: AuditLog, tmp_path: Path, mail_server: FakeMailServer, to: str, tool: str
) -> None:
    store_password("work", "pw")
    rules: Policy = write_policy(tmp_path, '[default]\nallowed_recipient_domains = ["example.com"]\n', "")
    book: MailboxBook = MailboxBook(settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=rules)
    arguments: dict[str, object] = {"mailbox": "work", "to": to, "subject": "s", "body": "b"}
    if tool == "create_draft":
        arguments["folder"] = "Drafts"
    async with Client(build_server(book, audit)) as client:
        result: CallToolResult = await client.call_tool(tool, arguments)
    assert result.is_error
    assert mail_server.sent == []
    assert mail_server.folders["Drafts"] == {}


@pytest.mark.anyio
async def test_the_server_refuses_by_policy_and_records_it(
    settings_file: Path, audit: AuditLog, tmp_path: Path, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    rules: Policy = write_policy(tmp_path, "[mailboxes.work]\nread_only = true\n", "")
    book: MailboxBook = MailboxBook(settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=rules)
    async with Client(build_server(book, audit)) as client:
        result: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "work", "to": "a@example.com", "subject": "s", "body": "b"}
        )
    assert result.is_error
    assert mail_server.sent == []
    assert "PolicyRefusal" in audit.path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("platform", "folder"), [("darwin", MACOS_ADMIN_DIRECTORY), ("linux", LINUX_ADMIN_DIRECTORY)])
def test_the_administrators_file_does_not_move_with_the_environment(
    monkeypatch: pytest.MonkeyPatch, platform: str, folder: Path
) -> None:
    """#122: on macOS platformdirs' folder honoured $XDG_CONFIG_DIRS, so whoever launched the
    server chose the administrator's file."""
    monkeypatch.setenv("XDG_CONFIG_DIRS", "/tmp/chosen-by-whoever-launches")
    monkeypatch.setattr(sys, "platform", platform)
    administrator: Path = policy_paths()[0]
    assert administrator == folder / POLICY_FILE
