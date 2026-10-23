"""A problem report the user reads and approves: their setup and recent errors, with nothing private in it.

Standard: redaction by the usual secret-scanning patterns (PEM key blocks, AWS key IDs,
`password=`-style assignments, long tokens) and PII patterns (addresses, home-folder paths,
IP addresses, host names), the same signs attachments.py treats as sensitive. A scanner
library such as detect-secrets reads files: its one-line API flags every word as a
high-entropy candidate and misses an unquoted `password=x`, so the patterns are kept here.
The GitHub route is a new-issue link to an issue form (`template=` plus the form's field ids),
whose `labels` apply for anyone, unlike a `labels=` parameter.
Placement: problem_report.py; tools/reporting.py serves it as report_problem and
email_problem_report, and approval.py shows the exact email before it is sent.

What a report holds: the email-tool, OS and Python versions, the app's name, how many
mailboxes of each kind (Gmail, Outlook, other; never an address), and the last few failed
calls in the audit log, which itself never holds a subject or a body. All of it, the user's
own description included, passes through `redact` before anyone sees it.
"""

from __future__ import annotations

import os
import platform
import re
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final, Literal, TypeAlias
from urllib.parse import quote, urlencode

from email_tool_mcp.attachments import SENSITIVE_TEXT
from email_tool_mcp.audit import parse_record
from email_tool_mcp.google import IMAP_HOST as GOOGLE_IMAP_HOST
from email_tool_mcp.google import SMTP_HOST as GOOGLE_SMTP_HOST
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import CLOUDS, PERSONAL_SMTP_HOST
from email_tool_mcp.settings import Mailbox

# The maintainer's published contact (pyproject.toml); emailed reports go there.
REPORT_ADDRESS: Final[str] = "s.khan@alchlight.com"
# Every emailed report's subject starts with this, so reports can be found and filed as issues.
SUBJECT_PREFIX: Final[str] = "email-tool problem report:"
NEW_ISSUE_URL: Final[str] = "https://github.com/skhan61/email-tool/issues/new"
# The issue form (.github/ISSUE_TEMPLATE) and its field the link fills in.
ISSUE_TEMPLATE: Final[str] = "user-report.yml"
REPORT_FIELD: Final[str] = "report"
REPORT_START: Final[str] = "----- report -----"
REPORT_END: Final[str] = "----- end of report -----"
FAILED_CALLS: Final[int] = 5
DESCRIPTION_LIMIT: Final[int] = 2000
REPORT_LIMIT: Final[int] = 20_000
_OUTCOME_LIMIT: Final[int] = 300
# How much of one error message is read at all: bounds the redaction's work on a huge message.
_OUTCOME_READ: Final[int] = 2000
_TITLE_LIMIT: Final[int] = 70
# Enough of the audit log's end for the last few failures, however large the log grows.
_TAIL_BYTES: Final[int] = 256 * 1024
# Longer new-issue links are not reliably opened by browsers and GitHub.
_LINK_LIMIT: Final[int] = 8000
_SHORTENED: Final[str] = "\n[shortened to fit the link]"
ProviderKind: TypeAlias = Literal["Gmail", "Outlook", "other"]
_KINDS: Final[tuple[ProviderKind, ...]] = ("Gmail", "Outlook", "other")
_OUTLOOK_HOSTS: Final[frozenset[str]] = frozenset(
    host for cloud in CLOUDS.values() for host in (cloud.imap_host, cloud.smtp_host)
) | {PERSONAL_SMTP_HOST}
# Public provider hosts are kept: they help find a fault and say nothing about the user.
_PUBLIC_HOSTS: Final[frozenset[str]] = _OUTLOOK_HOSTS | {
    GOOGLE_IMAP_HOST,
    GOOGLE_SMTP_HOST,
    "gmail.com",
    "outlook.com",
    "github.com",
    *(cloud.login_host for cloud in CLOUDS.values()),
}

_KEY_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"-----BEGIN [A-Z0-9 ]*-----.*?(?:-----END [A-Z0-9 ]*-----|\Z)", re.DOTALL
)
# The attachment check's own signs of a secret, applied to text.
_ATTACHMENT_SIGNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern.pattern.decode("ascii"), pattern.flags) for pattern, _ in SENSITIVE_TEXT
)
_SECRET_VALUE: Final[str] = r"""(?:"[^"\n]*"?|'[^'\n]*'?|(?:[a-z]{4} ){3}[a-z]{4}\b|[^\s,;]+)"""
# `password=x`, `"api_key": "x"`, `client_secret: x`: the name stays, the value goes.
_ASSIGNED_SECRET: Final[re.Pattern[str]] = re.compile(
    r"""(\b\w*(?:pass(?:word|wd|phrase|code)|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key"""
    r"""|credential|authorization)\w*["']?\s*(?:[:=]|=>)\s*)""" + _SECRET_VALUE,
    re.IGNORECASE,
)
# `my password is x`, `Bearer x`, and a Gmail app password after the word password.
_SPOKEN_SECRET: Final[re.Pattern[str]] = re.compile(
    r"(\b(?:pass(?:word|wd|phrase|code)|pwd)\s+(?:is|was)\s+|\bbearer\s+)" + _SECRET_VALUE, re.IGNORECASE
)
_APP_PASSWORD: Final[re.Pattern[str]] = re.compile(r"(\bpassword\W{0,3})(?:[a-z]{4} ){3}[a-z]{4}\b", re.IGNORECASE)
_LOCAL_PART: Final[str] = r"""[^\s@<>()\[\]\\,;:"]"""
# Tried only where a run of local-part characters starts, so a long run without `@` is read once.
_ADDRESS: Final[re.Pattern[str]] = re.compile(rf"(?<!{_LOCAL_PART}){_LOCAL_PART}+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# The rest of a path: up to a space or quote, less a sentence's closing punctuation (`x.pdf: no such file`).
_PATH_REST: Final[str] = r"""[^\s"'<>|]*?(?=[.,;:)]*(?:[\s"'<>|]|$))"""
_HOME_PATH: Final[re.Pattern[str]] = re.compile(
    r"""(?:(?<![\w.~])(?:/home/|/Users/|[A-Za-z]:[\\/]Users[\\/])|(?<!\w)~[\\/])""" + _PATH_REST
)
_QUOTED: Final[re.Pattern[str]] = re.compile(
    r"""(?<!\w)b?"[^"\n]*"|(?<!\w)b?'[^'\n]*'(?!\w)|“[^”\n]*”|‘[^’\n]*’(?!\w)"""
)
_SUBJECT: Final[re.Pattern[str]] = re.compile(r"\b(subject\s*:)[^\n]*", re.IGNORECASE)
_TOKEN_CHARACTER: Final[str] = r"[A-Za-z0-9_\-+/=.~]"
_TOKEN: Final[re.Pattern[str]] = re.compile(
    rf"(?<!{_TOKEN_CHARACTER})(?={_TOKEN_CHARACTER}*[0-9])(?={_TOKEN_CHARACTER}*[A-Za-z]){_TOKEN_CHARACTER}{{20,}}"
)
_IP_ADDRESS: Final[re.Pattern[str]] = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOST: Final[re.Pattern[str]] = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}\b")
# Each removal can expose another (a quote after a removed name), so the rules repeat until
# nothing changes: the text shown is then exactly the text redacted again before sending.
_MAX_PASSES: Final[int] = 10


def home_pattern(home: Path) -> re.Pattern[str]:
    """Any path under `home`, written with either slash."""
    roots: list[str] = sorted({str(home), home.as_posix()}, key=len, reverse=True)
    return re.compile(
        "(?:" + "|".join(re.escape(root) for root in roots) + r")(?:(?=[\\/])" + _PATH_REST + ")?", re.IGNORECASE
    )


def public_or_removed(found: re.Match[str]) -> str:
    """A known provider host as it is; any other host or dotted name removed."""
    return found.group(0) if found.group(0).lower() in _PUBLIC_HOSTS else "[name]"


def redaction_pass(text: str, own_home: re.Pattern[str]) -> str:
    """One pass of every rule, most specific first."""
    text = _KEY_BLOCK.sub("[private key]", text)
    text = _ASSIGNED_SECRET.sub(r"\1[secret]", text)
    text = _SPOKEN_SECRET.sub(r"\1[secret]", text)
    text = _APP_PASSWORD.sub(r"\1[secret]", text)
    sign: re.Pattern[str]
    for sign in _ATTACHMENT_SIGNS:
        text = sign.sub("[secret]", text)
    text = _ADDRESS.sub("[address]", text)
    text = own_home.sub("[home folder path]", text)
    text = _HOME_PATH.sub("[home folder path]", text)
    text = _QUOTED.sub("[quoted text]", text)
    text = _SUBJECT.sub(r"\1 [removed]", text)
    text = _TOKEN.sub("[secret]", text)
    text = _IP_ADDRESS.sub("[IP address]", text)
    return _HOST.sub(public_or_removed, text)


def redact(text: str, home: Path | None = None) -> str:
    """`text` without addresses, subjects or quoted text, home-folder paths, keys, tokens or passwords."""
    own_home: re.Pattern[str] = home_pattern(home if home is not None else Path.home())
    for _ in range(_MAX_PASSES):
        cleaner: str = redaction_pass(text, own_home)
        if cleaner == text:
            return text
        text = cleaner
    raise ValueError(f"the report could not be cleaned in {_MAX_PASSES} passes; nothing was shown or sent")


def provider_kind(mailbox: Mailbox) -> ProviderKind:
    """Gmail (Google Workspace included), Outlook (Microsoft 365 included) or other."""
    if mailbox.auth == "google" or mailbox.imap_host.lower() == GOOGLE_IMAP_HOST:
        return "Gmail"
    if mailbox.auth == "microsoft" or mailbox.imap_host.lower() in _OUTLOOK_HOSTS:
        return "Outlook"
    return "other"


def mailbox_kinds(book: MailboxBook) -> str:
    """How many mailboxes of each kind, `1 Gmail, 2 other`; never a name or an address."""
    try:
        mailboxes: dict[str, Mailbox] = book.mailboxes()
    except Exception as error:
        return f"cannot be read ({type(error).__name__})"
    counts: Counter[str] = Counter(provider_kind(mailbox) for mailbox in mailboxes.values())
    return ", ".join(f"{counts[kind]} {kind}" for kind in _KINDS if counts[kind]) or "none"


def audit_tail(path: Path) -> list[bytes]:
    """The whole lines at the end of the audit log; [] when there is no log."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size: int = handle.tell()
        handle.seek(max(0, size - _TAIL_BYTES))
        tail: bytes = handle.read()
    lines: list[bytes] = tail.split(b"\n")
    # A tail that starts mid-file starts mid-line.
    return lines[1:] if size > _TAIL_BYTES else lines


def failure_line(record: dict[str, Any], home: Path | None) -> str:
    """`2026-10-23 14:03 UTC send_email (SMTPAuthenticationError) message`, redacted, then shortened."""
    try:
        when: str = datetime.fromisoformat(str(record.get("time"))).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        when = "unknown time"
    outcome: str = str(record.get("outcome", ""))
    if len(outcome) > _OUTCOME_READ:
        # Cut at a word's start, so no part of a long token is left to pass as a short one.
        outcome = re.sub(r"\S*$", "", outcome[:_OUTCOME_READ]) + "..."
    kind: str
    separator: str
    message: str
    kind, separator, message = outcome.partition(": ")
    # The error's type in brackets: a colon after a name such as MissingPassword would read as a secret.
    described: str = f"({kind}) {message}" if separator and kind.isidentifier() else outcome
    line: str = redact(f"{when} {record.get('tool', '')} {described}", home)
    return line if len(line) <= _OUTCOME_LIMIT else line[: _OUTCOME_LIMIT - 3] + "..."


def failed_calls(path: Path, count: int, home: Path | None = None) -> list[str]:
    """The last `count` failed calls in the audit log, newest first."""
    try:
        lines: list[bytes] = audit_tail(path)
    except FileNotFoundError:
        return []
    except OSError as error:
        return [f"the audit log could not be read ({type(error).__name__})"]
    failures: list[dict[str, Any]] = []
    line: bytes
    for line in lines:
        record: dict[str, Any] | None = parse_record(line)
        if (
            record is not None
            and record.get("phase") == "finished"
            and not str(record.get("outcome", "")).startswith("ok")
        ):
            failures.append(record)
    return [failure_line(record, home) for record in reversed(failures[-count:])] if count > 0 else []


def build_report(description: str, app: str, mailboxes: str, failures: list[str], home: Path | None = None) -> str:
    """The report the user reads: the problem, then the setup, then recent failures; all of it redacted."""
    lines: list[str] = [
        f"Problem: {description.strip() or 'no description'}",
        "",
        f"email-tool: {version('email-tool-mcp')}",
        f"System: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
        f"App: {app.strip() or 'unknown'}",
        f"Mailboxes: {mailboxes}",
        "Recent failed calls, newest first:" if failures else "Recent failed calls: none",
        *(f"- {failure}" for failure in failures),
    ]
    return redact("\n".join(lines), home)


def report_title(report: str) -> str:
    """The report's first line, without its `Problem:` label, short enough for a subject."""
    first: str = next((line.strip() for line in report.splitlines() if line.strip()), "")
    title: str = first.removeprefix("Problem:").strip() or "no description"
    return title if len(title) <= _TITLE_LIMIT else title[: _TITLE_LIMIT - 3] + "..."


def report_email(report: str, home: Path | None = None) -> dict[str, str]:
    """The `to`, `subject` and `body` of the emailed report; redacted again, so added text is cleaned too."""
    body: str = redact(report[:REPORT_LIMIT], home)
    return {"to": REPORT_ADDRESS, "subject": f"{SUBJECT_PREFIX} {report_title(body)}", "body": body}


def link_to(title: str, body: str) -> str:
    """The new-issue link for the report form with `title` and `body` filled in."""
    fields: dict[str, str] = {"template": ISSUE_TEMPLATE, "title": title, REPORT_FIELD: body}
    return f"{NEW_ISSUE_URL}?{urlencode(fields, quote_via=quote)}"


def issue_link(report: str) -> str:
    """A GitHub link that opens a new `user-report` issue with the report filled in, shortened if it must be."""
    title: str = f"{SUBJECT_PREFIX} {report_title(report)}"
    link: str = link_to(title, report)
    body: str = report
    while len(link) > _LINK_LIMIT and body:
        body = body[: len(body) * 9 // 10]
        link = link_to(title, body + _SHORTENED)
    return link


def reply(report: str) -> str:
    """What report_problem tells the assistant: the report to show, and the two ways to send it."""
    return "\n".join(
        [
            "Nothing has been sent. Show the user this report exactly as written, between the lines:",
            REPORT_START,
            report,
            REPORT_END,
            "Then ask which way they want to send it, if at all:",
            f"1. By email from one of their own mailboxes to the email-tool maintainer ({REPORT_ADDRESS}): call "
            "email_problem_report with `report` set to the text between the lines and the mailbox they choose. "
            "Their app shows them the exact message to approve first.",
            "2. On GitHub (needs a free GitHub account): give them this link. It opens a new issue with the report "
            "filled in, which they check and submit themselves:",
            issue_link(report),
        ]
    )
