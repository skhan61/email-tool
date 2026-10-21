"""Build the MCP server: every tool, its safety hints, and readable errors.

Standard: the official MCP Python SDK's MCPServer over stdio.
Placement: server.py in the src layout, beside the tool modules it registers.

mcp 2.x hides the text of any exception that is not a ToolError. Every failure
here is one the user can act on (no password, locked keyring, bad settings,
login refused), so each is re-raised as a ToolError with its message intact.

Every call is audit-logged (audit.py). If the log cannot be written the call is
refused before it touches the mailbox: no action without a record.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from importlib.metadata import version
from typing import Any, Final, ParamSpec

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.tools.drafts import DraftTools
from email_tool_mcp.tools.reading import ReadingTools
from email_tool_mcp.tools.sending import SendingTools

DISTRIBUTION: Final[str] = "email-tool-mcp"

_READ_ONLY: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITES: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE: Final[ToolAnnotations] = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
_SENDS: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

Params = ParamSpec("Params")


def mailbox_label(book: MailboxBook, arguments: dict[str, Any]) -> str:
    """The mailbox a call acts on, as the audit log should name it."""
    given: str = str(arguments.get("mailbox", ""))
    try:
        return book.resolve(given).name
    except Exception:
        return given


def reported(tool: Callable[Params, str], audit: AuditLog, book: MailboxBook) -> Callable[Params, str]:
    """Wrap `tool`: refuse without a writable audit log, record the outcome, surface errors as ToolError."""

    @functools.wraps(tool)
    def run(*args: Params.args, **kwargs: Params.kwargs) -> str:
        name: str = tool.__name__
        mailbox: str = mailbox_label(book, kwargs)
        try:
            audit.ensure_writable()
        except OSError as error:
            raise ToolError(f"Refused: the audit log {audit.path} cannot be written ({error}).") from error
        try:
            result: str = tool(*args, **kwargs)
        except Exception as error:
            audit.record(mailbox, name, kwargs, f"{type(error).__name__}: {error}")
            raise ToolError(f"{type(error).__name__}: {error}") from error
        audit.record(mailbox, name, kwargs, "ok")
        return result

    return run


def build_server(book: MailboxBook, audit: AuditLog) -> MCPServer:
    """Return a server exposing every mail tool over the mailboxes in `book`, audited to `audit`."""
    reading: ReadingTools = ReadingTools(book)
    drafts: DraftTools = DraftTools(book)
    sending: SendingTools = SendingTools(book)
    tools: list[tuple[Callable[..., str], ToolAnnotations]] = [
        (reading.list_mailboxes, _READ_ONLY),
        (reading.list_folders, _READ_ONLY),
        (reading.list_emails, _READ_ONLY),
        (reading.search_emails, _READ_ONLY),
        (reading.get_email, _READ_ONLY),
        (reading.delete_email, _DESTRUCTIVE),
        (drafts.create_draft, _WRITES),
        (drafts.list_drafts, _READ_ONLY),
        (drafts.get_draft, _READ_ONLY),
        (drafts.update_draft, _DESTRUCTIVE),
        (sending.send_email, _SENDS),
    ]
    server: MCPServer = MCPServer(
        name="email-tool",
        version=version(DISTRIBUTION),
        instructions=(
            "IMAP/SMTP email. Call list_mailboxes first when more than one mailbox may exist. "
            "Never send or delete without the user's explicit confirmation of the exact message."
        ),
    )
    for tool, hints in tools:
        server.add_tool(reported(tool, audit, book), name=tool.__name__, annotations=hints, structured_output=False)
    return server
