"""Prove a mailbox login works before anything is written to disk.

Verifying first means a typo is caught while the user is still sitting there,
instead of surfacing later as an MCP server that will not start.
"""

from __future__ import annotations

import imaplib
import logging
import smtplib
import ssl
from typing import Final

from mailbox_catalog import Mailbox

logger: Final[logging.Logger] = logging.getLogger(__name__)


def _verified_context() -> ssl.SSLContext:
    context: ssl.SSLContext = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def check_imap(mailbox: Mailbox, user: str, password: str) -> str | None:
    """Return None when IMAP login succeeds, else a human-readable reason."""
    try:
        connection: imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
            host=mailbox.imap_host, port=mailbox.imap_port, ssl_context=_verified_context()
        )
    except (OSError, ssl.SSLError) as error:
        return f"cannot reach {mailbox.imap_host}:{mailbox.imap_port}: {error}"
    try:
        connection.login(user, password)
    except imaplib.IMAP4.error as error:
        return f"IMAP rejected the login: {error}"
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return None


def check_smtp(mailbox: Mailbox, user: str, password: str) -> str | None:
    """Return None when SMTP login succeeds, else a human-readable reason."""
    try:
        with smtplib.SMTP_SSL(
            host=mailbox.smtp_host, port=mailbox.smtp_port, context=_verified_context(), timeout=30
        ) as smtp:
            smtp.login(user, password)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as error:
        return f"SMTP rejected the login: {error}"
    return None
