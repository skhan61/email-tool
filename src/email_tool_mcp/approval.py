"""Ask the human, through their app, before an irreversible action (NIST SP 800-171 3.1.2).

Standard: the MCP SDK's resolver injection (`Annotated[..., Resolve(fn)]`) returning an
`Elicit` request. The SDK carries the question in the client's own UI, outside the
model's control, on both protocol generations.
Placement: approval.py; server.py attaches `approval_resolver` to every destructive tool.

The human sees exactly what would run, and only after every other check passed:
policy and recipient checks first, then the question. Shown in full: the delivered
recipient list (parsed, as SMTP receives it), the subject, every text part of the
message (plain and HTML), and for a delete or a draft replacement the message it
removes. Nothing here is logged.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage, Message
from typing import Any, Final

from mcp.server.mcpserver import Context, Elicit, ElicitationResult
from mcp_types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, Field

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.message_render import MessageSummary, every_text, read_headers, summarize
from email_tool_mcp.policy import PolicyRefusal
from email_tool_mcp.settings import Mailbox

# Tool arguments the question may read; a resolver takes only those its tool has.
_QUESTION_ARGUMENTS: Final[tuple[str, ...]] = (
    "mailbox",
    "to",
    "cc",
    "subject",
    "body",
    "html",
    "folder",
    "uid",
    "in_reply_to_uid",
    "in_reply_to_folder",
)


class Approval(BaseModel):
    """The single question the human answers."""

    approve: bool = Field(description="Allow this action?")


@dataclass(frozen=True)
class Decision:
    """The resolver's outcome when it did not ask: not needed, impossible, or refused outright."""

    required: bool
    refusal: str = ""


def can_ask(capabilities: ClientCapabilities | None) -> bool:
    """The SDK's own rule: form elicitation, or a bare `elicitation: {}` from before modes existed."""
    elicitation: ElicitationCapability | None = capabilities.elicitation if capabilities is not None else None
    return elicitation is not None and (elicitation.form is not None or elicitation.url is None)


def target_summary(book: MailboxBook, mailbox: Mailbox, folder: str, uid: int) -> MessageSummary:
    """The headers of the message a delete or replacement would remove; LookupError if absent."""
    with book.imap(mailbox) as session:
        return summarize(uid, read_headers(session, folder, uid))


def describe(tool: str, book: MailboxBook, mailbox: Mailbox, arguments: Mapping[str, Any]) -> str:
    """The full text the human reads; runs the recipient check first, so a refused send is never shown."""
    lines: list[str] = [f"The assistant wants to run {tool} on mailbox {mailbox.name!r} ({mailbox.address})."]
    if "uid" in arguments:
        removed: MessageSummary = target_summary(book, mailbox, str(arguments["folder"]), int(arguments["uid"]))
        verb: str = "permanently delete" if tool == "delete_email" else "replace"
        lines += [f"It will {verb} this message in {arguments['folder']!r}:", removed.render()]
    if "to" in arguments:
        parent_uid: int = int(arguments.get("in_reply_to_uid", 0))
        parent: Message | None = None
        if parent_uid:
            with book.imap(mailbox) as session:
                parent = read_headers(session, str(arguments.get("in_reply_to_folder", "INBOX")), parent_uid)
        message: EmailMessage = compose(
            mailbox.address,
            str(arguments.get("to", "")),
            str(arguments.get("subject", "")),
            str(arguments.get("body", "")),
            str(arguments.get("cc", "")),
            str(arguments.get("html", "")),
            parent,
        )
        recipients: list[str] = book.approve(mailbox, message)
        if parent is not None:
            lines += ["In reply to:", summarize(parent_uid, parent).render()]
        lines += [
            f"Delivered to: {', '.join(recipients)}",
            f"Subject: {message.get('Subject', '')}",
            "Full text (every part, as the recipient's mail program shows it):",
            every_text(message),
        ]
    return "\n".join(lines)


def approval_resolver(
    tool: str, tool_arguments: set[str], known_tools: frozenset[str], book: MailboxBook
) -> Callable[..., Any]:
    """Build the resolver that checks policy, then decides whether and how to ask before `tool` runs."""
    names: list[str] = [name for name in _QUESTION_ARGUMENTS if name in tool_arguments]

    def question(ctx: Context, **arguments: Any) -> Elicit[Approval] | Decision:
        try:
            mailbox: Mailbox = book.resolve(str(arguments.get("mailbox", "")))
            book.policy.check_call(
                mailbox.name, mailbox.address, tool, True, known_tools, keeps_sign_in=mailbox.keeps_sign_in
            )
            if not book.policy.rules_for(mailbox.name, mailbox.address).require_approval:
                return Decision(required=False)
            if not can_ask(ctx.client_capabilities):
                return Decision(required=True)
            return Elicit(describe(tool, book, mailbox, arguments), Approval)
        except Exception as error:
            # Reported by the audited wrapper, never as a bare SDK error.
            return Decision(required=True, refusal=f"{type(error).__name__}: {error}")

    # The SDK binds resolver parameters by name to the tool's own arguments.
    parameters: list[inspect.Parameter] = [
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context),
        *(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Any) for name in names),
    ]
    question.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    question.__annotations__ = {"ctx": Context, **dict.fromkeys(names, Any), "return": Elicit[Approval] | Decision}
    question.__name__ = question.__qualname__ = f"approve_{tool}"
    return question


def enforce(tool: str, outcome: ElicitationResult[Any] | None) -> bool:
    """Raise PolicyRefusal unless the action may go ahead; return True when a human approved it.

    Fails closed: a destructive call whose approval step did not run is refused.
    """
    if outcome is None:
        raise PolicyRefusal(f"policy: the approval step for {tool} did not run; nothing was done")
    if outcome.action != "accept":
        raise PolicyRefusal(f"policy: the user did not approve {tool}; nothing was done")
    answer: Any = outcome.data
    if isinstance(answer, Decision):
        if answer.refusal:
            raise PolicyRefusal(answer.refusal)
        if answer.required:
            raise PolicyRefusal(f"policy: {tool} needs the user's approval and this app cannot ask; nothing was done")
        return False
    if not isinstance(answer, Approval) or not answer.approve:
        raise PolicyRefusal(f"policy: the user did not approve {tool}; nothing was done")
    return True
