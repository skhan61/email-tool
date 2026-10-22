"""Build the MCP server: every tool, its safety hints, and readable errors.

Standard: the official MCP Python SDK's MCPServer over stdio.
Placement: server.py in the src layout, beside the tool modules it registers.

mcp 2.x hides the text of any exception that is not a ToolError. Every failure
here is one the user can act on (no password, locked keyring, bad settings,
login refused), so each is re-raised as a ToolError with its message intact.

Every call is audit-logged (audit.py): a "started" record before the mailbox is
touched, refused if it cannot be written, and a "finished" record after. Between
the two, the call is checked against the administrator's and user's policy
(policy.py); a refusal is recorded like any other outcome.
"""

from __future__ import annotations

import functools
import inspect
import typing
from collections.abc import Awaitable, Callable
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Final

import anyio
from mcp.server.mcpserver import ElicitationResult, MCPServer, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from email_tool_mcp.approval import Approval, approval_resolver, enforce
from email_tool_mcp.attachments import Attachment, load
from email_tool_mcp.audit import AuditError, AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.tools.drafts import DraftTools
from email_tool_mcp.tools.reading import ReadingTools
from email_tool_mcp.tools.sending import SendingTools

DISTRIBUTION: Final[str] = "email-tool-mcp"

_READ_ONLY: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITES: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE: Final[ToolAnnotations] = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
# Writes a file on this computer and changes no mail, so a read-only mailbox allows it.
_SAVES: Final[ToolAnnotations] = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
_SENDS: Final[ToolAnnotations] = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)


def broken_text_arguments(kwargs: dict[str, Any]) -> list[str]:
    """The text arguments that are not valid Unicode (JSON can carry a lone surrogate such as \\ud800)."""
    broken: list[str] = []
    key: str
    value: Any
    for key, value in kwargs.items():
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                broken.append(key)
    return broken


def attachment_record(paths: object) -> object:
    """What the audit log keeps of attachments: name, size and SHA-256 of each, never the contents."""
    if not isinstance(paths, list):
        return paths
    try:
        files: list[Attachment] = load([str(path) for path in paths])
    except (OSError, ValueError):
        # The tool refuses these; the log keeps the names it was given.
        return [Path(str(path)).name for path in paths]
    return [{"name": file.name, "size": file.size, "sha256": file.sha256} for file in files]


def escaped(value: object) -> object:
    """`value` safe to write as UTF-8: broken characters shown as `\\udXXX` escapes."""
    return value.encode("utf-8", "backslashreplace").decode("utf-8") if isinstance(value, str) else value


def reported(
    tool: Callable[..., str],
    hints: ToolAnnotations,
    known_tools: frozenset[str],
    audit: AuditLog,
    book: MailboxBook,
) -> Callable[..., Awaitable[str]]:
    """Wrap `tool`: audit before and after, enforce policy and approval, surface failures as ToolError.

    Destructive tools gain an `approval` parameter the SDK fills by running the approval
    resolver; it never appears in the schema. Everything that blocks (audit lock, keyring,
    policy files, IMAP/SMTP) runs in a worker thread, so a slow lock or keyring prompt
    never stalls the server's event loop.
    """
    name: str = tool.__name__
    changes_mail: bool = not hints.read_only_hint and hints is not _SAVES
    destructive: bool = bool(hints.destructive_hint)
    signature: inspect.Signature = inspect.signature(tool, eval_str=True)
    takes_mailbox: bool = "mailbox" in signature.parameters

    def execute(args: tuple[Any, ...], kwargs: dict[str, Any], approval: ElicitationResult[Any] | None) -> str:
        broken: list[str] = broken_text_arguments(kwargs)
        # Logged escaped: the audit log is UTF-8, which an unpaired surrogate is not.
        logged: dict[str, object] = {key: escaped(value) if key in broken else value for key, value in kwargs.items()}
        if logged.get("attachments") and "attachments" not in broken:
            logged["attachments"] = attachment_record(logged["attachments"])
        given: str = str(logged.get("mailbox", ""))
        target: Mailbox | None = None
        unresolved: Exception | None = None
        if takes_mailbox:
            try:
                target = book.resolve(given)
            except Exception as error:
                unresolved = error
        mailbox: str = target.name if target is not None else given
        try:
            call: str = audit.started(mailbox, name, logged)
        except AuditError as error:
            raise ToolError(f"Refused, nothing was done: {error}") from error
        approved: bool = False
        try:
            if broken:
                raise ValueError(
                    f"{', '.join(broken)} contains invalid text (a broken Unicode character); nothing was done"
                )
            if unresolved is not None:
                # Never check policy without the address: a mailbox that cannot be resolved does not run.
                raise unresolved
            book.policy.check_call(
                mailbox,
                target.address if target is not None else "",
                name,
                changes_mail,
                known_tools,
                keeps_sign_in=target is not None and target.keeps_sign_in,
            )
            if destructive:
                approved = enforce(name, approval)
            result: str = tool(*args, **kwargs)
        except Exception as error:
            message: str = f"{type(error).__name__}: {error}"
            try:
                audit.finished(call, mailbox, name, message)
            except AuditError as audit_error:
                message += f" (the outcome could not be recorded: {audit_error})"
            raise ToolError(message) from error
        try:
            audit.finished(call, mailbox, name, "ok (approved by the user)" if approved else "ok")
        except AuditError as error:
            raise ToolError(f"Done, but the outcome could not be recorded ({error}). Do not repeat it.") from error
        return result

    @functools.wraps(tool)
    async def run(*args: Any, approval: ElicitationResult[Any] | None = None, **kwargs: Any) -> str:
        outcome: str = await anyio.to_thread.run_sync(functools.partial(execute, args, kwargs, approval))
        return outcome

    parameters: list[inspect.Parameter] = list(signature.parameters.values())
    annotations: dict[str, Any] = typing.get_type_hints(tool, include_extras=True)
    if destructive:
        question: Callable[..., Any] = approval_resolver(name, set(signature.parameters), known_tools, book)
        resolved: Any = Annotated[ElicitationResult[Approval], Resolve(question)]
        parameters.append(inspect.Parameter("approval", inspect.Parameter.KEYWORD_ONLY, annotation=resolved))
        annotations["approval"] = resolved
    # The SDK reads parameters from the signature and resolver markers from the type hints.
    run.__signature__ = signature.replace(parameters=parameters)  # type: ignore[attr-defined]
    run.__annotations__ = annotations
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
        (reading.save_attachment, _SAVES),
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
    known_tools: frozenset[str] = frozenset(tool.__name__ for tool, _ in tools)
    for tool, hints in tools:
        server.add_tool(
            reported(tool, hints, known_tools, audit, book),
            name=tool.__name__,
            annotations=hints,
            structured_output=False,
        )
    return server
