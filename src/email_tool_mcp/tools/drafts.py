"""Draft tools: create, list, read and replace drafts.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/drafts.py, one module per tool group.
"""

from __future__ import annotations

from email.message import EmailMessage, Message
from typing import Final

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.message_render import MessageSummary, parse_message
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tools.params import (
    Body,
    Cc,
    DraftsFolder,
    Html,
    InReplyToFolder,
    InReplyToUid,
    Limit,
    MailboxName,
    Subject,
    To,
    Uid,
)
from email_tool_mcp.tools.reading import (
    newest_summaries,
    pending_deletion,
    render_message,
    render_summaries,
    reply_parent,
)

_DRAFT_FLAGS: Final[tuple[str, ...]] = ("\\Draft",)


class DraftTools:
    """Tools that manage drafts without sending anything."""

    def __init__(self, book: MailboxBook) -> None:
        self._book: MailboxBook = book

    def create_draft(
        self,
        folder: DraftsFolder,
        to: To,
        mailbox: MailboxName = "",
        subject: Subject = "",
        body: Body = "",
        cc: Cc = "",
        html: Html = "",
        in_reply_to_uid: InReplyToUid = 0,
        in_reply_to_folder: InReplyToFolder = "INBOX",
    ) -> str:
        """Save a new draft into the drafts folder. Does not send it.

        For a reply, `in_reply_to_uid` names the message answered, so the draft joins its conversation.
        """
        sender: Mailbox = self._book.resolve(mailbox)
        with self._book.imap(sender) as session:
            parent: Message | None = reply_parent(session, in_reply_to_folder, in_reply_to_uid)
            message: EmailMessage = compose(sender.address, to, subject, body, cc, html, parent)
            self._book.approve(sender, message)
            session.append(folder, _DRAFT_FLAGS, message.as_bytes())
        return f"Draft saved to {folder!r} for {to}."

    def list_drafts(self, folder: DraftsFolder, mailbox: MailboxName = "", limit: Limit = 20) -> str:
        """List the newest drafts, newest first."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            session.select(folder, readonly=True)
            uids: list[int] = session.search(["ALL"])
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        return render_summaries(summaries, len(uids))

    def get_draft(self, folder: DraftsFolder, uid: Uid, mailbox: MailboxName = "") -> str:
        """Read one draft in full by UID."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            session.select(folder, readonly=True)
            raw: bytes | None = session.fetch_message(uid)
        if raw is None:
            return f"No draft with uid {uid} in folder {folder!r}."
        return render_message(parse_message(raw))

    def update_draft(
        self,
        folder: DraftsFolder,
        uid: Uid,
        to: To,
        mailbox: MailboxName = "",
        subject: Subject = "",
        body: Body = "",
        cc: Cc = "",
        html: Html = "",
        in_reply_to_uid: InReplyToUid = 0,
        in_reply_to_folder: InReplyToFolder = "INBOX",
    ) -> str:
        """Replace an existing draft with new content, keyed by UID.

        IMAP has no in-place edit: the replacement is stored first, then the original deleted.
        A reply draft passes `in_reply_to_uid` again, or the replacement leaves the conversation.
        """
        sender: Mailbox = self._book.resolve(mailbox)
        with self._book.imap(sender) as session:
            parent: Message | None = reply_parent(session, in_reply_to_folder, in_reply_to_uid)
            message: EmailMessage = compose(sender.address, to, subject, body, cc, html, parent)
            self._book.approve(sender, message)
            session.select(folder, readonly=False)
            if not session.exists(uid):
                raise LookupError(f"no draft with uid {uid} in folder {folder!r}; nothing was changed")
            session.append(folder, _DRAFT_FLAGS, message.as_bytes())
            expunged: bool = session.mark_deleted(uid)
        replaced: str = f"Draft uid {uid} in {folder!r} replaced."
        return replaced if expunged else f"{replaced} {pending_deletion(uid, folder)}"
