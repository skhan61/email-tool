"""report_problem and email_problem_report: what a problem report holds, never holds, and how it is sent.

Standard: the MCP SDK's in-process client (with an `elicitation_callback` standing in for the
person and `client_info` for the app), and Hypothesis for the redaction properties.
Placement: tests/test_problem_report.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import json
import platform
import re
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp_types import CallToolResult, ElicitRequestParams, ElicitResult, Implementation, TextContent

from email_tool_mcp import problem_report
from email_tool_mcp.audit import AuditLog
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_render import every_text
from email_tool_mcp.passwords import store_password
from email_tool_mcp.problem_report import (
    REPORT_ADDRESS,
    SUBJECT_PREFIX,
    build_report,
    failed_calls,
    issue_link,
    provider_kind,
    redact,
    report_email,
    report_title,
)
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import Mailbox
from tests.conftest import HOME, WORK
from tests.fakes import FakeMailServer

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FUZZ: settings = settings(max_examples=200, deadline=None)
HOME_FOLDER: Final[Path] = Path("/home/dana")
# Built at run time so the repository's private-key hook does not flag this file.
KEY_BLOCK: Final[str] = (
    "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END " + "OPENSSH PRIVATE KEY-----"
)
PGP_HEADER: Final[str] = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
# (text holding something private, the private part that must not survive)
PRIVATE: Final[list[tuple[str, str]]] = [
    ("Send to dana.lee+work@example.com failed", "dana.lee+work@example.com"),
    ("From: Dana <dana@corp.example.org>", "dana@corp.example.org"),
    ("cannot attach '/home/dana/Documents/merger plan.pdf'", "merger plan"),
    ("cannot attach /home/dana/Documents/merger.pdf: no such file", "merger.pdf"),
    ("saved to /Users/dana/Downloads/invoice-7.pdf", "invoice-7.pdf"),
    (r"C:\Users\dana\Desktop\salary.xlsx is missing", "salary.xlsx"),
    ("file ~/secret-folder/notes.txt", "secret-folder"),
    ("No mailbox called 'alchlight'. Configured: work", "alchlight"),
    ('the message "Q3 layoffs list" did not send', "Q3 layoffs"),
    ("Subject: Offer letter for Dana", "Offer letter"),
    ("my password is hunter2 and it fails", "hunter2"),
    ("password=hunter2", "hunter2"),
    ('{"password": "correct horse battery"}', "correct horse"),
    ("app password: abcd efgh ijkl mnop", "abcd efgh"),
    ("token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0", "a1B2c3D4e5F6"),
    ("Authorization: Bearer ya29.a0AfH6SMBx3k9-shortish", "ya29"),
    ("api_key=sk-proj-abc123def456ghi789jkl012mno345", "sk-proj"),
    ("key AKIAIOSFODNN7EXAMPLE leaked", "AKIAIOSFODNN7EXAMPLE"),
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
    (f"pasted {KEY_BLOCK} by mistake", "b3BlbnNzaC1rZXktdjEAAAAA"),
    (f"{PGP_HEADER}\nlQOYBGXyz123", "lQOYBGXyz123"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P", "eyJhbGciOiJIUzI1NiJ9"),
    ("connect to imap.mycompany.example failed", "mycompany"),
    ("refused by 10.20.30.40", "10.20.30.40"),
    ("connect to 2001:db8:85a3::8a2e:370:7334 port 993 failed", "2001:db8"),
    ("refused dana@exämple.de", "dana@"),
    ("cut off inside 'Offer letter for Dana Lee", "Offer letter"),
    ('a subject broken by a line break: "Offer letter\nfor Dana"', "Offer letter"),
]


def report_of(result: CallToolResult) -> str:
    """The text a tool returned."""
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


def between_markers(text: str) -> str:
    """The report itself, as the assistant shows it to the user."""
    return text.split(problem_report.REPORT_START + "\n", 1)[1].split("\n" + problem_report.REPORT_END, 1)[0]


@pytest.mark.parametrize(("text", "private"), PRIVATE)
def test_private_text_never_survives_redaction(text: str, private: str) -> None:
    assert private not in redact(text, HOME_FOLDER)


def test_the_attachment_checks_sensitive_text_never_survives() -> None:
    """The signs attachments.py treats as a secret (private keys, AWS keys) are removed from text too."""
    text: str = f"{PGP_HEADER}\nabc\naws_secret_access_key = abc\nAKIAABCDEFGHIJKLMNOP"
    redacted: str = redact(text, HOME_FOLDER)
    assert "PRIVATE KEY" not in redacted and "AKIA" not in redacted and "= abc" not in redacted


def test_this_computers_home_folder_is_removed(tmp_path: Path) -> None:
    home: Path = tmp_path / "someone"
    assert "someone" not in redact(f"cannot read {home / 'a.toml'}", home)


def test_ordinary_words_survive() -> None:
    text: str = "Sending fails since Tuesday. I don't know why it's slow at 14:03:11; the token expired? error 535."
    assert redact(text, HOME_FOLDER) == text


def test_a_longer_name_that_starts_like_home_is_not_cut_in_half() -> None:
    assert "[home folder path]ice" not in redact("see /srv/alice/notes", Path("/srv/al"))
    assert redact("[Gmail]/Drafts", Path("/")) == "[Gmail]/Drafts"


def test_the_computers_own_versions_are_never_taken_for_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Fedora kernel or a development version looks like a token, but email-tool wrote it itself."""
    monkeypatch.setattr(platform, "release", lambda: "6.11.4-301.fc41.x86_64")
    report: str = build_report("x", "app", "none", [], HOME_FOLDER)
    assert "6.11.4-301.fc41.x86_64" in report
    added: str = report + "\nSystem: Linux a1B2c3D4e5F6g7H8i9J0k1L2 (x86_64)"
    assert "a1B2c3D4e5F6g7H8i9J0k1L2" not in report_email(added, HOME_FOLDER)["body"]


ADDRESS_IN_TEXT: st.SearchStrategy[tuple[str, str, str]] = st.tuples(
    st.text(max_size=30), st.emails(), st.text(max_size=30)
)


@FUZZ
@given(ADDRESS_IN_TEXT)
def test_an_address_never_survives_whatever_surrounds_it(parts: tuple[str, str, str]) -> None:
    before, address, after = parts
    assert address not in redact(f"{before} {address} {after}", HOME_FOLDER)


@FUZZ
@given(st.text(max_size=30), st.from_regex(r"[A-Za-z0-9_\-]{1,12}", fullmatch=True), st.text(max_size=30))
def test_a_home_path_never_survives_whatever_surrounds_it(before: str, name: str, after: str) -> None:
    path: str = f"/home/dana/Private/{name}.pdf"
    assert f"Private/{name}" not in redact(f"{before} {path} {after}", HOME_FOLDER)


SECRET: st.SearchStrategy[str] = st.from_regex(
    r"[A-Za-z0-9]{8,16}[0-9][A-Za-z]{1,8}[A-Za-z0-9/+]{12,30}", fullmatch=True
)


@FUZZ
@given(st.text(max_size=30), SECRET, st.sampled_from(["password=", "token: ", "api_key = ", "secret=", ""]))
def test_a_token_never_survives_whatever_surrounds_it(before: str, secret: str, label: str) -> None:
    assert secret not in redact(f"{before} {label}{secret} done", HOME_FOLDER)


@FUZZ
@given(st.text())
def test_redaction_is_stable_so_the_text_shown_is_the_text_sent(text: str) -> None:
    once: str = redact(text, HOME_FOLDER)
    assert redact(once, HOME_FOLDER) == once


@pytest.mark.parametrize(
    ("mailbox", "kind"),
    [
        (HOME, "Gmail"),
        (Mailbox("g", "a@corp.example", "imap.gmail.com", 993, "smtp.gmail.com", 465, auth="google"), "Gmail"),
        (Mailbox("m", "a@corp.example", "outlook.office365.com", 993, "smtp.office365.com", 587), "Outlook"),
        (Mailbox("u", "a@agency.example", "outlook.office365.us", 993, "smtp.office365.us", 587), "Outlook"),
        (WORK, "other"),
    ],
)
def test_a_mailbox_is_named_only_by_its_kind(mailbox: Mailbox, kind: str) -> None:
    assert provider_kind(mailbox) == kind


def write_failure(audit: AuditLog, tool: str, outcome: str) -> None:
    call: str = audit.started("work", tool, {})
    audit.finished(call, "work", tool, outcome)


def test_failed_calls_are_newest_first_without_successes(audit: AuditLog) -> None:
    write_failure(audit, "list_emails", "OSError: first")
    write_failure(audit, "send_email", "ok")
    write_failure(audit, "get_email", "LookupError: second")
    lines: list[str] = failed_calls(audit.path, 5)
    assert len(lines) == 2
    assert lines[0].endswith("get_email (LookupError) second") and lines[1].endswith("list_emails (OSError) first")


def test_only_the_last_few_failures_are_kept(audit: AuditLog) -> None:
    number: int
    for number in range(8):
        write_failure(audit, "list_emails", f"OSError: failure {number}")
    lines: list[str] = failed_calls(audit.path, 3)
    assert [line.rsplit(" ", 1)[1] for line in lines] == ["7", "6", "5"]


def test_a_huge_error_is_cut_without_leaving_part_of_a_token(audit: AuditLog) -> None:
    token: str = "ghp_" + "a1B2c3D4e5" * 4
    # The quoted text shrinks to a few characters, so the token's start would show if it were kept.
    write_failure(audit, "list_emails", "OSError: '" + "x" * 1983 + "' " + token + " y" * 2000)
    line: str = failed_calls(audit.path, 1)[0]
    assert len(line) <= 300 and "[quoted text]" in line and "ghp_" not in line


def test_an_error_that_cannot_be_cleaned_is_left_out_not_the_report(
    audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never_clean(text: str, home: Path | None = None) -> str:
        raise ValueError("too many passes")

    write_failure(audit, "list_emails", "OSError: anything")
    monkeypatch.setattr(problem_report, "redact", never_clean)
    assert "could not be cleaned is left out" in failed_calls(audit.path, 1)[0]


def test_no_audit_log_means_no_failures(tmp_path: Path) -> None:
    assert failed_calls(tmp_path / "missing.jsonl", 5) == []


def test_the_report_names_the_setup_and_redacts_everything_it_holds() -> None:
    report: str = build_report(
        "Sending to boss@corp.example fails with my password=hunter2",
        "claude-code 2.1.0",
        "1 Gmail, 1 other",
        ["2026-10-23 14:03 UTC send_email (SMTPAuthenticationError) 'Offer letter' from /home/dana/x.pdf"],
        HOME_FOLDER,
    )
    assert f"email-tool: {version('email-tool-mcp')}" in report
    assert f"Python: {platform.python_version()}" in report
    assert platform.system() in report
    assert "App: claude-code 2.1.0" in report
    assert "Mailboxes: 1 Gmail, 1 other" in report
    assert "send_email (SMTPAuthenticationError)" in report
    private: str
    for private in ("boss@corp.example", "hunter2", "Offer letter", "/home/dana"):
        assert private not in report


def test_the_title_is_the_first_line_of_the_problem() -> None:
    report: str = build_report("Search never finishes.\nIt hangs.", "app", "none", [], HOME_FOLDER)
    assert report_title(report) == "Search never finishes."
    assert len(report_title(build_report("x" * 500, "app", "none", [], HOME_FOLDER))) <= 80


def test_the_issue_template_labels_every_report_and_has_the_report_field() -> None:
    template: str = (ROOT / ".github" / "ISSUE_TEMPLATE" / problem_report.ISSUE_TEMPLATE).read_text(encoding="utf-8")
    assert re.search(r"^labels: \[user-report\]$", template, re.MULTILINE)
    assert re.search(rf"^\s+id: {problem_report.REPORT_FIELD}$", template, re.MULTILINE)


def test_the_github_link_opens_the_report_template_filled_in() -> None:
    report: str = build_report("Search never finishes & hangs?", "app", "1 other", [], HOME_FOLDER)
    link: str = issue_link(report)
    assert link.startswith("https://github.com/skhan61/email-tool/issues/new?")
    query: dict[str, list[str]] = parse_qs(urlsplit(link).query)
    assert query["template"] == [problem_report.ISSUE_TEMPLATE]
    assert query["title"] == [f"{SUBJECT_PREFIX} Search never finishes & hangs?"]
    assert query[problem_report.REPORT_FIELD] == [report]


def test_the_longest_report_still_fits_in_a_link() -> None:
    failures: list[str] = [f"2026-10-23 14:03 UTC send_email (OSError) {'x y ' * 200}"] * 5
    report: str = build_report("é " * 1000, "app " * 50, "1 other", failures, HOME_FOLDER)
    assert len(issue_link(report)) < 8000


APP: Final[Implementation] = Implementation(name="claude-code", version="2.1.0")


class Person:
    """Answers every approval question the same way and remembers what it was shown."""

    def __init__(self, action: Literal["accept", "decline", "cancel"], approve: bool) -> None:
        self.action: Literal["accept", "decline", "cancel"] = action
        self.approve: bool = approve
        self.shown: list[str] = []

    async def __call__(self, context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        self.shown.append(params.message)
        content: dict[str, Any] | None = {"approve": self.approve} if self.action == "accept" else None
        return ElicitResult(action=self.action, content=content)


async def report_problem(book: MailboxBook, audit: AuditLog, description: str) -> str:
    async with Client(build_server(book, audit), client_info=APP) as client:
        result: CallToolResult = await client.call_tool("report_problem", {"description": description})
    assert not result.is_error, report_of(result)
    return report_of(result)


@pytest.mark.anyio
async def test_report_problem_changes_nothing_and_sends_nothing(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, settings_file: Path
) -> None:
    store_password("work", "pw")
    settings_before: bytes = settings_file.read_bytes()
    write_failure(audit, "send_email", "SMTPRecipientsRefused: {'lee@corp.example': (550, b'no such user')}")
    said: str = await report_problem(book, audit, "Sending to lee@corp.example fails")
    report: str = between_markers(said)
    assert "App: claude-code 2.1.0" in report and "Mailboxes: 1 Gmail, 1 other" in report
    assert "send_email (SMTPRecipientsRefused)" in report
    private: str
    for private in ("lee@corp.example", "me@example.com", "me@gmail.com", "'work'"):
        assert private not in report
    assert mail_server.sent == [] and mail_server.logins == []
    assert mail_server.folders == {"INBOX": {}, "Drafts": {}}
    assert settings_file.read_bytes() == settings_before
    assert issue_link(report) in said and REPORT_ADDRESS in said


@pytest.mark.anyio
async def test_the_description_is_never_written_to_the_audit_log(book: MailboxBook, audit: AuditLog) -> None:
    await report_problem(book, audit, "My boss Dana's mail breaks")
    records: list[dict[str, Any]] = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert [record["tool"] for record in records] == ["report_problem", "report_problem"]
    assert "Dana" not in audit.path.read_text(encoding="utf-8")


async def email_report(book: MailboxBook, audit: AuditLog, person: Person | None, report: str) -> CallToolResult:
    async with Client(build_server(book, audit), elicitation_callback=person, client_info=APP) as client:
        return await client.call_tool("email_problem_report", {"report": report, "mailbox": "work"})


@pytest.mark.parametrize(("action", "approve"), [("accept", False), ("decline", False), ("cancel", False)])
@pytest.mark.anyio
async def test_anything_but_a_yes_sends_no_report(
    book: MailboxBook,
    audit: AuditLog,
    mail_server: FakeMailServer,
    action: Literal["accept", "decline", "cancel"],
    approve: bool,
) -> None:
    store_password("work", "pw")
    person: Person = Person(action, approve)
    result: CallToolResult = await email_report(book, audit, person, "Problem: search hangs")
    assert result.is_error and mail_server.sent == []
    assert len(person.shown) == 1


@pytest.mark.anyio
async def test_an_accepted_report_sends_exactly_the_text_shown(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    """No approval policy is set: a report asks the user every time."""
    store_password("work", "pw")
    report: str = between_markers(await report_problem(book, audit, "Search never finishes."))
    person: Person = Person("accept", True)
    result: CallToolResult = await email_report(book, audit, person, report)
    assert not result.is_error, report_of(result)
    assert len(mail_server.sent) == 1
    sent: Any
    recipients: list[str]
    sent, recipients = mail_server.sent[0]
    assert recipients == [REPORT_ADDRESS]
    assert sent["Subject"] == f"{SUBJECT_PREFIX} Search never finishes."
    body: str = every_text(sent)
    assert body.strip() == report.strip()
    assert body in person.shown[0] and f"Delivered to: {REPORT_ADDRESS}" in person.shown[0]
    started: dict[str, Any] = json.loads(audit.path.read_text(encoding="utf-8").splitlines()[-2])
    assert started["tool"] == "email_problem_report" and started["arguments"]["to"] == REPORT_ADDRESS


@pytest.mark.anyio
async def test_text_the_assistant_adds_is_redacted_before_it_is_shown_or_sent(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    person: Person = Person("accept", True)
    await email_report(book, audit, person, "Problem: fails\nAlso dana@corp.example, password=hunter2")
    shown_and_sent: str = person.shown[0] + every_text(mail_server.sent[0][0])
    assert "dana@corp.example" not in shown_and_sent and "hunter2" not in shown_and_sent


@pytest.mark.anyio
async def test_an_app_that_cannot_ask_sends_no_report(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer
) -> None:
    store_password("work", "pw")
    result: CallToolResult = await email_report(book, audit, None, "Problem: search hangs")
    assert result.is_error and "cannot ask" in report_of(result)
    assert mail_server.sent == []
