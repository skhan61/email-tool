"""Draft tools: create, list, read and replace drafts."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Final

from message_compose import COMPOSE_PROPERTIES, compose
from message_render import MessageSummary
from tools.base import Tool
from tools.messages import GetEmail, newest_summaries, render_summaries

_DRAFT_FLAGS: Final[str] = r"(\Draft)"

_FOLDER_PROPERTY: Final[dict[str, str]] = {
    "type": "string",
    "description": "Drafts folder, for example '[Gmail]/Drafts' or 'INBOX.Drafts'.",
}


class CreateDraft(Tool):
    """Store a new draft in the drafts folder."""

    @property
    def name(self) -> str:
        return "create_draft"

    @property
    def description(self) -> str:
        return "Save a new draft message into the drafts folder. Does not send it."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"folder": _FOLDER_PROPERTY, **COMPOSE_PROPERTIES},
            "required": ["folder", "to"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        message: EmailMessage = compose(self._config.imap_user, arguments)
        with self.open_session() as session:
            session.append(folder, _DRAFT_FLAGS, message.as_bytes())
        return f"Draft saved to {folder!r} for {arguments['to']}."


class ListDrafts(Tool):
    """List the newest drafts."""

    @property
    def name(self) -> str:
        return "list_drafts"

    @property
    def description(self) -> str:
        return "List the newest drafts, newest first."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": _FOLDER_PROPERTY,
                "limit": {"type": "integer", "description": "How many drafts to return.", "minimum": 1},
            },
            "required": ["folder", "limit"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        limit: int = int(arguments["limit"])
        with self.open_session() as session:
            session.select(folder, readonly=True)
            uids: list[int] = session.search(["ALL"])
            summaries: list[MessageSummary] = newest_summaries(session, uids, limit)
        return render_summaries(summaries, len(uids))


class GetDraft(GetEmail):
    """Read one draft in full."""

    @property
    def name(self) -> str:
        return "get_draft"

    @property
    def description(self) -> str:
        return "Read one draft in full by UID."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": _FOLDER_PROPERTY,
                "uid": {"type": "integer", "description": "UID of the draft, as shown in list_drafts."},
            },
            "required": ["folder", "uid"],
        }


class UpdateDraft(Tool):
    """Replace an existing draft with new content.

    IMAP has no in-place edit, so this appends the replacement first and only
    deletes the original once the replacement is stored.
    """

    @property
    def name(self) -> str:
        return "update_draft"

    @property
    def description(self) -> str:
        return "Replace an existing draft with new content, keyed by UID."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder": _FOLDER_PROPERTY,
                "uid": {"type": "integer", "description": "UID of the draft to replace."},
                **COMPOSE_PROPERTIES,
            },
            "required": ["folder", "uid", "to"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        folder: str = arguments["folder"]
        uid: int = int(arguments["uid"])
        message: EmailMessage = compose(self._config.imap_user, arguments)
        with self.open_session() as session:
            session.select(folder, readonly=False)
            session.append(folder, _DRAFT_FLAGS, message.as_bytes())
            session.mark_deleted(uid)
        return f"Draft uid {uid} in {folder!r} replaced."
