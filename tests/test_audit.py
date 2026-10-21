"""The audit log: records before and after each call, tamper detection, no message content, fail closed.

Standard: pytest with the in-memory keyring from conftest; the server is driven through the SDK's in-process client.
Placement: tests/test_audit.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditError, AuditLog, syslog_handler, verify
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import SettingsError
from tests.fakes import FakeMailServer


def records(log: AuditLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def lines_of(log: AuditLog) -> list[str]:
    return log.path.read_text(encoding="utf-8").splitlines()


def rewrite(log: AuditLog, lines: list[str]) -> None:
    log.path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def write_three(log: AuditLog) -> None:
    uid: int
    for uid in (1, 2, 3):
        call: str = log.started("work", "delete_email", {"folder": "INBOX", "uid": uid})
        log.finished(call, "work", "delete_email", "ok")


def test_records_chain_and_verify(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    assert verify(audit.path).broken_at is None
    assert records(audit)[1]["previous"] == records(audit)[0]["mac"]
    assert [entry["phase"] for entry in records(audit)[:2]] == ["started", "finished"]


def test_an_edited_record_is_detected(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    lines: list[str] = lines_of(audit)
    lines[2] = lines[2].replace('"uid": 2', '"uid": 9')
    assert lines[2] != lines_of(audit)[2], "the test must actually change the record"
    rewrite(audit, lines)
    assert verify(audit.path).broken_at == 3


def test_a_removed_record_is_detected(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    lines: list[str] = lines_of(audit)
    rewrite(audit, lines[:2] + lines[3:])
    assert verify(audit.path).broken_at == 3


def test_removing_the_newest_records_is_detected(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    rewrite(audit, lines_of(audit)[:-2])
    assert "newest" in verify(audit.path).reason


def test_a_junk_line_is_reported_not_crashed_on(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    rewrite(audit, lines_of(audit)[:1] + ["[]"] + lines_of(audit)[1:])
    assert verify(audit.path).reason == "not a valid audit record"


def test_a_torn_last_line_refuses_new_records(audit: AuditLog, policy: Policy) -> None:
    write_three(audit)
    with audit.path.open("a", encoding="utf-8") as handle:
        handle.write('{"call": "half')
    with pytest.raises(AuditError, match="audit verify"):
        audit.started("work", "send_email", {"to": "a@x.com"})


def test_subject_and_body_are_never_recorded(audit: AuditLog, policy: Policy) -> None:
    audit.started("work", "send_email", {"to": "a@x.com", "subject": "CUI//SP-PROPIN", "body": "secret"})
    text: str = audit.path.read_text(encoding="utf-8")
    assert "a@x.com" in text
    assert "CUI//SP-PROPIN" not in text and "secret" not in text


@pytest.mark.parametrize("address", ["siem:udp", "ftp://siem:514", "tcp://:514"])
def test_a_bad_syslog_address_is_a_clear_settings_error(address: str) -> None:
    with pytest.raises(SettingsError, match="EMAIL_TOOL_AUDIT_SYSLOG"):
        syslog_handler(address)


@pytest.mark.anyio
async def test_every_server_call_is_recorded_before_and_after(
    book: MailboxBook, audit: AuditLog, policy: Policy, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    async with Client(build_server(book, audit, policy)) as client:
        await client.call_tool("list_emails", {"mailbox": "work"})
        await client.call_tool("list_emails", {"mailbox": "home"})
    written: list[tuple[str, str, str]] = [
        (entry["mailbox"], entry["phase"], entry.get("outcome", "")) for entry in records(audit)
    ]
    assert written[:2] == [("work", "started", ""), ("work", "finished", "ok")]
    assert written[3][1] == "finished" and written[3][2].startswith("MissingPassword")


@pytest.mark.anyio
async def test_an_unwritable_log_refuses_the_action(
    book: MailboxBook, tmp_path: Path, policy: Policy, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    blocked: Path = tmp_path / "blocked"
    blocked.mkdir()
    log: AuditLog = AuditLog(blocked)  # a directory, so it cannot be appended to
    async with Client(build_server(book, log, policy)) as client:
        result: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "work", "to": "a@x.com", "subject": "s", "body": "b"}
        )
    assert result.is_error
    assert mail_server.sent == []
