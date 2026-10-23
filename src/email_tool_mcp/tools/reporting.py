"""Problem-report tools: build a redacted report, and email it to the maintainer once the user approves.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/reporting.py, one module per tool group.
"""

from __future__ import annotations

from pathlib import Path

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.problem_report import FAILED_CALLS, build_report, failed_calls, mailbox_kinds, reply, report_email
from email_tool_mcp.tools.params import MailboxName, ProblemDescription, Report
from email_tool_mcp.tools.sending import SendingTools


class ReportingTools:
    """The tools a user reports a problem with."""

    def __init__(self, book: MailboxBook, audit_log: Path, sending: SendingTools) -> None:
        self._book: MailboxBook = book
        self._audit_log: Path = audit_log
        self._sending: SendingTools = sending

    def report_problem(self, description: ProblemDescription, app: str = "") -> str:
        """Build a problem report for the email-tool maintainer when the user wants to report a problem.

        It holds the versions, the app, the kinds of mailbox and the last few failed calls, with
        addresses, subjects, quoted text, home-folder paths, passwords, tokens and keys removed.
        It changes nothing and sends nothing; it says how the user can send it.
        """
        failures: list[str] = failed_calls(self._audit_log, FAILED_CALLS)
        return reply(build_report(description, app, mailbox_kinds(self._book), failures))

    def email_problem_report(self, report: Report, mailbox: MailboxName = "") -> str:
        """Email a report from report_problem to the email-tool maintainer, from one of the user's mailboxes.

        The user's app always shows them the exact message to approve first. If the app cannot ask,
        nothing is sent: offer the GitHub link from report_problem instead.
        """
        email: dict[str, str] = report_email(report)
        return self._sending.send_email(email["to"], email["subject"], email["body"], mailbox=mailbox)
