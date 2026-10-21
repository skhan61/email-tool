"""The server, driven through the SDK's in-process client as an agent would.

Standard: the MCP SDK's `Client(server)` in-process transport, with anyio's pytest plugin.
Placement: tests/test_server.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest
from mcp import Client
from mcp_types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def text_of(result: CallToolResult) -> str:
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(book: MailboxBook, tool: str, arguments: dict[str, object]) -> CallToolResult:
    async with Client(build_server(book)) as client:
        return await client.call_tool(tool, arguments)


async def test_every_tool_is_listed_with_safety_hints(book: MailboxBook) -> None:
    async with Client(build_server(book)) as client:
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


async def test_missing_password_reaches_the_model_with_the_fix(book: MailboxBook) -> None:
    result: CallToolResult = await call(book, "list_emails", {"mailbox": "work"})
    assert result.is_error
    assert "email-tool-mcp add work" in text_of(result)
    assert "uvx --from" in text_of(result)


async def test_list_and_read_a_message(book: MailboxBook, mail_server: FakeMailServer) -> None:
    store_password("work", "secret")
    message: EmailMessage = compose("jane@example.com", "me@example.com", "Quarterly report", "Numbers inside.", "", "")
    uid: int = mail_server.add("INBOX", message.as_bytes())

    listing: CallToolResult = await call(book, "list_emails", {"mailbox": "work", "limit": 5})
    assert not listing.is_error
    assert "Quarterly report" in text_of(listing)

    full: CallToolResult = await call(book, "get_email", {"mailbox": "work", "uid": uid})
    assert "Numbers inside." in text_of(full)


async def test_send_uses_the_named_mailbox(book: MailboxBook, mail_server: FakeMailServer) -> None:
    store_password("home", "secret")
    result: CallToolResult = await call(
        book, "send_email", {"mailbox": "home", "to": "a@example.com", "subject": "Hi", "body": "hello"}
    )
    assert not result.is_error
    sent, recipients = mail_server.sent[0]
    assert sent["From"] == "me@gmail.com"
    assert recipients == ["a@example.com"]


async def test_update_draft_replaces_the_original(book: MailboxBook, mail_server: FakeMailServer) -> None:
    store_password("work", "secret")
    created: CallToolResult = await call(book, "create_draft", {"mailbox": "work", "folder": "Drafts", "to": "a@x.com"})
    assert not created.is_error
    await call(book, "update_draft", {"mailbox": "work", "folder": "Drafts", "uid": 1, "to": "b@x.com"})
    assert list(mail_server.folders["Drafts"]) == [2]
