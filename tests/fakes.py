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

from imapclient import IMAPClient

from email_tool_mcp.credentials import Credential, Xoauth2Responder
from email_tool_mcp.imap_session import ImapSession, SearchItem
from email_tool_mcp.settings import Mailbox


@dataclass
class FakeMailServer:
    """Folders of raw messages keyed by UID, plus every message sent over SMTP."""

    folders: dict[str, dict[int, bytes]] = field(default_factory=lambda: {"INBOX": {}, "Drafts": {}})
    sent: list[tuple[EmailMessage, list[str]]] = field(default_factory=list)
    logins: list[tuple[str, str]] = field(default_factory=list)
    token_logins: list[tuple[str, str]] = field(default_factory=list)
    gmail: bool = False

    def open_imap(self, mailbox: Mailbox, credential: Credential) -> ImapSession:
        """Return a session over this server; the ImapSession factory signature."""
        self.logins.append((credential.user, credential.secret))
        if credential.is_token:
            self.token_logins.append(("imap", credential.secret))
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

    def tls_details(self) -> str:
        return "TLSv1.3 TLS_AES_256_GCM_SHA384"

    def list_folders(self) -> list[str]:
        return list(self._server.folders)

    def select(self, folder: str, readonly: bool) -> int:
        if folder not in self._server.folders:
            raise IMAPClient.Error(f"cannot select folder {folder!r}")
        self._folder = folder
        return len(self._server.folders[folder])

    def search(self, criteria: list[SearchItem]) -> list[int]:
        return sorted(self._server.folders[self._folder])

    def exists(self, uid: int) -> bool:
        return uid in self._server.folders[self._folder]

    def gmail_search(self, query: str) -> list[int]:
        return sorted(self._server.folders[self._folder])

    def fetch_headers(self, uids: list[int]) -> dict[int, bytes]:
        messages: dict[int, bytes] = self._server.folders[self._folder]
        return {uid: messages[uid] for uid in uids if uid in messages}

    def fetch_message(self, uid: int) -> bytes | None:
        return self._server.folders[self._folder].get(uid)

    def append(self, folder: str, flags: tuple[str, ...], raw_message: bytes) -> None:
        self._server.add(folder, raw_message)

    def mark_deleted(self, uid: int) -> bool:
        if not self.exists(uid):
            raise LookupError(f"no message with uid {uid} in this folder")
        del self._server.folders[self._folder][uid]
        return True


class FakeTlsSocket:
    """What `smtp.sock` reports after a TLS handshake."""

    def version(self) -> str:
        return "TLSv1.3"

    def cipher(self) -> tuple[str, str, int]:
        return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)


class FakeSmtp:
    """The subset of smtplib.SMTP that MailboxBook.send calls."""

    def __init__(self, server: FakeMailServer) -> None:
        self._server: FakeMailServer = server
        self.sock: FakeTlsSocket = FakeTlsSocket()

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        self._server.logins.append((user, password))
        return (235, b"ok")

    def auth(self, mechanism: str, authobject: Xoauth2Responder, initial_response_ok: bool = True) -> None:
        response: str | None = authobject(None)
        self._server.token_logins.append((f"smtp {mechanism}", response or ""))

    def send_message(self, message: EmailMessage, to_addrs: list[str]) -> dict[str, tuple[int, bytes]]:
        self._server.sent.append((message, to_addrs))
        return {}
