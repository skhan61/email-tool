"""The send tool, over implicit-TLS SMTP.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/sending.py, one module per tool group.
"""

from __future__ import annotations

from email.message import EmailMessage, Message

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose, envelope_recipients
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tools.params import Body, Cc, Html, InReplyToFolder, InReplyToUid, MailboxName, Subject, To
from email_tool_mcp.tools.reading import reply_parent


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
        in_reply_to_uid: InReplyToUid = 0,
        in_reply_to_folder: InReplyToFolder = "INBOX",
    ) -> str:
        """Send an email immediately from this mailbox. This is not reversible.

        For a reply, `in_reply_to_uid` names the message answered, so the reply joins its conversation.
        """
        sender: Mailbox = self._book.resolve(mailbox)
        parent: Message | None = None
        if in_reply_to_uid:
            with self._book.imap(sender) as session:
                parent = reply_parent(session, in_reply_to_folder, in_reply_to_uid)
        message: EmailMessage = compose(sender.address, to, subject, body, cc, html, parent)
        refused: dict[str, tuple[int, bytes]] = self._book.send(sender, message)
        if refused:
            return f"Sent, but {len(refused)} recipient(s) were refused: {sorted(refused)}"
        return f"Sent to {', '.join(envelope_recipients(message))}."
