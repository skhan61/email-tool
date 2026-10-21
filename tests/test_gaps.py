"""The gaps the control-mapping review found stay closed.

Standard: pytest with policy files in tmp_path and the offline fakes; POSIX-only checks are skipped on Windows.
Placement: tests/test_gaps.py, one test per gap listed in issue #47.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp import audit as audit_module
from email_tool_mcp.audit import AuditLog, os_account, verify
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.policy import Policy, PolicyRefusal, show_rules
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import Mailbox
from tests.conftest import WORK
from tests.fakes import FakeMailServer

TOOLS: frozenset[str] = frozenset({"list_emails", "send_email"})
ENVIRONMENT: dict[str, str] = {
    "EMAIL_TOOL_NAME": "work",
    "EMAIL_TOOL_ADDRESS": "other@elsewhere.com",
    "EMAIL_TOOL_IMAP_HOST": "imap.elsewhere.com",
    "EMAIL_TOOL_SMTP_HOST": "smtp.elsewhere.com",
    "EMAIL_TOOL_PASSWORD": "pw",
}


def policy_file(tmp_path: Path, text: str) -> Policy:
    path: Path = tmp_path / "admin.toml"
    path.write_text(text, encoding="utf-8")
    return Policy([path])


def test_a_rule_keyed_by_address_binds_under_any_name(tmp_path: Path) -> None:
    rules: Policy = policy_file(tmp_path, '[mailboxes."ME@example.com"]\nread_only = true\n')
    for name in ("work", "work2", "anything"):
        with pytest.raises(PolicyRefusal, match="read_only"):
            rules.check_call(name, "me@example.com", "send_email", True, TOOLS)
    rules.check_call("work", "someone@else.com", "send_email", True, TOOLS)


def test_the_environment_mailbox_never_replaces_an_enrolled_one(
    settings_file: Path, mail_server: FakeMailServer
) -> None:
    book: MailboxBook = MailboxBook(settings_file, ENVIRONMENT, mail_server.open_imap)
    found: Mailbox = book.resolve("work")
    assert found == WORK
    assert "already enrolled" in book.environment_problem


def test_policy_can_switch_the_environment_mailbox_off(tmp_path: Path, mail_server: FakeMailServer) -> None:
    rules: Policy = policy_file(tmp_path, "[default]\nallow_environment_mailbox = false\n")
    book: MailboxBook = MailboxBook(tmp_path / "none.toml", {**ENVIRONMENT, "EMAIL_TOOL_NAME": "desk"}, policy=rules)
    assert book.mailboxes() == {}
    assert "policy disallows it" in book.environment_problem


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX account lookup")
def test_the_audit_user_cannot_be_set_through_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import pwd

    real: str = pwd.getpwuid(os.getuid()).pw_name
    for variable in ("USER", "LOGNAME", "LNAME", "USERNAME"):
        monkeypatch.setenv(variable, "alice-not-me")
    assert os_account() == real


def test_an_unreachable_syslog_target_is_not_fatal(tmp_path: Path) -> None:
    environment: dict[str, str] = {
        "EMAIL_TOOL_AUDIT_FILE": str(tmp_path / "audit.jsonl"),
        "EMAIL_TOOL_AUDIT_SYSLOG": "tcp://127.0.0.1:9",
    }
    log: AuditLog = AuditLog.from_environment(environment, with_syslog=True)
    call: str = log.started("work", "list_emails", {})
    log.finished(call, "work", "list_emails", "ok")
    assert verify(log.path).broken_at is None


def test_verify_says_so_when_there_is_no_log(tmp_path: Path) -> None:
    assert verify(tmp_path / "never.jsonl").render().startswith("No audit log at ")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX account lookup")
def test_a_uid_without_a_passwd_entry_is_still_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import pwd

    def missing(uid: int) -> pwd.struct_passwd:
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", missing)
    os_account.cache_clear()
    try:
        assert os_account() == f"uid:{os.getuid()}"
    finally:
        os_account.cache_clear()


def test_names_match_case_insensitively(tmp_path: Path) -> None:
    rules: Policy = policy_file(tmp_path, "[mailboxes.work]\nread_only = true\n")
    with pytest.raises(PolicyRefusal):
        rules.check_call("Work", "", "send_email", True, TOOLS)


def test_the_syslog_copy_reconnects_when_the_target_comes_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []
    received: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record.getMessage())

    def flaky(address: str) -> logging.Handler:
        attempts.append(address)
        if len(attempts) == 1:
            raise ConnectionRefusedError("down")
        return Capture()

    monkeypatch.setattr(audit_module, "syslog_handler", flaky)
    log: AuditLog = AuditLog(tmp_path / "audit.jsonl", "tcp://siem.example.com:514")
    log.started("work", "list_emails", {})
    assert len(attempts) == 2 and len(received) == 1


def test_policy_show_says_when_address_rules_are_missing(tmp_path: Path) -> None:
    rules: Policy = policy_file(tmp_path, '[mailboxes."me@example.com"]\nread_only = true\n')
    assert "rules keyed by address are not shown" in show_rules(rules, tmp_path / "none.toml", "desk", "")
    assert "read_only=True" in show_rules(rules, tmp_path / "none.toml", "desk", "me@example.com")


@pytest.mark.anyio
async def test_an_unresolvable_mailbox_never_runs(book: MailboxBook, audit: AuditLog) -> None:
    async with Client(build_server(book, audit)) as client:
        result: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "nope", "to": "a@x.com", "subject": "s", "body": "b"}
        )
    assert result.is_error and "UnknownMailbox" in audit.path.read_text(encoding="utf-8")
