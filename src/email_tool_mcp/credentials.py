"""How a mailbox proves who it is: a password, or an OAuth access token.

Standard: SASL XOAUTH2, the token login Microsoft and Google document for IMAP and
SMTP (`user=<address>^Aauth=Bearer <token>^A^A`); imapclient's `oauth2_login` for
IMAP and `smtplib.SMTP.auth("XOAUTH2", ...)` for SMTP.
Placement: credentials.py; MailboxBook builds one Credential per connection, and
imap_session.py and the SMTP paths log in with it.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from typing import Protocol, overload

from email_tool_mcp.settings import Mailbox


@dataclass(frozen=True)
class Credential:
    """What one login needs. The secret never appears in a repr or a log."""

    user: str
    secret: str = field(repr=False)
    is_token: bool


class TokenSource(Protocol):
    """Hands out OAuth access tokens for one provider, refreshing them as needed."""

    def access_token(self, mailbox: Mailbox) -> str:
        """A currently valid access token; raises when the user must sign in again."""
        ...

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        """True when a stored sign-in exists, without contacting the provider."""
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


def smtp_login(smtp: smtplib.SMTP, credential: Credential) -> None:
    """Log in on an open SMTP connection with a password or an XOAUTH2 token."""
    if credential.is_token:
        smtp.auth("XOAUTH2", Xoauth2Responder(credential.user, credential.secret), initial_response_ok=True)
    else:
        smtp.login(credential.user, credential.secret)
