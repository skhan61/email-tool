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

import hashlib
import hmac
import inspect
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage, Message
from pathlib import Path
from typing import Any, Final

from mcp.server.mcpserver import Context, Elicit, ElicitationResult
from mcp_types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, Field

from email_tool_mcp.attachments import (
    Attachment,
    SensitiveFile,
    attachment_bytes,
    human_size,
    load,
    risky_save,
    safe_file_name,
    save_directory,
    sensitive,
)
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.message_render import (
    MessageSummary,
    attached_parts,
    decode_header_value,
    every_text,
    parse_message,
    read_headers,
    summarize,
)
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
    "attachments",
    "index",
    "directory",
    "confirm_sensitive",
    "in_reply_to_uid",
    "in_reply_to_folder",
)
# How long a confirmation code from a refusal stays valid.
CODE_SECONDS: Final[float] = 600.0


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
    if tool == "save_attachment":
        name: str
        size: int
        name, size = saved_attachment(book, mailbox, arguments)
        directory: Path = save_directory(str(arguments.get("directory", "")))
        lines.append(f"It will save {name} ({human_size(size)}) from message uid {arguments['uid']} into {directory}.")
        return "\n".join(lines + [f"WARNING: {reason}." for reason in risky_save(directory, name)])
    if "uid" in arguments:
        removed: MessageSummary = target_summary(book, mailbox, str(arguments["folder"]), int(arguments["uid"]))
        verb: str = "permanently delete" if tool == "delete_email" else "replace"
        lines += [f"It will {verb} this message in {arguments['folder']!r}:", removed.render()]
    if "to" in arguments:
        paths: list[str] = attachment_paths(arguments)
        files: list[Attachment] = load(paths)
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
            attachments=files,
            parent=parent,
        )
        recipients: list[str] = book.approve(mailbox, message)
        if parent is not None:
            lines += ["In reply to:", summarize(parent_uid, parent).render()]
        lines += [f"Delivered to: {', '.join(recipients)}", f"Subject: {message.get('Subject', '')}"]
        if files:
            lines.append("Attachments: " + ", ".join(attachment.label() for attachment in files))
            lines += [f"WARNING: {found.render()}." for found in sensitive(paths, files)]
        lines += ["Full text (every part, as the recipient's mail program shows it):", every_text(message)]
    return "\n".join(lines)


def attachment_paths(arguments: Mapping[str, Any]) -> list[str]:
    """The `attachments` argument as a list of paths."""
    given: object = arguments.get("attachments")
    return [str(path) for path in given] if isinstance(given, list) else []


def sensitive_sends(tool: str, arguments: Mapping[str, Any]) -> list[SensitiveFile]:
    """The attachments of a send that look sensitive; drafts are only warned about, never stopped."""
    paths: list[str] = attachment_paths(arguments)
    if tool != "send_email" or not paths:
        return []
    return sensitive(paths, load(paths))


def saved_attachment(book: MailboxBook, mailbox: Mailbox, arguments: Mapping[str, Any]) -> tuple[str, int]:
    """The name and size of the attachment a save would write; LookupError when there is none."""
    folder: str = str(arguments.get("folder", "INBOX"))
    uid: int = int(arguments["uid"])
    with book.imap(mailbox) as session:
        session.select(folder, readonly=True)
        raw: bytes | None = session.fetch_message(uid)
    if raw is None:
        raise LookupError(f"no message with uid {uid} in folder {folder!r}")
    parts: list[Message] = attached_parts(parse_message(raw))
    index: int = int(arguments["index"])
    if not 1 <= index <= len(parts):
        raise LookupError(f"message uid {uid} has no attachment {index}")
    part: Message = parts[index - 1]
    return safe_file_name(decode_header_value(part.get_filename())), len(attachment_bytes(part))


def warnings_for(tool: str, book: MailboxBook, mailbox: Mailbox, arguments: Mapping[str, Any]) -> list[str]:
    """What the user should hear before `tool` runs: sensitive attachments, or a risky place to save."""
    if tool == "save_attachment":
        name: str = saved_attachment(book, mailbox, arguments)[0]
        return risky_save(save_directory(str(arguments.get("directory", ""))), name)
    return [found.render() for found in sensitive_sends(tool, arguments)]


def fingerprint(tool: str, mailbox: Mailbox, arguments: Mapping[str, Any]) -> str:
    """What a confirmation code is bound to: these exact files and recipients, or this exact save."""
    if tool == "save_attachment":
        parts: list[str] = [
            str(arguments.get("folder", "INBOX")),
            str(arguments.get("uid")),
            str(arguments.get("index")),
            str(save_directory(str(arguments.get("directory", "")))),
        ]
    else:
        files: list[Attachment] = load(attachment_paths(arguments))
        parts = [str(arguments.get("to", "")), str(arguments.get("cc", "")), *(file.sha256 for file in files)]
    return hashlib.sha256("\x00".join([tool, mailbox.name, *parts]).encode("utf-8")).hexdigest()


class ConfirmationCodes:
    """One-time codes a refusal hands out when the app cannot ask the user.

    A code proves only that the warning was given for these exact files and recipients
    (or this save) within the last ten minutes; whether the user agreed rests on the
    assistant asking them, which is why apps that can show a question always get one.
    """

    def __init__(self) -> None:
        self._codes: dict[str, tuple[float, str]] = {}
        self._lock: threading.Lock = threading.Lock()

    def issue(self, bound_to: str) -> str:
        code: str = secrets.token_hex(4)
        now: float = time.monotonic()
        with self._lock:
            self._codes = {key: entry for key, entry in self._codes.items() if entry[0] > now}
            self._codes[code] = (now + CODE_SECONDS, bound_to)
        return code

    def redeem(self, code: str, bound_to: str) -> bool:
        """True once for a live code issued for `bound_to`; any use spends it."""
        with self._lock:
            entry: tuple[float, str] | None = self._codes.pop(code, None)
        return entry is not None and entry[0] > time.monotonic() and hmac.compare_digest(entry[1], bound_to)


def approval_resolver(
    tool: str,
    tool_arguments: set[str],
    known_tools: frozenset[str],
    book: MailboxBook,
    changes_mail: bool,
    codes: ConfirmationCodes,
) -> Callable[..., Any]:
    """Build the resolver that checks policy, then decides whether and how to ask before `tool` runs."""
    names: list[str] = [name for name in _QUESTION_ARGUMENTS if name in tool_arguments]

    def question(ctx: Context, **arguments: Any) -> Elicit[Approval] | Decision:
        try:
            mailbox: Mailbox = book.resolve(str(arguments.get("mailbox", "")))
            book.policy.check_call(
                mailbox.name, mailbox.address, tool, changes_mail, known_tools, keeps_sign_in=mailbox.keeps_sign_in
            )
            # require_approval covers what changes mail; a warning makes the app ask regardless.
            required: bool = changes_mail and book.policy.rules_for(mailbox.name, mailbox.address).require_approval
            warnings: list[str] = warnings_for(tool, book, mailbox, arguments)
            if not required and not warnings:
                return Decision(required=False)
            if can_ask(ctx.client_capabilities):
                return Elicit(describe(tool, book, mailbox, arguments), Approval)
            if required:
                return Decision(required=True)
            bound_to: str = fingerprint(tool, mailbox, arguments)
            given: str = str(arguments.get("confirm_sensitive") or "")
            if given and codes.redeem(given, bound_to):
                return Decision(required=False)
            code: str = codes.issue(bound_to)
            return Decision(
                required=True,
                refusal=(
                    "nothing was done: "
                    + "; ".join(warnings)
                    + f". Tell the user exactly this and ask whether to go ahead. Only if they agree, call {tool} "
                    f'again with the same arguments and confirm_sensitive="{code}" (one use, ten minutes)'
                ),
            )
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
