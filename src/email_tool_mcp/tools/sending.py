"""The send tool, over implicit-TLS SMTP.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/sending.py, one module per tool group.
"""

from __future__ import annotations

from email.message import EmailMessage

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose, envelope_recipients
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tools.params import Body, Cc, Html, MailboxName, Subject, To


class SendingTools:
    """The one tool that sends mail."""

    def __init__(self, book: MailboxBook) -> None:
        self._book: MailboxBook = book

    def send_email(
        self,
        to: To,
        subject: Subject,
        body: Body,
        mailbox: MailboxName = "",
        cc: Cc = "",
        html: Html = "",
    ) -> str:
        """Send an email immediately from this mailbox. This is not reversible."""
        sender: Mailbox = self._book.resolve(mailbox)
        message: EmailMessage = compose(sender.address, to, subject, body, cc, html)
        recipients: list[str] = envelope_recipients(message)
        if not recipients:
            raise ValueError("no recipients resolved from the 'to' and 'cc' arguments")
        refused: dict[str, tuple[int, bytes]] = self._book.send(sender, message, recipients)
        if refused:
            return f"Sent, but {len(refused)} recipient(s) were refused: {sorted(refused)}"
        return f"Sent to {', '.join(recipients)}."
