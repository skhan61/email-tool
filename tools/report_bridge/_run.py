"""Turn each emailed report into one GitHub issue: never two, never with an address in it.

Standard: email-tool's own mailbox book (`open_book`: this computer's settings, keyring and
sign-ins) for the mail, and the bot's PyGithub tracker for the issues.
Placement: tools/report_bridge/_run.py, called by `__main__.py` and by the tests with fakes.

NEVER TWO. Each issue body ends with `<!-- email-tool-report <key> -->`, the report's key being a hash
of its Message-ID. Before opening anything, every issue the bot opened (open or closed, any label) is
read, and a report whose marker is the LAST line of one of them is skipped; a marker inside the report's
own text does not count. The marker is in the body, not in GitHub's search index, so a second run
straight after the first sees it. Only a deleted or transferred issue is forgotten.

ONE REFUSED REPORT DOES NOT BLOCK THE REST: it is said and skipped, and the next run tries it again.
"""

from __future__ import annotations

import os
import re
from typing import Final, Protocol

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.providers import open_book
from tools.bot_pr import BotError
from tools.bot_pr._github import _reached
from tools.report_bridge._github import bot_tracker
from tools.report_bridge._mail import Report, find_reports

# GitHub refuses an issue body over 65,536 characters: the text, two fences of at most `_FENCE_LIMIT`
# backticks and the two short lines around them stay well under it.
_TEXT_LIMIT: Final[int] = 60_000
_TITLE_LIMIT: Final[int] = 200
_FENCE_LIMIT: Final[int] = 16
_BACKTICKS: Final[re.Pattern[str]] = re.compile(r"`+")
_LONG_BACKTICKS: Final[re.Pattern[str]] = re.compile(f"`{{{_FENCE_LIMIT},}}")


class Tracker(Protocol):
    """Where reports become issues: the bot's GitHub repository, or a fake in the tests."""

    def filed(self) -> list[str]: ...

    def ensure_label(self) -> None: ...

    def open_issue(self, title: str, body: str) -> str: ...


def marker(report: Report) -> str:
    """The line that ties an issue to its report, hidden when GitHub renders the body."""
    return f"<!-- email-tool-report {report.key} -->"


def issue_body(report: Report) -> str:
    """The report's text in a fenced block (so it cannot ping anyone or add markup), and its marker."""
    text: str = _LONG_BACKTICKS.sub("`" * (_FENCE_LIMIT - 1), report.text[:_TEXT_LIMIT]).rstrip()
    if len(report.text) > _TEXT_LIMIT:
        text += "\n[cut: the report was longer than a GitHub issue allows]"
    longest: int = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    fence: str = "`" * max(3, longest + 1)
    arrived: str = f" on {report.date}" if report.date else ""
    return (
        f"A problem report that arrived by email{arrived}. Every address was removed.\n\n"
        f"{fence}text\n{text}\n{fence}\n\n{marker(report)}\n"
    )


def bridge(book: MailboxBook, tracker: Tracker, mailbox: str, folder: str, dry_run: bool) -> list[str]:
    """Open one issue per new report in `folder` of `mailbox`; what was done, one line each."""
    with book.imap(book.resolve(mailbox)) as session:
        reports: list[Report] = find_reports(session, folder)
    if not reports:
        return [f"no problem reports in {folder}"]
    filed: set[str] = {_last_line(body) for body in tracker.filed()}
    new: list[Report] = []
    said: list[str] = []
    for report in reports:
        if marker(report) in filed:
            said.append(f"already filed: {report.title[:_TITLE_LIMIT]}")
        else:
            filed.add(marker(report))
            new.append(report)
    if new and not dry_run:
        tracker.ensure_label()
    for report in new:
        title: str = report.title[:_TITLE_LIMIT]
        body: str = issue_body(report)
        if dry_run:
            said.extend([f"would open: {title}", body])
            continue
        try:
            said.append(f"opened {tracker.open_issue(title, body)}: {title}")
        except BotError as error:
            said.append(f"not opened, tried again next run: {title}: {error}")
    return said


def _last_line(body: str) -> str:
    lines: list[str] = body.strip().splitlines()
    return lines[-1].strip() if lines else ""


def run(mailbox: str = "", folder: str = "INBOX", dry_run: bool = False) -> str:
    """Open a GitHub issue, as the bot, for each new report in `folder`; with `dry_run`, only say which."""
    # `fire` turns a numeric-looking flag into a number; a mailbox or folder name is text.
    return _reached(
        lambda: "\n".join(
            bridge(open_book(os.environ, with_policy=True), bot_tracker(), str(mailbox), str(folder), bool(dry_run))
        )
    )
