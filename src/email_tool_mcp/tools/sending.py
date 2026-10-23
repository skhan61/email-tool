"""The send tool, over implicit-TLS SMTP.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/sending.py, one module per tool group.
"""

from __future__ import annotations

from email.message import EmailMessage, Message

from email_tool_mcp.attachments import Attachment, load
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose, envelope_recipients
from email_tool_mcp.message_render import read_headers
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tools.params import (
    Attachments,
    Body,
    Cc,
    ConfirmSensitive,
    Html,
    InReplyToFolder,
    InReplyToUid,
    MailboxName,
    Subject,
    To,
)


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
        attachments: Attachments = None,
        confirm_sensitive: ConfirmSensitive = "",
        in_reply_to_uid: InReplyToUid = 0,
        in_reply_to_folder: InReplyToFolder = "INBOX",
    ) -> str:
        """Send an email immediately from this mailbox, with any attachments. This is not reversible.

        Attachments that look sensitive (keys, credentials, CUI) are shown to the user to confirm first.
        For a reply, `in_reply_to_uid` names the message answered, so the reply joins its conversation.
        """
        # confirm_sensitive is read by the approval step before this runs.
        sender: Mailbox = self._book.resolve(mailbox)
        files: list[Attachment] = load(attachments or [])
        parent: Message | None = None
        if in_reply_to_uid:
            with self._book.imap(sender) as session:
                parent = read_headers(session, in_reply_to_folder, in_reply_to_uid)
        message: EmailMessage = compose(sender.address, to, subject, body, cc, html, attachments=files, parent=parent)
        refused: dict[str, tuple[int, bytes]] = self._book.send(sender, message)
        if refused:
            return f"Sent, but {len(refused)} recipient(s) were refused: {sorted(refused)}"
        return f"Sent to {', '.join(envelope_recipients(message))}."
