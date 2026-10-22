"""Token login (XOAUTH2) and SMTP STARTTLS, with a fake token source standing in for a provider.

Standard: pytest with the offline fakes; smtplib is replaced by a recording stub only to check the TLS calls.
Placement: tests/test_credentials.py, beside credentials.py and the SMTP opening in mailbox_book.py.
"""

from __future__ import annotations

import smtplib
import ssl
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.credentials import Xoauth2Responder, xoauth2
from email_tool_mcp.mailbox_book import MailboxBook, open_smtp
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import Mailbox, SettingsError, load_mailboxes, save_mailboxes
from tests.fakes import FakeMailServer

OUTLOOK: Mailbox = Mailbox(
    "outlook", "me@outlook.com", "outlook.office365.com", 993, "smtp-mail.outlook.com", 587, auth="microsoft"
)


class FakeTokens:
    """A provider that is signed in and hands out one fixed token."""

    def __init__(self, signed_in: bool = True) -> None:
        self.signed_in: bool = signed_in

    def access_token(self, mailbox: Mailbox) -> str:
        if not self.signed_in:
            raise PermissionError(f"sign in again: email-tool-mcp add {mailbox.name} --auth {mailbox.auth}")
        return "token-123"

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        return self.signed_in


@pytest.fixture
def outlook_book(tmp_path: Path, mail_server: FakeMailServer) -> MailboxBook:
    path: Path = tmp_path / "mailboxes.toml"
    save_mailboxes(path, {"outlook": OUTLOOK})
    return MailboxBook(
        path, {}, mail_server.open_imap, mail_server.open_smtp, token_sources={"microsoft": FakeTokens()}
    )


def test_xoauth2_matches_microsofts_documented_format() -> None:
    expected: str = "user=test@contoso.onmicrosoft.com\x01auth=Bearer EwBAAl3BAAUFFpUAo7J3Ve0bjLBWZWCclRC3EoAA\x01\x01"
    assert xoauth2("test@contoso.onmicrosoft.com", "EwBAAl3BAAUFFpUAo7J3Ve0bjLBWZWCclRC3EoAA") == expected


def test_the_responder_answers_an_error_challenge_with_an_empty_line() -> None:
    respond: Xoauth2Responder = Xoauth2Responder("me@x.com", "t")
    assert respond(None) == xoauth2("me@x.com", "t")
    assert respond(b'{"status":"400"}') == ""


@pytest.mark.anyio
async def test_a_signed_in_mailbox_logs_in_with_its_token(
    outlook_book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    async with Client(build_server(outlook_book, audit)) as client:
        await client.call_tool("list_emails", {"mailbox": "outlook"})
        sent: CallToolResult = await client.call_tool(
            "send_email", {"mailbox": "outlook", "to": "a@example.com", "subject": "s", "body": "b"}
        )
    assert not sent.is_error
    assert ("imap", "token-123") in mail_server.token_logins
    assert ("smtp XOAUTH2", xoauth2("me@outlook.com", "token-123")) in mail_server.token_logins


def test_listing_says_when_a_sign_in_is_missing(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    save_mailboxes(path, {"outlook": OUTLOOK})
    book: MailboxBook = MailboxBook(path, {}, token_sources={"microsoft": FakeTokens(signed_in=False)})
    assert not book.has_credential(OUTLOOK)


def test_a_provider_this_version_lacks_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="microsoft sign-in is not available"):
        MailboxBook(tmp_path / "m.toml", {}).credential(OUTLOOK)


def test_old_settings_files_still_load(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    path.write_text(
        '[mailboxes.work]\naddress = "a@x.com"\nimap_host = "i"\nimap_port = 993\nsmtp_host = "s"\nsmtp_port = 465\n',
        encoding="utf-8",
    )
    assert load_mailboxes(path)["work"].auth == "password"


def test_sign_in_fields_round_trip(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    signed: Mailbox = Mailbox(
        "o", "me@outlook.com", "i", 993, "s", 587, auth="microsoft", client_id="abc", tenant="consumers"
    )
    save_mailboxes(path, {"o": signed})
    assert load_mailboxes(path)["o"] == signed


class RecordingSmtp:
    """Stands in for smtplib.SMTP / SMTP_SSL to show which TLS path open_smtp takes."""

    calls: list[tuple[str, Any]] = []

    def __init__(self, host: str, port: int, timeout: float, context: ssl.SSLContext | None = None) -> None:
        RecordingSmtp.calls.append(("connect", (host, port, context is not None)))

    def starttls(self, context: ssl.SSLContext) -> None:
        RecordingSmtp.calls.append(("starttls", context.minimum_version))

    def close(self) -> None:
        RecordingSmtp.calls.append(("close", None))


class NoStartTls(RecordingSmtp):
    def starttls(self, context: ssl.SSLContext) -> None:
        raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")


@pytest.mark.parametrize(("port", "starttls"), [(587, True), (465, False)])
def test_port_465_is_implicit_tls_and_others_use_starttls(
    monkeypatch: pytest.MonkeyPatch, port: int, starttls: bool
) -> None:
    RecordingSmtp.calls = []
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSmtp)
    open_smtp(Mailbox("o", "a@x.com", "i", 993, "smtp.x.com", port))
    assert (("starttls", ssl.TLSVersion.TLSv1_2) in RecordingSmtp.calls) is starttls
    assert RecordingSmtp.calls[0] == ("connect", ("smtp.x.com", port, not starttls))


def test_a_server_without_starttls_is_refused_and_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.calls = []
    monkeypatch.setattr(smtplib, "SMTP", NoStartTls)
    with pytest.raises(smtplib.SMTPNotSupportedError):
        open_smtp(Mailbox("o", "a@x.com", "i", 993, "smtp.x.com", 587))
    assert ("close", None) in RecordingSmtp.calls
