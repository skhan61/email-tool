"""Ask the human, through their app, before an irreversible action (NIST SP 800-171 3.1.2).

Standard: the MCP SDK's resolver injection (`Annotated[..., Resolve(fn)]`) returning an
`Elicit` request. The SDK carries the question in the client's own UI, outside the
model's control, on both protocol generations (a request mid-call on older ones, an
input-required round trip on 2026-07-28+).
Placement: approval.py; server.py attaches `approval_resolver` to every destructive tool.

The prompt shows what the model cannot alter on the way: tool, mailbox, recipients,
subject and the start of the body. Nothing here is logged.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from mcp.server.mcpserver import Context, Elicit, ElicitationResult
from mcp_types import ClientCapabilities
from pydantic import BaseModel, Field

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.policy import PolicyRefusal

_PREVIEW_CHARACTERS: Final[int] = 600
_SHOWN_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("to", "To"),
    ("cc", "Cc"),
    ("subject", "Subject"),
    ("folder", "Folder"),
    ("uid", "Message UID"),
)
# Tool arguments the question may read; a resolver takes only those its tool has.
_QUESTION_ARGUMENTS: Final[tuple[str, ...]] = ("mailbox", "to", "cc", "subject", "body", "folder", "uid")


class Approval(BaseModel):
    """The single question the human answers."""

    approve: bool = Field(description="Allow this action?")


@dataclass(frozen=True)
class NotAsked:
    """Why the human was not asked: approval not required here, or the app cannot ask."""

    required: bool


def describe(tool: str, mailbox: str, arguments: Mapping[str, Any]) -> str:
    """The text the human reads before approving."""
    lines: list[str] = [f"The assistant wants to run {tool} on mailbox {mailbox!r}."]
    for key, label in _SHOWN_FIELDS:
        value: Any = arguments.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    body: str = str(arguments.get("body", ""))
    if body:
        preview: str = body[:_PREVIEW_CHARACTERS]
        more: str = " [...]" if len(body) > _PREVIEW_CHARACTERS else ""
        lines.append(f"Body:\n{preview}{more}")
    return "\n".join(lines)


def approval_resolver(tool: str, tool_arguments: set[str], book: MailboxBook) -> Callable[..., Any]:
    """Build the resolver that decides whether, and how, to ask before `tool` runs."""
    names: list[str] = [name for name in _QUESTION_ARGUMENTS if name in tool_arguments]

    def question(ctx: Context, **arguments: Any) -> Elicit[Approval] | NotAsked:
        mailbox: str = book.label(str(arguments.get("mailbox", "")))
        if not book.policy.rules_for(mailbox).require_approval:
            return NotAsked(required=False)
        capabilities: ClientCapabilities | None = ctx.client_capabilities
        if capabilities is None or capabilities.elicitation is None:
            return NotAsked(required=True)
        return Elicit(describe(tool, mailbox, arguments), Approval)

    # The SDK binds resolver parameters by name to the tool's own arguments.
    parameters: list[inspect.Parameter] = [
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context),
        *(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Any) for name in names),
    ]
    question.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    question.__annotations__ = {
        "ctx": Context,
        **dict.fromkeys(names, Any),
        "return": Elicit[Approval] | NotAsked,
    }
    question.__name__ = question.__qualname__ = f"approve_{tool}"
    return question


def enforce(tool: str, outcome: ElicitationResult[Any]) -> bool:
    """Raise PolicyRefusal unless the action may go ahead; return True when a human approved it."""
    if outcome.action != "accept":
        raise PolicyRefusal(f"policy: the user did not approve {tool}; nothing was done")
    answer: Any = outcome.data
    if isinstance(answer, NotAsked):
        if answer.required:
            raise PolicyRefusal(f"policy: {tool} needs the user's approval and this app cannot ask; nothing was done")
        return False
    if not isinstance(answer, Approval) or not answer.approve:
        raise PolicyRefusal(f"policy: the user did not approve {tool}; nothing was done")
    return True
