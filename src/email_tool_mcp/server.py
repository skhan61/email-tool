"""Build the MCP server: every tool, its safety hints, and readable errors.

Standard: the official MCP Python SDK's MCPServer over stdio.
Placement: server.py in the src layout, beside the tool modules it registers.

mcp 2.x hides the text of any exception that is not a ToolError, so the
failures a user can fix (no password, unknown mailbox, login refused) are
re-raised as ToolError with their message intact.
"""

from __future__ import annotations

import functools
import imaplib
import smtplib
from collections.abc import Callable
from importlib.metadata import version
from typing import Final, ParamSpec

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from email_tool_mcp.imap_session import ImapError
from email_tool_mcp.mailbox_book import MailboxBook, UnknownMailbox
from email_tool_mcp.passwords import MissingPassword
from email_tool_mcp.tools.drafts import DraftTools
from email_tool_mcp.tools.reading import ReadingTools
from email_tool_mcp.tools.sending import SendingTools

DISTRIBUTION: Final[str] = "email-tool-mcp"

_EXPECTED_FAILURES: Final[tuple[type[Exception], ...]] = (
    MissingPassword,
    UnknownMailbox,
    ImapError,
    imaplib.IMAP4.error,
    smtplib.SMTPException,
    OSError,
    ValueError,
)

_READ_ONLY: Final[ToolAnnotations] = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_WRITES: Final[ToolAnnotations] = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
_DESTRUCTIVE: Final[ToolAnnotations] = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
_SENDS: Final[ToolAnnotations] = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

Params = ParamSpec("Params")


def reported(tool: Callable[Params, str]) -> Callable[Params, str]:
    """Wrap `tool` so an expected failure reaches the model as a ToolError."""

    @functools.wraps(tool)
    def run(*args: Params.args, **kwargs: Params.kwargs) -> str:
        try:
            return tool(*args, **kwargs)
        except _EXPECTED_FAILURES as error:
            raise ToolError(f"{type(error).__name__}: {error}") from error

    return run


def build_server(book: MailboxBook) -> MCPServer:
    """Return a server exposing every mail tool over the mailboxes in `book`."""
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
        server.add_tool(reported(tool), name=tool.__name__, annotations=hints, structured_output=False)
    return server
