"""Message-level tools: listing, searching, reading and deleting."""

from __future__ import annotations

from email.message import Message
from typing import Any, Final

from imap_session import ImapSession
from message_render import (
    MessageSummary,
    attachment_names,
    extract_body,
    header_block,
    parse_message,
    summarize,
)
from tools.base import Tool

_HEADERS_PART: Final[str] = "(BODY.PEEK[HEADER])"
_FULL_PART: Final[str] = "(BODY.PEEK[])"
_BODY_CHARACTER_LIMIT: Final[int] = 20_000


def quote_criterion(value: str) -> str:
    """Return `value` as a quoted IMAP string literal."""
    escaped: str = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def newest_summaries(session: ImapSession, uids: list[int], limit: int) -> list[MessageSummary]:
    """Fetch header summaries for the newest `limit` UIDs, newest first."""
    selected: list[int] = uids[-limit:][::-1]
    summaries: list[MessageSummary] = []
    for uid in selected:
        raw: bytes | None = session.fetch(uid, _HEADERS_PART)
        if raw is None:
            continue
        summaries.append(summarize(uid, parse_message(raw)))
    return summaries


def render_summaries(summaries: list[MessageSummary], total: int) -> str:
    """Return a printable listing for `summaries` out of `total` matches."""
    if not summaries:
        return "No messages matched."
    blocks: list[str] = [summary.render() for summary in summaries]
    return f"{total} match(es), showing {len(summaries)} newest:\n\n" + "\n\n".join(blocks)


class ListEmails(Tool):
    """List the newest messages in a folder."""

    @property
    def name(self) -> str:
        return "list_emails"

    @property
    def description(self) -> str:
        return "List the newest messages in a folder, newest first."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to list, for example INBOX."},
                "limit": {"type": "integer", "description": "How many messages to return.", "minimum": 1},
            },
            "required": ["folder", "limit"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        limit: int = int(arguments["limit"])
        with self.open_session() as session:
            selected_count: int = session.select(folder, readonly=True)
            uids: list[int] = session.search(["ALL"])
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        rendered: str = render_summaries(summaries, len(uids))
        return f"Folder {folder!r} holds {selected_count} message(s).\n\n{rendered}"


class SearchEmails(Tool):
    """Search a folder by sender, subject, body text or a raw Gmail query."""

    @property
    def name(self) -> str:
        return "search_emails"

    @property
    def description(self) -> str:
        return (
            "Search a folder by sender, subject, body text, or a raw Gmail query. "
            "At least one search field must be supplied."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to search, for example INBOX."},
                "limit": {"type": "integer", "description": "How many messages to return.", "minimum": 1},
                "sender": {"type": "string", "description": "Substring of the From header."},
                "subject": {"type": "string", "description": "Substring of the Subject header."},
                "body": {"type": "string", "description": "Substring of the message body."},
                "since": {"type": "string", "description": "Only messages on or after this date, as DD-Mon-YYYY."},
                "gmail_query": {
                    "type": "string",
                    "description": "Raw Gmail search syntax. Only valid on Gmail servers, and ignored elsewhere.",
                },
            },
            "required": ["folder", "limit"],
        }

    def build_criteria(self, arguments: dict[str, Any], gmail_capable: bool) -> list[str]:
        """Translate tool arguments into IMAP SEARCH tokens."""
        gmail_query: str | None = arguments.get("gmail_query")
        if gmail_query and gmail_capable:
            return ["X-GM-RAW", quote_criterion(gmail_query)]

        criteria: list[str] = []
        for key, keyword in (("sender", "FROM"), ("subject", "SUBJECT"), ("body", "BODY")):
            value: str | None = arguments.get(key)
            if value:
                criteria.extend([keyword, quote_criterion(value)])
        since: str | None = arguments.get("since")
        if since:
            criteria.extend(["SINCE", since])
        if not criteria:
            raise ValueError("supply at least one of sender, subject, body, since or gmail_query")
        return criteria

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        limit: int = int(arguments["limit"])
        with self.open_session() as session:
            gmail_capable: bool = session.supports_gmail_search()
            criteria: list[str] = self.build_criteria(arguments, gmail_capable)
            session.select(folder, readonly=True)
            uids: list[int] = session.search(criteria)
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        note: str = ""
        if arguments.get("gmail_query") and not gmail_capable:
            note = "Note: this server is not Gmail, so gmail_query was ignored.\n\n"
        return note + render_summaries(summaries, len(uids))


class GetEmail(Tool):
    """Read one message in full without marking it as seen."""

    @property
    def name(self) -> str:
        return "get_email"

    @property
    def description(self) -> str:
        return "Read one message in full by UID. Does not mark it as read."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder holding the message."},
                "uid": {"type": "integer", "description": "UID of the message, as shown in listings."},
            },
            "required": ["folder", "uid"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        uid: int = int(arguments["uid"])
        with self.open_session() as session:
            session.select(folder, readonly=True)
            raw: bytes | None = session.fetch(uid, _FULL_PART)
        if raw is None:
            return f"No message with uid {uid} in folder {folder!r}."

        message: Message = parse_message(raw)
        body: str = extract_body(message)
        truncated: str = body[:_BODY_CHARACTER_LIMIT]
        sections: list[str] = [header_block(message)]
        attachments: list[str] = attachment_names(message)
        if attachments:
            sections.append("Attachments: " + ", ".join(attachments))
        sections.append("-" * 60)
        sections.append(truncated if truncated else "(no readable body)")
        if len(body) > _BODY_CHARACTER_LIMIT:
            sections.append(f"... truncated at {_BODY_CHARACTER_LIMIT} characters.")
        return "\n".join(sections)


class DeleteEmail(Tool):
    """Permanently delete one message."""

    @property
    def name(self) -> str:
        return "delete_email"

    @property
    def description(self) -> str:
        return "Permanently delete one message by UID. This cannot be undone."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder holding the message."},
                "uid": {"type": "integer", "description": "UID of the message to delete."},
            },
            "required": ["folder", "uid"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        uid: int = int(arguments["uid"])
        with self.open_session() as session:
            session.select(folder, readonly=False)
            session.mark_deleted(uid)
        return f"Deleted uid {uid} from folder {folder!r}."
