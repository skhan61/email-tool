"""Policy: read-only, allowed tools, recipient domains; administrator rules cannot be loosened.

Standard: pytest with policy files written to tmp_path.
Placement: tests/test_policy.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy, PolicyRefusal, Rules
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import SettingsError
from tests.fakes import FakeMailServer


def policy(tmp_path: Path, admin: str, user: str) -> Policy:
    admin_file: Path = tmp_path / "admin.toml"
    user_file: Path = tmp_path / "user.toml"
    admin_file.write_text(admin, encoding="utf-8")
    user_file.write_text(user, encoding="utf-8")
    return Policy([admin_file, user_file])


def test_no_policy_files_allow_everything(tmp_path: Path) -> None:
    Policy([tmp_path / "absent.toml"]).check("work", "send_email", {"to": "a@anywhere.com"})


def test_read_only_refuses_writing_tools_only(tmp_path: Path) -> None:
    rules: Policy = policy(tmp_path, "[mailboxes.work]\nread_only = true\n", "")
    rules.check("work", "list_emails", {})
    with pytest.raises(PolicyRefusal, match="read_only"):
        rules.check("work", "delete_email", {"uid": 1})
    rules.check("home", "delete_email", {"uid": 1})


def test_a_user_cannot_loosen_the_administrator(tmp_path: Path) -> None:
    rules: Policy = policy(tmp_path, "[default]\nread_only = true\n", "[default]\nread_only = false\n")
    with pytest.raises(PolicyRefusal):
        rules.check("work", "send_email", {"to": "a@x.com"})


def test_allowed_tools_take_the_overlap(tmp_path: Path) -> None:
    rules: Policy = policy(
        tmp_path,
        '[default]\nallowed_tools = ["list_emails", "get_email", "send_email"]\n',
        '[mailboxes.work]\nallowed_tools = ["list_emails", "send_email", "delete_email"]\n',
    )
    assert rules.rules_for("work") == Rules(allowed_tools=["list_emails", "send_email"])
    with pytest.raises(PolicyRefusal, match="delete_email is not in allowed_tools"):
        rules.check("work", "delete_email", {})
    rules.check("work", "list_mailboxes", {})


@pytest.mark.parametrize(
    ("to", "cc", "refused"),
    [
        ("a@example.com", "", False),
        ("A@Example.COM", "", False),
        ('"Doe, Jane" <jane@example.com>', "", False),
        ("a@example.com", "boss@gmail.com", True),
        ("a@example.com.evil.net", "", True),
    ],
)
def test_recipients_outside_the_allowed_domains_are_refused(tmp_path: Path, to: str, cc: str, refused: bool) -> None:
    rules: Policy = policy(tmp_path, '[default]\nallowed_recipient_domains = ["Example.com"]\n', "")
    if refused:
        with pytest.raises(PolicyRefusal, match="outside allowed_recipient_domains"):
            rules.check("work", "send_email", {"to": to, "cc": cc})
    else:
        rules.check("work", "send_email", {"to": to, "cc": cc})


@pytest.mark.parametrize("text", ["[defaults]\nread_only = true\n", '[default]\nread_only = "yes"\n'])
def test_a_malformed_policy_is_an_error_not_ignored(tmp_path: Path, text: str) -> None:
    with pytest.raises(SettingsError):
        policy(tmp_path, text, "").check("work", "list_emails", {})


@pytest.mark.anyio
async def test_the_server_refuses_by_policy_and_records_it(
    book: MailboxBook, audit: AuditLog, tmp_path: Path, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    rules: Policy = policy(tmp_path, "[mailboxes.work]\nread_only = true\n", "")
    async with Client(build_server(book, audit, rules)) as client:
        result: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "work", "to": "a@x.com", "subject": "s", "body": "b"}
        )
    assert result.is_error
    assert mail_server.sent == []
    assert "PolicyRefusal" in audit.path.read_text(encoding="utf-8")
