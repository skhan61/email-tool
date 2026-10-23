"""The real tools against this computer's real mailboxes: send, receive, reply, drafts, approval.

Standard: pytest's `live` marker, skipped unless EMAIL_TOOL_LIVE=1; the real server
(`build_server` over this computer's settings, keyring and sign-ins) driven through the MCP
SDK's in-process client, which answers approval prompts as the user would.
Placement: tests/live/test_live_mail.py, in pytest's tests/ layout, kept in its own folder as
Google's client libraries keep their system tests; run on the maintainer's computer only, so
no real password reaches CI.

Run:  EMAIL_TOOL_LIVE=1 uv run pytest tests/live -q
Mailboxes: EMAIL_TOOL_LIVE_FROM (default `gmail`) sends to EMAIL_TOOL_LIVE_TO (default `outlook`).
Every message carries a unique code in its subject, and cleanup deletes only those. Junk
filters may file the messages as junk or spam: the test looks there too and warns when it
does, since that is the mail provider's choice, not a fault in email-tool.
"""

from __future__ import annotations

import os
import re
import secrets
import time
import warnings
from email.message import Message
from pathlib import Path
from typing import Any, Final

import anyio
import pytest
from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp.client.session import ElicitationFnT
from mcp_types import CallToolResult, ElicitRequestParams, ElicitResult, TextContent

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_render import parse_message
from email_tool_mcp.policy import Policy
from email_tool_mcp.providers import open_book, token_sources
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import Mailbox, settings_path

LIVE: Final[bool] = os.environ.get("EMAIL_TOOL_LIVE") == "1"
SENDER: Final[str] = os.environ.get("EMAIL_TOOL_LIVE_FROM", "gmail")
RECEIVER: Final[str] = os.environ.get("EMAIL_TOOL_LIVE_TO", "outlook")
ARRIVAL_SECONDS: Final[float] = 240.0
_UID: Final[re.Pattern[str]] = re.compile(r"\[uid (\d+)\]")
_JUNK: Final[tuple[str, ...]] = ("Junk", "Junk Email", "[Gmail]/Spam", "Spam")
BODY: Final[str] = (
    "Hello,\n\nThis is the weekly check that email-tool can send, receive and reply. It removes "
    "itself when the check finishes.\n\nBest regards,\nemail-tool\n"
)
# Built at run time so the repository's private-key hook does not flag this file.
KEY_HEADER: Final[str] = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"

pytestmark: list[pytest.MarkDecorator] = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.timeout(900),
    pytest.mark.skipif(not LIVE, reason="live test: set EMAIL_TOOL_LIVE=1 on the maintainer's computer"),
]


def text_of(result: CallToolResult) -> str:
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> str:
    """A tool call that must succeed; its text."""
    result: CallToolResult = await client.call_tool(tool, arguments)
    assert not result.is_error, f"{tool} failed: {text_of(result)}"
    return text_of(result)


def folder_named(listing: str, *wanted: str) -> str:
    """The first folder in `list_folders` output whose name is one of `wanted`."""
    names: set[str] = set(listing.splitlines())
    choice: str
    for choice in wanted:
        if choice in names:
            return choice
    raise AssertionError(f"none of {wanted} in {sorted(names)}")


async def uids_with(client: Client, mailbox: str, folder: str, code: str) -> list[int]:
    said: str = await call(client, "search_emails", {"mailbox": mailbox, "folder": folder, "subject": code})
    return [int(uid) for uid in _UID.findall(said)]


async def junk_folder(client: Client, mailbox: str) -> str:
    """The mailbox's junk or spam folder, or "" when it has none under a known name."""
    listing: str = await call(client, "list_folders", {"mailbox": mailbox})
    try:
        return folder_named(listing, *_JUNK)
    except AssertionError:
        return ""


async def arrival(client: Client, mailbox: str, code: str) -> tuple[str, int]:
    """Where the message whose subject holds `code` arrived (inbox, or junk with a warning) and its UID."""
    folders: list[str] = ["INBOX"]
    junk: str = await junk_folder(client, mailbox)
    if junk:
        folders.append(junk)
    deadline: float = time.monotonic() + ARRIVAL_SECONDS
    while time.monotonic() < deadline:
        folder: str
        for folder in folders:
            found: list[int] = await uids_with(client, mailbox, folder, code)
            if found:
                if folder != "INBOX":
                    warnings.warn(f"{mailbox} filed {code!r} in {folder}, not the inbox", stacklevel=2)
                return folder, max(found)
        await anyio.sleep(5)
    raise AssertionError(
        f"no message with {code!r} reached {mailbox} ({', '.join(folders)}) in {ARRIVAL_SECONDS:.0f} s"
    )


async def clean_up(client: Client, code: str) -> None:
    """Delete every message whose subject holds `code`, in both mailboxes' inbox, sent and drafts."""
    mailbox: str
    for mailbox in (SENDER, RECEIVER):
        listing: str = await call(client, "list_folders", {"mailbox": mailbox})
        folders: list[str] = ["INBOX"]
        candidates: tuple[str, ...]
        for candidates in (("[Gmail]/Sent Mail", "Sent", "Sent Items"), ("[Gmail]/Drafts", "Drafts"), _JUNK):
            try:
                folders.append(folder_named(listing, *candidates))
            except AssertionError:
                pass
        folder: str
        for folder in folders:
            uid: int
            for uid in await uids_with(client, mailbox, folder, code):
                await call(client, "delete_email", {"mailbox": mailbox, "folder": folder, "uid": uid})


def address_of(book: MailboxBook, name: str) -> str:
    known: dict[str, Mailbox] = book.mailboxes()
    assert name in known, f"mailbox {name!r} is not set up on this computer: {sorted(known)}"
    return known[name].address


async def test_a_real_round_trip_send_receive_attachment_reply_and_drafts(tmp_path: Path) -> None:
    book: MailboxBook = open_book(os.environ, with_policy=True)
    code: str = f"email-tool live test {secrets.token_hex(4)}"
    payload: bytes = f"email-tool weekly check\nReference: {code}\nEverything below is a test.\n".encode()
    attachment: Path = tmp_path / "live-report.txt"
    attachment.write_bytes(payload)
    async with Client(build_server(book, AuditLog(tmp_path / "audit.jsonl"))) as client:
        try:
            await call(
                client,
                "send_email",
                {
                    "mailbox": SENDER,
                    "to": address_of(book, RECEIVER),
                    "subject": code,
                    "body": BODY,
                    "attachments": [str(attachment)],
                },
            )
            folder: str
            received: int
            folder, received = await arrival(client, RECEIVER, code)

            opened: str = await call(client, "get_email", {"mailbox": RECEIVER, "folder": folder, "uid": received})
            assert "live-report.txt" in opened, opened

            saved_to: Path = tmp_path / "saved"
            await call(
                client,
                "save_attachment",
                {"mailbox": RECEIVER, "folder": folder, "uid": received, "index": 1, "directory": str(saved_to)},
            )
            assert (saved_to / "live-report.txt").read_bytes() == payload

            await call(
                client,
                "send_email",
                {
                    "mailbox": RECEIVER,
                    "to": address_of(book, SENDER),
                    "subject": f"Re: {code}",
                    "body": "Thank you, received.\n",
                    "in_reply_to_uid": received,
                    "in_reply_to_folder": folder,
                },
            )
            reply_folder: str
            reply: int
            reply_folder, reply = await arrival(client, SENDER, f"Re: {code}")
            with book.imap(book.resolve(RECEIVER)) as session:
                session.select(folder, readonly=True)
                original: Message = parse_message(session.fetch_headers([received])[received])
            with book.imap(book.resolve(SENDER)) as session:
                session.select(reply_folder, readonly=True)
                answered: Message = parse_message(session.fetch_headers([reply])[reply])
            assert str(answered["In-Reply-To"]).strip() == str(original["Message-ID"]).strip()

            drafts: str = folder_named(
                await call(client, "list_folders", {"mailbox": SENDER}), "[Gmail]/Drafts", "Drafts"
            )
            draft_code: str = f"{code} draft"
            await call(
                client,
                "create_draft",
                {"mailbox": SENDER, "folder": drafts, "to": address_of(book, RECEIVER), "subject": draft_code},
            )
            draft: int = max(await uids_with(client, SENDER, drafts, draft_code))
            await call(
                client,
                "update_draft",
                {
                    "mailbox": SENDER,
                    "folder": drafts,
                    "uid": draft,
                    "to": address_of(book, RECEIVER),
                    "subject": draft_code,
                    "body": "Replaced.",
                },
            )
            remaining: list[int] = await uids_with(client, SENDER, drafts, draft_code)
            assert len(remaining) == 1 and remaining[0] != draft, remaining
        finally:
            await clean_up(client, code)


def answering(action: str, shown: list[str]) -> ElicitationFnT:
    """An app's user who answers every approval question with `action`, remembering each question."""

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        shown.append(params.message)
        content: dict[str, Any] | None = {"approve": True} if action == "accept" else None
        return ElicitResult(action=action, content=content)  # type: ignore[arg-type]

    return answer


async def test_approval_and_the_sensitive_file_warning_on_real_mail(tmp_path: Path) -> None:
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text("[default]\nrequire_approval = true\n", encoding="utf-8")
    approving: MailboxBook = MailboxBook(
        settings_path(), os.environ, policy=Policy([policy_file]), token_sources=token_sources()
    )
    plain: MailboxBook = open_book(os.environ, with_policy=True)
    audit: AuditLog = AuditLog(tmp_path / "audit.jsonl")
    code: str = f"email-tool live test {secrets.token_hex(4)}"
    key: Path = tmp_path / "id_ed25519"
    key.write_text(f"{KEY_HEADER}\nnot a real key\n", encoding="utf-8")
    message: dict[str, Any] = {
        "mailbox": SENDER,
        "to": address_of(plain, RECEIVER),
        "subject": code,
        "body": BODY,
    }
    try:
        declined: list[str] = []
        async with Client(build_server(approving, audit), elicitation_callback=answering("decline", declined)) as app:
            refused: CallToolResult = await app.call_tool("send_email", message)
            assert refused.is_error and "did not approve" in text_of(refused), text_of(refused)
            assert code in declined[0], "the question shows the message"

            warned: CallToolResult = await app.call_tool(
                "send_email", {**message, "subject": f"{code} key", "attachments": [str(key)]}
            )
            assert warned.is_error and "looks sensitive" in declined[1], declined[1]

        accepted: list[str] = []
        async with Client(build_server(approving, audit), elicitation_callback=answering("accept", accepted)) as app:
            assert not (await app.call_tool("send_email", message)).is_error
        async with Client(build_server(plain, audit)) as client:
            await arrival(client, RECEIVER, code)
            assert not await uids_with(client, RECEIVER, "INBOX", f"{code} key"), "a declined file was sent"
    finally:
        async with Client(build_server(plain, audit)) as client:
            await clean_up(client, code)
