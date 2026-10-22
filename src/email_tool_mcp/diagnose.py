"""`email-tool-mcp check <mailbox>`: show the connection is what the policy says (3.13.8, 3.13.11).

Standard: the negotiated protocol and cipher read from the live sockets (`SSLSocket.version()`,
`SSLSocket.cipher()`), the floor and verification read from the real client context, and
the FIPS state from tls.py; evidence an assessor can re-run. The check is audit-logged.
Placement: diagnose.py, which `__main__.py` dispatches the `check` command to.
"""

from __future__ import annotations

import smtplib
import ssl

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.credentials import smtp_login
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tls import (
    client_context,
    describe_context,
    fips_enabled,
    sign_in_storage_fips_enabled,
    socket_details,
)


def imap_line(book: MailboxBook, mailbox: Mailbox) -> str:
    """One report line for the IMAP login; a refusal is reported, not raised."""
    where: str = f"  IMAP {mailbox.imap_host}:{mailbox.imap_port}"
    try:
        with book.imap(mailbox) as session:
            return f"{where}  {session.tls_details()}  (login ok)"
    except Exception as error:
        return f"{where}  REFUSED: {type(error).__name__}: {error}"


def smtp_line(book: MailboxBook, mailbox: Mailbox) -> str:
    """One report line for the SMTP login; a refusal is reported, not raised."""
    where: str = f"  SMTP {mailbox.smtp_host}:{mailbox.smtp_port}"
    try:
        smtp: smtplib.SMTP
        with book.smtp(mailbox) as smtp:
            smtp_login(smtp, book.credential(mailbox))
            sock: ssl.SSLSocket = smtp.sock  # type: ignore[assignment]
            return f"{where}  {socket_details(sock)}  (login ok)"
    except Exception as error:
        return f"{where}  REFUSED: {type(error).__name__}: {error}"


def check_mailbox(book: MailboxBook, audit: AuditLog, name: str) -> str:
    """Log in over IMAP and SMTP and report the TLS each negotiated, what is enforced, and FIPS."""
    mailbox: Mailbox = book.resolve(name)
    call: str = audit.started(mailbox.name, "check", {})
    lines: list[str] = [
        f"{mailbox.name} ({mailbox.address})",
        imap_line(book, mailbox),
        smtp_line(book, mailbox),
        f"  {describe_context(client_context())}   OpenSSL: {ssl.OPENSSL_VERSION}",
        f"  FIPS mode: {'on' if fips_enabled() else 'off'}"
        + (
            f"   sign-in storage FIPS: {'on' if sign_in_storage_fips_enabled() else 'off'}"
            if mailbox.auth != "password"
            else ""
        ),
    ]
    refused: bool = any("REFUSED" in line for line in lines)
    audit.finished(call, mailbox.name, "check", "refused" if refused else "ok")
    return "\n".join(lines)
