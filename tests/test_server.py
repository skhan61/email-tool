"""The server, driven through the SDK's in-process client as an agent would.

Standard: the MCP SDK's `Client(server)` in-process transport, with anyio's pytest plugin.
Placement: tests/test_server.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import json
from email import message_from_bytes
from email.message import EmailMessage, Message

import pytest
from mcp import Client
from mcp_types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.passwords import store_password
from email_tool_mcp.server import build_server
from tests.fakes import FakeMailServer

pytestmark: pytest.MarkDecorator = pytest.mark.anyio

TOOL_NAMES: set[str] = {
    "list_mailboxes",
    "list_folders",
    "list_emails",
    "search_emails",
    "get_email",
    "delete_email",
    "create_draft",
    "list_drafts",
    "get_draft",
    "update_draft",
    "send_email",
}


def text_of(result: CallToolResult) -> str:
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(book: MailboxBook, audit: AuditLog, tool: str, arguments: dict[str, object]) -> CallToolResult:
    async with Client(build_server(book, audit)) as client:
        return await client.call_tool(tool, arguments)


async def test_every_tool_is_listed_with_safety_hints(book: MailboxBook, audit: AuditLog) -> None:
    async with Client(build_server(book, audit)) as client:
        listed: ListToolsResult = await client.list_tools()
    tools: dict[str, Tool] = {tool.name: tool for tool in listed.tools}
    assert set(tools) == TOOL_NAMES
    hints: dict[str, ToolAnnotations] = {name: tool.annotations for name, tool in tools.items() if tool.annotations}
    assert set(hints) == TOOL_NAMES
    assert {name for name, hint in hints.items() if hint.destructive_hint} == {
        "delete_email",
        "update_draft",
        "send_email",
    }
    assert hints["list_emails"].read_only_hint
    assert "mailbox" in tools["list_emails"].input_schema["properties"]


async def test_missing_password_reaches_the_model_with_the_fix(book: MailboxBook, audit: AuditLog) -> None:
    result: CallToolResult = await call(book, audit, "list_emails", {"mailbox": "work"})
    assert result.is_error
    assert "email-tool-mcp add work" in text_of(result)
    assert "uvx --from" in text_of(result)


async def test_list_and_read_a_message(book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer) -> None:
    store_password("work", "secret")
    message: EmailMessage = compose("jane@example.com", "me@example.com", "Quarterly report", "Numbers inside.", "", "")
    uid: int = mail_server.add("INBOX", message.as_bytes())

    listing: CallToolResult = await call(book, audit, "list_emails", {"mailbox": "work", "limit": 5})
    assert not listing.is_error
    assert "Quarterly report" in text_of(listing)

    full: CallToolResult = await call(book, audit, "get_email", {"mailbox": "work", "uid": uid})
    assert "Numbers inside." in text_of(full)


async def test_send_uses_the_named_mailbox(book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer) -> None:
    store_password("home", "secret")
    result: CallToolResult = await call(
        book, audit, "send_email", {"mailbox": "home", "to": "a@example.com", "subject": "Hi", "body": "hello"}
    )
    assert not result.is_error
    sent, recipients = mail_server.sent[0]
    assert sent["From"] == "me@gmail.com"
    assert recipients == ["a@example.com"]


async def test_update_draft_replaces_the_original(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "secret")
    created: CallToolResult = await call(
        book, audit, "create_draft", {"mailbox": "work", "folder": "Drafts", "to": "a@x.com"}
    )
    assert not created.is_error
    await call(book, audit, "update_draft", {"mailbox": "work", "folder": "Drafts", "uid": 1, "to": "b@x.com"})
    assert list(mail_server.folders["Drafts"]) == [2]


async def test_update_draft_with_a_wrong_uid_changes_nothing(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "secret")
    await call(book, audit, "create_draft", {"mailbox": "work", "folder": "Drafts", "to": "a@x.com"})
    result: CallToolResult = await call(
        book, audit, "update_draft", {"mailbox": "work", "folder": "Drafts", "uid": 99, "to": "b@x.com"}
    )
    assert result.is_error
    assert list(mail_server.folders["Drafts"]) == [1]


PARENT_ID: str = "<parent@example.com>"


def add_parent(mail_server: FakeMailServer) -> int:
    parent: EmailMessage = compose("jane@example.com", "me@example.com", "Plan", "Thoughts?", "", "")
    parent.replace_header("Message-ID", PARENT_ID)
    return mail_server.add("INBOX", parent.as_bytes())


def saved_draft(mail_server: FakeMailServer) -> Message:
    return message_from_bytes(list(mail_server.folders["Drafts"].values())[-1])


async def test_a_reply_draft_joins_the_parents_thread(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "secret")
    uid: int = add_parent(mail_server)
    reply: dict[str, object] = {"mailbox": "work", "folder": "Drafts", "to": "jane@example.com", "in_reply_to_uid": uid}
    assert not (await call(book, audit, "create_draft", reply)).is_error
    assert saved_draft(mail_server)["In-Reply-To"] == PARENT_ID
    assert not (await call(book, audit, "update_draft", {**reply, "uid": 1})).is_error
    assert list(mail_server.folders["Drafts"]) == [2]
    assert saved_draft(mail_server)["References"] == PARENT_ID


async def test_a_sent_reply_joins_the_parents_thread(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "secret")
    uid: int = add_parent(mail_server)
    arguments: dict[str, object] = {
        "mailbox": "work",
        "to": "jane@example.com",
        "subject": "Re: Plan",
        "body": "Yes.",
        "in_reply_to_uid": uid,
    }
    assert not (await call(book, audit, "send_email", arguments)).is_error
    assert mail_server.sent[0][0]["In-Reply-To"] == PARENT_ID


@pytest.mark.parametrize("tool", ["create_draft", "send_email"])
async def test_a_reply_to_a_missing_message_saves_and_sends_nothing(
    tool: str, book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "secret")
    arguments: dict[str, object] = {"mailbox": "work", "to": "a@x.com", "subject": "Re", "in_reply_to_uid": 42}
    arguments.update({"folder": "Drafts"} if tool == "create_draft" else {"body": "x"})
    result: CallToolResult = await call(book, audit, tool, arguments)
    assert result.is_error
    assert "no message with uid 42" in text_of(result)
    assert not mail_server.folders.get("Drafts") and mail_server.sent == []


async def test_broken_unicode_is_refused_by_name_and_still_audited(book: MailboxBook, audit: AuditLog) -> None:
    """JSON can carry an unpaired surrogate; it used to escape as a raw UnicodeEncodeError (found by fuzzing)."""
    store_password("work", "secret")
    result: CallToolResult = await call(book, audit, "search_emails", {"mailbox": "work", "subject": "\ud800"})
    assert result.is_error
    assert "subject contains invalid text" in text_of(result)
    finished: list[dict[str, object]] = [
        record
        for record in map(json.loads, audit.path.read_text(encoding="utf-8").splitlines())
        if record.get("phase") == "finished"
    ]
    assert finished[-1]["tool"] == "search_emails"
    assert "subject contains invalid text" in str(finished[-1]["outcome"])
