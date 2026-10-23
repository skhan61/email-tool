"""How a mailbox proves who it is: a password, or an OAuth access token. The one place logins happen.

Standard: SASL XOAUTH2, the token login Microsoft and Google document for IMAP and
SMTP (`user=<address>^Aauth=Bearer <token>^A^A`); imapclient's `oauth2_login` for
IMAP and `smtplib.SMTP.auth("XOAUTH2", ...)` after EHLO for SMTP.
Placement: credentials.py; MailboxBook builds one Credential per connection, and
imap_session.py and every SMTP path log in through `imap_login` / `smtp_login`.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from typing import Any, Protocol, overload

from email_tool_mcp.settings import Mailbox

XOAUTH2: str = "XOAUTH2"


@dataclass(frozen=True)
class Credential:
    """What one login needs. The secret never appears in a repr or a log."""

    user: str
    secret: str = field(repr=False)
    is_token: bool


class SignInRequired(PermissionError):
    """A kept sign-in is missing, expired or revoked; the user must sign in again."""

    def __init__(self, name: str, provider: str, command: str, detail: str = "") -> None:
        reason: str = f" ({detail})" if detail else ""
        super().__init__(
            f"{name} needs a new {provider} sign-in{reason}. Call add_mailbox to open a setup page, or run "
            f"`{command}` in a terminal."
        )


class TokenSource(Protocol):
    """Hands out OAuth access tokens for one provider, refreshing them as needed."""

    def access_token(self, mailbox: Mailbox) -> str:
        """A currently valid access token; raises when the user must sign in again."""
        ...

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        """True when a stored sign-in exists, without contacting the provider."""
        ...

    def forget(self, mailbox: Mailbox) -> None:
        """Delete the stored sign-in for `mailbox`, if any."""
        ...


def xoauth2(user: str, token: str) -> str:
    """The SASL XOAUTH2 initial response, before base64 (the libraries encode it)."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


class Xoauth2Responder:
    """smtplib auth object: the token first; an empty reply to an error challenge ends the exchange."""

    def __init__(self, user: str, token: str) -> None:
        self._initial: str = xoauth2(user, token)

    @overload
    def __call__(self, challenge: None = None, /) -> str | None: ...

    @overload
    def __call__(self, challenge: bytes, /) -> str: ...

    def __call__(self, challenge: bytes | None = None, /) -> str | None:
        return "" if challenge else self._initial


def imap_login(client: Any, credential: Credential) -> None:
    """Log an imapclient connection in with a password or an XOAUTH2 token."""
    if credential.is_token:
        client.oauth2_login(credential.user, credential.secret)
    else:
        client.login(credential.user, credential.secret)


def smtp_login(smtp: smtplib.SMTP, credential: Credential) -> None:
    """Log in on an open SMTP connection with a password or an XOAUTH2 token.

    `SMTP.auth`, unlike `login`, does not send EHLO itself, and it treats a 503 reply
    as success; so EHLO is sent first and the server must offer XOAUTH2.
    """
    if not credential.is_token:
        smtp.login(credential.user, credential.secret)
        return
    smtp.ehlo_or_helo_if_needed()
    offered: list[str] = smtp.esmtp_features.get("auth", "").upper().split()
    if XOAUTH2 not in offered:
        raise smtplib.SMTPNotSupportedError("the SMTP server does not offer XOAUTH2 token login")
    smtp.auth(XOAUTH2, Xoauth2Responder(credential.user, credential.secret), initial_response_ok=True)
