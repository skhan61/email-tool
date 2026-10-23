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
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Final

import anyio
from mcp.server.mcpserver import Context, ElicitationResult, MCPServer, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp_types import ClientCapabilities, ElicitRequestURLParams, ToolAnnotations

from email_tool_mcp.approval import Approval, ConfirmationCodes, approval_resolver, enforce
from email_tool_mcp.attachments import Attachment, load
from email_tool_mcp.audit import AuditError, AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.providers import google_tokens, microsoft_tokens
from email_tool_mcp.settings import Mailbox
from email_tool_mcp.setup_page import SetupPage
from email_tool_mcp.tools.drafts import DraftTools
from email_tool_mcp.tools.reading import ReadingTools
from email_tool_mcp.tools.sending import SendingTools
from email_tool_mcp.tools.setup import SetupTools

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


@dataclass(frozen=True)
class ToolKind:
    """How one tool is registered and guarded, stated where the tool is listed."""

    hints: ToolAnnotations
    # Policy's read_only refuses tools that change mail.
    changes_mail: bool
    # The tool has an approval step that may ask the user before it runs.
    asks: bool


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
    kind: ToolKind,
    known_tools: frozenset[str],
    audit: AuditLog,
    book: MailboxBook,
    codes: ConfirmationCodes,
) -> Callable[..., Awaitable[str]]:
    """Wrap `tool`: audit before and after, enforce policy and approval, surface failures as ToolError.

    Destructive tools gain an `approval` parameter the SDK fills by running the approval
    resolver; it never appears in the schema. Everything that blocks (audit lock, keyring,
    policy files, IMAP/SMTP) runs in a worker thread, so a slow lock or keyring prompt
    never stalls the server's event loop.
    """
    name: str = tool.__name__
    changes_mail: bool = kind.changes_mail
    asks: bool = kind.asks
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
            if asks:
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
    if asks:
        question: Callable[..., Any] = approval_resolver(
            name, set(signature.parameters), known_tools, book, changes_mail, codes
        )
        resolved: Any = Annotated[ElicitationResult[Approval], Resolve(question)]
        parameters.append(inspect.Parameter("approval", inspect.Parameter.KEYWORD_ONLY, annotation=resolved))
        annotations["approval"] = resolved
    # The SDK reads parameters from the signature and resolver markers from the type hints.
    run.__signature__ = signature.replace(parameters=parameters)  # type: ignore[attr-defined]
    run.__annotations__ = annotations
    return run


def can_open_pages(capabilities: ClientCapabilities | None) -> bool:
    """True when the app can open a web page for the user (URL-mode elicitation)."""
    elicitation: Any = capabilities.elicitation if capabilities is not None else None
    return elicitation is not None and elicitation.url is not None


def opening_page(run: Callable[..., Awaitable[str]], page: SetupPage) -> Callable[..., Awaitable[str]]:
    """`add_mailbox` as the app sees it: the audited tool starts the page, then the app opens it.

    An app that can open pages gets MCP's "URL elicitation required" error naming the page,
    so the address, which carries the page's token, never reaches the assistant. Asked again
    after the user added a mailbox there, the tool reports what was added. Any other app's
    assistant gets the address to show as a link.
    """

    async def add_mailbox(ctx: Context) -> str:
        added: str = page.take_result()
        if added:
            return added + " Call list_mailboxes to see every mailbox, or add_mailbox again to add another."
        address: str = await run()
        if can_open_pages(ctx.client_capabilities):
            raise UrlElicitationRequiredError(
                [
                    ElicitRequestURLParams(
                        message=(
                            "Add a mailbox on this page. It runs on your computer only and closes after one "
                            "mailbox or 10 minutes."
                        ),
                        url=address,
                        elicitation_id=page.elicitation_id,
                    )
                ]
            )
        return (
            f"Show the user this link and ask them to open it in their browser: {address}\n"
            "It runs on their computer only and closes after one mailbox or 10 minutes. When they say they are "
            "done, call add_mailbox again to see what was added. Never ask for a password in the chat."
        )

    add_mailbox.__doc__ = run.__doc__
    return add_mailbox


def build_server(book: MailboxBook, audit: AuditLog, page: SetupPage | None = None) -> MCPServer:
    """Return a server exposing every mail tool over the mailboxes in `book`, audited to `audit`.

    `page` is the setup page `add_mailbox` opens; by default one over `book`'s settings file.
    """
    reading: ReadingTools = ReadingTools(book)
    drafts: DraftTools = DraftTools(book)
    sending: SendingTools = SendingTools(book)
    setup_page: SetupPage = page or SetupPage(book.settings_file, book.forget, microsoft_tokens, google_tokens)
    setup: SetupTools = SetupTools(setup_page)
    reads: ToolKind = ToolKind(_READ_ONLY, changes_mail=False, asks=False)
    tools: list[tuple[Callable[..., str], ToolKind]] = [
        (reading.list_mailboxes, reads),
        (reading.list_folders, reads),
        (reading.list_emails, reads),
        (reading.search_emails, reads),
        (reading.get_email, reads),
        # Changes no mail, but asks before saving into a place where a file can run.
        (reading.save_attachment, ToolKind(_SAVES, changes_mail=False, asks=True)),
        (reading.delete_email, ToolKind(_DESTRUCTIVE, changes_mail=True, asks=True)),
        (drafts.create_draft, ToolKind(_WRITES, changes_mail=True, asks=False)),
        (drafts.list_drafts, reads),
        (drafts.get_draft, reads),
        (drafts.update_draft, ToolKind(_DESTRUCTIVE, changes_mail=True, asks=True)),
        (sending.send_email, ToolKind(_SENDS, changes_mail=True, asks=True)),
        # Changes no mail; the user adds the mailbox on the page, where policy's FIPS rule applies.
        (setup.add_mailbox, ToolKind(_WRITES, changes_mail=False, asks=False)),
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
    # One set of confirmation codes per server, shared by every tool that asks.
    codes: ConfirmationCodes = ConfirmationCodes()
    tool: Callable[..., str]
    kind: ToolKind
    for tool, kind in tools:
        audited: Callable[..., Awaitable[str]] = reported(tool, kind, known_tools, audit, book, codes)
        server.add_tool(
            opening_page(audited, setup_page) if tool.__name__ == "add_mailbox" else audited,
            name=tool.__name__,
            annotations=kind.hints,
            structured_output=False,
        )
    return server
