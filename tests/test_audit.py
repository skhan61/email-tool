"""The audit log: one chained record per call, tamper detection, no message content, fail closed.

Standard: pytest; the server is driven through the SDK's in-process client.
Placement: tests/test_audit.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditLog, verify
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.server import build_server
from tests.fakes import FakeMailServer


def records(log: AuditLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def write_three(log: AuditLog) -> None:
    for uid in (1, 2, 3):
        log.record("work", "delete_email", {"folder": "INBOX", "uid": uid}, "ok")


def test_records_chain_and_verify(audit: AuditLog) -> None:
    write_three(audit)
    assert verify(audit.path).render() == "OK: 3 record(s), chain intact."
    assert records(audit)[1]["previous"] == records(audit)[0]["hash"]


def test_an_edited_record_is_detected(audit: AuditLog) -> None:
    write_three(audit)
    lines: list[str] = audit.path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"uid":2', '"uid":9')
    audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify(audit.path).broken_at == 2


def test_a_removed_record_is_detected(audit: AuditLog) -> None:
    write_three(audit)
    lines: list[str] = audit.path.read_text(encoding="utf-8").splitlines()
    audit.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert verify(audit.path).broken_at == 2


def test_subject_and_body_are_never_recorded(audit: AuditLog) -> None:
    audit.record("work", "send_email", {"to": "a@x.com", "subject": "CUI//SP-PROPIN", "body": "secret"}, "ok")
    text: str = audit.path.read_text(encoding="utf-8")
    assert "a@x.com" in text
    assert "CUI//SP-PROPIN" not in text and "secret" not in text


@pytest.mark.anyio
async def test_every_server_call_is_recorded_with_its_outcome(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    async with Client(build_server(book, audit)) as client:
        await client.call_tool("list_emails", {"mailbox": "work"})
        await client.call_tool("list_emails", {"mailbox": "home"})
    written: list[dict[str, Any]] = records(audit)
    assert [(entry["mailbox"], entry["tool"]) for entry in written] == [
        ("work", "list_emails"),
        ("home", "list_emails"),
    ]
    assert written[0]["outcome"] == "ok"
    assert written[1]["outcome"].startswith("MissingPassword")


@pytest.mark.anyio
async def test_an_unwritable_log_refuses_the_action(
    book: MailboxBook, tmp_path: Path, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    blocked: Path = tmp_path / "blocked"
    blocked.mkdir()
    log: AuditLog = AuditLog(blocked)  # a directory, so it cannot be appended to
    async with Client(build_server(book, log)) as client:
        result: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "work", "to": "a@x.com", "subject": "s", "body": "b"}
        )
    assert result.is_error
    assert mail_server.sent == []
