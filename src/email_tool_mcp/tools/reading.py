"""Read-side tools: mailboxes, folders, listing, searching, reading, deleting.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/reading.py, one module per tool group.
"""

from __future__ import annotations

from datetime import datetime
from email.message import Message
from typing import Final

from email_tool_mcp.imap_session import ImapSession, SearchItem, text
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_render import (
    MessageSummary,
    attachment_names,
    extract_body,
    header_block,
    parse_message,
    summarize,
)
from email_tool_mcp.settings import SETUP_COMMAND, Mailbox
from email_tool_mcp.tools.params import Folder, Limit, MailboxName, Uid

_BODY_CHARACTER_LIMIT: Final[int] = 20_000


def newest_summaries(session: ImapSession, uids: list[int], limit: int) -> list[MessageSummary]:
    """Fetch header summaries for the `limit` highest UIDs in one round trip, newest first."""
    newest: list[int] = sorted(uids, reverse=True)[:limit]
    headers: dict[int, bytes] = session.fetch_headers(newest)
    return [summarize(uid, parse_message(headers[uid])) for uid in newest if uid in headers]


def render_summaries(summaries: list[MessageSummary], total: int) -> str:
    """Return a printable listing for `summaries` out of `total` matches."""
    if not summaries:
        return "No messages matched."
    blocks: list[str] = [summary.render() for summary in summaries]
    return f"{total} match(es), showing {len(summaries)} newest:\n\n" + "\n\n".join(blocks)


def search_criteria(sender: str, subject: str, body: str, since: str) -> list[SearchItem]:
    """Translate the search fields into IMAP SEARCH criteria."""
    criteria: list[SearchItem] = []
    for value, keyword in ((sender, "FROM"), (subject, "SUBJECT"), (body, "BODY")):
        if value:
            criteria.extend([keyword, text(value)])
    if since:
        try:
            criteria.extend(["SINCE", datetime.strptime(since, "%d-%b-%Y").date()])
        except ValueError as error:
            raise ValueError(f"since must look like 01-Jan-2026, got {since!r}") from error
    return criteria


def pending_deletion(uid: int, folder: str) -> str:
    """Explain a deletion left flagged because other messages were already flagged."""
    return (
        f"uid {uid} in {folder!r} is flagged as deleted but not yet removed: other messages there are "
        "also flagged, and removing it now would purge them too. The mail client will finish it."
    )


def render_message(message: Message) -> str:
    """Return headers, attachment names and the readable body, truncated."""
    body: str = extract_body(message)
    sections: list[str] = [header_block(message)]
    attachments: list[str] = attachment_names(message)
    if attachments:
        sections.append("Attachments: " + ", ".join(attachments))
    sections.append("-" * 60)
    sections.append(body[:_BODY_CHARACTER_LIMIT] or "(no readable body)")
    if len(body) > _BODY_CHARACTER_LIMIT:
        sections.append(f"... truncated at {_BODY_CHARACTER_LIMIT} characters.")
    return "\n".join(sections)


class ReadingTools:
    """Tools that read a mailbox, plus `delete_email`."""

    def __init__(self, book: MailboxBook) -> None:
        self._book: MailboxBook = book

    def list_mailboxes(self) -> str:
        """List the mailboxes configured on this machine and whether each has a password."""
        known: dict[str, Mailbox] = self._book.mailboxes()
        lines: list[str] = [
            f"{name}: {mailbox.address} ({'ready' if self._book.has_password(mailbox) else 'no password'})"
            for name, mailbox in sorted(known.items())
        ]
        if not known:
            lines.append(f"No mailbox is configured. Run `{SETUP_COMMAND} <name>` in a terminal.")
        if self._book.environment_problem:
            lines.append(self._book.environment_problem)
        return "\n".join(lines)

    # no-library: scikit-learn: list_folders lists IMAP mail folders, it is not a data split.
    def list_folders(self, mailbox: MailboxName = "") -> str:
        """List every folder in the mailbox."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            names: list[str] = session.list_folders()
        return "\n".join(sorted(names)) if names else "No folders found."

    def list_emails(self, mailbox: MailboxName = "", folder: Folder = "INBOX", limit: Limit = 20) -> str:
        """List the newest messages in a folder, newest first."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            count: int = session.select(folder, readonly=True)
            uids: list[int] = session.search(["ALL"])
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        return f"Folder {folder!r} holds {count} message(s).\n\n{render_summaries(summaries, len(uids))}"

    def search_emails(
        self,
        mailbox: MailboxName = "",
        folder: Folder = "INBOX",
        limit: Limit = 20,
        sender: str = "",
        subject: str = "",
        body: str = "",
        since: str = "",
        gmail_query: str = "",
    ) -> str:
        """Search a folder by sender, subject, body text or date (since, as DD-Mon-YYYY).

        On Gmail, `gmail_query` takes Gmail's own search syntax instead; other servers ignore it.
        Supply at least one field.
        """
        with self._book.imap(self._book.resolve(mailbox)) as session:
            gmail_capable: bool = session.supports_gmail_search()
            criteria: list[SearchItem] = search_criteria(sender, subject, body, since)
            use_gmail: bool = bool(gmail_query) and gmail_capable
            if not (use_gmail or criteria):
                raise ValueError("supply at least one of sender, subject, body, since or gmail_query")
            session.select(folder, readonly=True)
            uids: list[int] = session.gmail_search(gmail_query) if use_gmail else session.search(criteria)
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        note: str = "Note: this server is not Gmail, so gmail_query was ignored.\n\n"
        return (note if gmail_query and not gmail_capable else "") + render_summaries(summaries, len(uids))

    def get_email(self, uid: Uid, mailbox: MailboxName = "", folder: Folder = "INBOX") -> str:
        """Read one message in full by UID. Does not mark it as read."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            session.select(folder, readonly=True)
            raw: bytes | None = session.fetch_message(uid)
        if raw is None:
            return f"No message with uid {uid} in folder {folder!r}."
        return render_message(parse_message(raw))

    def delete_email(self, uid: Uid, folder: Folder, mailbox: MailboxName = "") -> str:
        """Permanently delete one message by UID. This cannot be undone."""
        with self._book.imap(self._book.resolve(mailbox)) as session:
            session.select(folder, readonly=False)
            expunged: bool = session.mark_deleted(uid)
        return f"Deleted uid {uid} from folder {folder!r}." if expunged else pending_deletion(uid, folder)
