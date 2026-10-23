"""Emailed problem reports become GitHub issues: one per message, never two, with no address in them.

Standard: pytest with the offline fakes (tests/fakes.py) for the mailbox and a recording fake for the
GitHub side, so nothing here reaches a real mailbox or a real repository.
Placement: tests/test_report_bridge.py, beside the other tools' tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage

import pytest
from github import GithubException

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from tests.fakes import FakeMailServer
from tools.bot_pr import BotError
from tools.report_bridge._github import LABEL, BotTracker
from tools.report_bridge._mail import SUBJECT_PREFIX, find_reports, redact
from tools.report_bridge._run import bridge

SENDER: str = "Pat User <pat.user@example.org>"


@dataclass
class FakeTracker:
    """The GitHub side: the issues it holds, and whether the label exists."""

    bodies: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    label_made: bool = False

    def known(self) -> str:
        return "\n".join(self.bodies)

    def ensure_label(self) -> None:
        self.label_made = True

    def open_issue(self, title: str, body: str) -> str:
        self.titles.append(title)
        self.bodies.append(body)
        return f"https://github.com/o/r/issues/{len(self.bodies)}"


def report(subject: str, body: str, message_id: str = "<report-1@example.org>") -> bytes:
    message: EmailMessage = EmailMessage()
    message["From"] = SENDER
    message["To"] = "s.khan@alchlight.com"
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message.set_content(body)
    return message.as_bytes()


@pytest.fixture
def signed_in(book: MailboxBook) -> MailboxBook:
    store_password("work", "secret")
    return book


def test_a_report_becomes_one_issue_with_no_address(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add(
        "INBOX",
        report(
            f"{SUBJECT_PREFIX} drafts fail for pat.user@example.org",
            "Steps: open a draft.\nCopy sent to other@example.net and <third@example.com>.\n",
        ),
    )
    tracker: FakeTracker = FakeTracker()

    said: list[str] = bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies) == 1
    assert tracker.label_made
    issue: str = tracker.titles[0] + "\n" + tracker.bodies[0]
    for address in ("pat.user@example.org", "other@example.net", "third@example.com", "s.khan@alchlight.com"):
        assert address not in issue
    assert "@" not in issue
    assert "Steps: open a draft." in tracker.bodies[0]
    assert "drafts fail for" in tracker.titles[0]
    assert said == ["opened https://github.com/o/r/issues/1: drafts fail for [address removed]"]


def test_a_second_run_opens_nothing(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} crash on send", "It crashed."))
    tracker: FakeTracker = FakeTracker()
    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    said: list[str] = bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies) == 1
    assert said == ["already filed: crash on send"]


def test_the_same_report_in_two_copies_opens_one_issue(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} crash", "It crashed."))
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} crash", "It crashed."))
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies) == 1


def test_other_subjects_are_ignored(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add("INBOX", report("Lunch on Friday?", "Pizza."))
    mail_server.add("INBOX", report(f"Re: {SUBJECT_PREFIX} crash", "Thanks.", "<reply@example.org>"))
    mail_server.add("INBOX", report("EMAIL-TOOL PROBLEM REPORT: shouting", "Loud.", "<loud@example.org>"))
    tracker: FakeTracker = FakeTracker()

    said: list[str] = bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert tracker.bodies == []
    assert said == ["no problem reports in INBOX"]


def test_a_dry_run_changes_nothing(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    raw: bytes = report(f"{SUBJECT_PREFIX} crash", "It crashed.")
    mail_server.add("INBOX", raw)
    tracker: FakeTracker = FakeTracker()

    said: list[str] = bridge(signed_in, tracker, "work", "INBOX", dry_run=True)

    assert tracker.bodies == []
    assert not tracker.label_made
    assert mail_server.folders["INBOX"] == {1: raw}
    assert said[0] == "would open: crash"
    assert "It crashed." in said[1]


def test_the_report_body_cannot_ping_or_break_out_of_its_block(
    signed_in: MailboxBook, mail_server: FakeMailServer
) -> None:
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} x", "Hi @someone\n```\n# injected heading\n"))
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    body: str = tracker.bodies[0]
    assert "\n````text\nHi @someone\n```\n# injected heading\n````\n" in body


def test_a_message_without_a_message_id_is_still_filed_once(
    signed_in: MailboxBook, mail_server: FakeMailServer
) -> None:
    message: EmailMessage = EmailMessage()
    message["Subject"] = f"{SUBJECT_PREFIX} no id"
    message.set_content("Body.")
    mail_server.add("INBOX", message.as_bytes())
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)
    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies) == 1


@pytest.mark.parametrize(
    "text",
    [
        "a.b+tag@sub.example.co.uk",
        "<x@y.z>",
        "mailto:someone@example.org",
        "ü.ser@exämple.de",
        '"quoted" name@host',
    ],
)
def test_redact_removes_every_address(text: str) -> None:
    assert "@" not in redact(text)


def test_find_reports_does_not_mark_mail_or_move_it(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    raw: bytes = report(f"{SUBJECT_PREFIX} crash", "It crashed.")
    mail_server.add("INBOX", raw)

    with signed_in.imap(signed_in.resolve("work")) as session:
        found: int = len(find_reports(session, "INBOX"))

    assert found == 1
    assert mail_server.folders == {"INBOX": {1: raw}, "Drafts": {}}


# ── the real tracker, over a stand-in for PyGithub's Repository ──────────────


@dataclass
class FakeIssue:
    body: str | None


@dataclass
class FakeRepository:
    """The four calls BotTracker makes on a PyGithub Repository."""

    labels: list[str] = field(default_factory=list)
    issues: list[FakeIssue] = field(default_factory=list)
    asked_labels: list[list[str]] = field(default_factory=list)

    def get_label(self, name: str) -> str:
        if name not in self.labels:
            raise GithubException(404, {"message": "Not Found"}, None)
        return name

    def create_label(self, name: str, color: str, description: str) -> str:
        self.labels.append(name)
        return name

    def get_issues(self, state: str, labels: list[str]) -> list[FakeIssue]:
        self.asked_labels.append(labels)
        return self.issues

    def create_issue(self, title: str, body: str, labels: list[str]) -> object:
        raise GithubException(403, {"message": "Resource not accessible by integration"}, None)


def test_the_bot_tracker_makes_the_label_once_and_reads_bodies() -> None:
    repository: FakeRepository = FakeRepository(issues=[FakeIssue("one"), FakeIssue(None), FakeIssue("two")])
    tracker: BotTracker = BotTracker(repository)  # type: ignore[arg-type]

    tracker.ensure_label()
    tracker.ensure_label()

    assert repository.labels == [LABEL]
    assert tracker.known() == "one\n\ntwo"
    assert repository.asked_labels == [[LABEL]]


def test_the_bot_tracker_reads_nothing_while_the_label_is_missing() -> None:
    repository: FakeRepository = FakeRepository(issues=[FakeIssue("ignored")])

    assert BotTracker(repository).known() == ""  # type: ignore[arg-type]
    assert repository.asked_labels == []


def test_github_refusing_an_issue_is_said_plainly() -> None:
    with pytest.raises(BotError, match="HTTP 403: Resource not accessible"):
        BotTracker(FakeRepository(labels=[LABEL])).open_issue("t", "b")  # type: ignore[arg-type]
