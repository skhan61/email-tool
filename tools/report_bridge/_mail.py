"""The problem reports in one mailbox folder, read without marking, moving or deleting anything.

Standard: email-tool's own ImapSession (a read-only select, a SUBJECT search, BODY.PEEK fetches) and
message_render's parsing, the same code the read tools use.
Placement: tools/report_bridge/_mail.py, the mail half of the report bridge.

An IMAP SUBJECT search is a case-insensitive substring match, so it only narrows the folder; a
report is a message whose decoded subject STARTS with `SUBJECT_PREFIX`, exactly as `report_problem`
writes it (#93). A reply ("Re: ...") is not a report.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Final

from email_tool_mcp.imap_session import ImapSession, text
from email_tool_mcp.message_render import decode_header_value, extract_body, parse_message
from email_tool_mcp.problem_report import SUBJECT_PREFIX

REMOVED: Final[str] = "[address removed]"

# A word: a run up to a space or a bracket that wraps addresses, or a quoted local part with its
# domain (`"john doe"@host`). Every word holding an @ after its first character is an address: wider
# than RFC 5322's addr-spec on purpose, since an over-removed word costs nothing and a leaked address
# does. Words, not an `x@y` pattern: that one backtracks over every start of a long run with no @,
# which is quadratic in a report's length.
_WORD: Final[re.Pattern[str]] = re.compile(r'"[^"\n]*"@[^\s<>(),;]*|[^\s<>(),;]+')


def _removed(word: re.Match[str]) -> str:
    return REMOVED if "@" in word.group().lstrip("@") else word.group()


def redact(value: str) -> str:
    """`value` with every email address replaced by `REMOVED`; a lone `@name` stays."""
    return _WORD.sub(_removed, value)


@dataclass(frozen=True)
class Report:
    """One emailed report, already free of addresses."""

    key: str
    """A hash of the Message-ID (of subject, date and text when it has none): stable, not the sender's domain."""
    title: str
    date: str
    """The day it was sent, `YYYY-MM-DD`, or "" when the Date header does not parse."""
    text: str


def _header(message: Message, name: str) -> str:
    """A header as text; the raw value when its encoded words do not decode (a bogus charset)."""
    raw: object = message.get(name)
    try:
        return decode_header_value(None if raw is None else str(raw))
    except (LookupError, UnicodeError, ValueError):
        return "" if raw is None else str(raw)


def _date(message: Message) -> str:
    """Only the parsed day: the header itself is the sender's text and may carry anything."""
    try:
        return parsedate_to_datetime(str(message.get("Date", ""))).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def _report(message: Message) -> Report:
    subject: str = _header(message, "Subject")
    title: str = " ".join(redact(subject.removeprefix(SUBJECT_PREFIX)).split())
    body: str = extract_body(message)
    message_id: str = _header(message, "Message-ID").strip()
    identity: str = message_id or "\n".join((subject, _header(message, "Date"), body))
    return Report(
        key=hashlib.sha256(identity.encode()).hexdigest(),
        title=title or "(no description)",
        date=_date(message),
        text=redact(body),
    )


def find_reports(session: ImapSession, folder: str) -> list[Report]:
    """Every report in `folder`, oldest first. Selects read-only and peeks, so nothing is marked read."""
    session.select(folder, readonly=True)
    candidates: list[int] = sorted(session.search(["SUBJECT", text(SUBJECT_PREFIX)]))
    headers: dict[int, bytes] = session.fetch_headers(candidates)
    reports: list[Report] = []
    for uid in candidates:
        if not _header(parse_message(headers.get(uid, b"")), "Subject").startswith(SUBJECT_PREFIX):
            continue
        raw: bytes | None = session.fetch_message(uid)
        if raw is not None:
            reports.append(_report(parse_message(raw)))
    return reports
