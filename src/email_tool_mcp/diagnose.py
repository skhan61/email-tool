"""`email-tool-mcp check <mailbox>`: prove the connection is what the policy says (3.13.8, 3.13.11).

Standard: the negotiated protocol and cipher read from the live sockets (`SSLSocket.version()`,
`SSLSocket.cipher()`), plus the FIPS state from tls.py; evidence an assessor can re-run.
Placement: diagnose.py, which `__main__.py` dispatches the `check` command to.
"""

from __future__ import annotations

import smtplib
import ssl
from typing import Any

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tls import fips_enabled


def socket_details(sock: Any) -> str:
    """Protocol and cipher of a TLS socket, e.g. TLSv1.3 TLS_AES_256_GCM_SHA384."""
    cipher: tuple[str, str, int] | None = sock.cipher()
    return f"{sock.version()} {cipher[0] if cipher else '?'}"


def check_mailbox(book: MailboxBook, name: str) -> str:
    """Log in over IMAP and SMTP and report the TLS each negotiated, plus the FIPS state."""
    mailbox: Mailbox = book.resolve(name)
    with book.imap(mailbox) as session:
        imap_tls: str = session.tls_details()
    smtp: smtplib.SMTP
    with book.smtp(mailbox) as smtp:
        smtp.login(mailbox.address, book.password(mailbox))
        smtp_tls: str = socket_details(smtp.sock)
    return "\n".join(
        [
            f"{mailbox.name} ({mailbox.address})",
            f"  IMAP {mailbox.imap_host}:{mailbox.imap_port}  {imap_tls}  (login ok)",
            f"  SMTP {mailbox.smtp_host}:{mailbox.smtp_port}  {smtp_tls}  (login ok)",
            f"  minimum accepted: TLS 1.2   certificate verification: on   OpenSSL: {ssl.OPENSSL_VERSION}",
            f"  FIPS mode: {'on' if fips_enabled() else 'off'}",
        ]
    )
