"""Offline stand-ins for an IMAP server and an SMTP server.

Standard: test fakes injected at the boundary the code already owns (ImapSession, the SMTP factory).
Placement: tests/fakes.py, imported by conftest.py and the tests.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from types import TracebackType
from typing import Any

from email_tool_mcp.imap_session import ImapError, ImapSession
from email_tool_mcp.settings import Mailbox


@dataclass
class FakeMailServer:
    """Folders of raw messages keyed by UID, plus every message sent over SMTP."""

    folders: dict[str, dict[int, bytes]] = field(default_factory=lambda: {"INBOX": {}, "Drafts": {}})
    sent: list[tuple[EmailMessage, list[str]]] = field(default_factory=list)
    logins: list[tuple[str, str]] = field(default_factory=list)
    gmail: bool = False

    def open_imap(self, mailbox: Mailbox, password: str) -> ImapSession:
        """Return a session over this server; the ImapSession factory signature."""
        self.logins.append((mailbox.address, password))
        return FakeSession(self)  # type: ignore[return-value]

    def open_smtp(self, mailbox: Mailbox) -> smtplib.SMTP:
        """Return an SMTP connection that records what it sends."""
        return FakeSmtp(self)  # type: ignore[return-value]

    def add(self, folder: str, raw: bytes) -> int:
        """Store `raw` in `folder` and return its new UID."""
        messages: dict[int, bytes] = self.folders.setdefault(folder, {})
        uid: int = max(messages, default=0) + 1
        messages[uid] = raw
        return uid


class FakeSession:
    """The subset of ImapSession the tools call."""

    def __init__(self, server: FakeMailServer) -> None:
        self._server: FakeMailServer = server
        self._folder: str = ""

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def supports_gmail_search(self) -> bool:
        return self._server.gmail

    def list_folders(self) -> list[str]:
        return list(self._server.folders)

    def select(self, folder: str, readonly: bool) -> int:
        if folder not in self._server.folders:
            raise ImapError(f"cannot select folder {folder!r}")
        self._folder = folder
        return len(self._server.folders[folder])

    def search(self, criteria: list[str]) -> list[int]:
        return sorted(self._server.folders[self._folder])

    def fetch(self, uid: int, parts: str) -> bytes | None:
        return self._server.folders[self._folder].get(uid)

    def append(self, folder: str, flags: str, raw_message: bytes) -> None:
        self._server.add(folder, raw_message)

    def mark_deleted(self, uid: int) -> None:
        del self._server.folders[self._folder][uid]


class FakeSmtp:
    """The subset of smtplib.SMTP that MailboxBook.send calls."""

    def __init__(self, server: FakeMailServer) -> None:
        self._server: FakeMailServer = server

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        self._server.logins.append((user, password))
        return (235, b"ok")

    def send_message(self, message: EmailMessage, to_addrs: list[str]) -> dict[str, tuple[int, bytes]]:
        self._server.sent.append((message, to_addrs))
        return {}
