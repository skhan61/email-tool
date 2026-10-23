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
BOT: str = "test-bot[bot]"


@dataclass
class FakeTracker:
    """The GitHub side: the issues it holds, and whether the label exists."""

    bodies: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    label_made: bool = False
    refused: str = ""

    def filed(self) -> list[str]:
        return list(self.bodies)

    def ensure_label(self) -> None:
        self.label_made = True

    def open_issue(self, title: str, body: str) -> str:
        if title == self.refused:
            raise BotError("could not open the issue (HTTP 422: Validation Failed)")
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


def test_a_report_without_a_message_id_delivered_twice_is_filed_once(
    signed_in: MailboxBook, mail_server: FakeMailServer
) -> None:
    for relay in ("mx1.example.org", "mx2.example.org"):
        message: EmailMessage = EmailMessage()
        message["Received"] = f"from {relay}"
        message["Subject"] = f"{SUBJECT_PREFIX} no id"
        message.set_content("Body.")
        mail_server.add("INBOX", message.as_bytes())
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)
    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies) == 1


def test_the_date_header_cannot_carry_text_into_the_issue(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    raw: bytes = report(f"{SUBJECT_PREFIX} x", "Body.").replace(
        b"Message-ID:", b"Date: =?utf-8?q?Mon=0A@maintainer_[x](http://evil)_bob@corp.com?=\nMessage-ID:"
    )
    mail_server.add("INBOX", raw)
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert "evil" not in tracker.bodies[0]
    assert "@" not in tracker.bodies[0]
    assert tracker.bodies[0].startswith("A problem report that arrived by email. ")


def test_the_date_is_shown_as_its_day(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    raw: bytes = report(f"{SUBJECT_PREFIX} x", "Body.").replace(
        b"Message-ID:", b"Date: Fri, 23 Oct 2026 09:15:00 -0400\nMessage-ID:"
    )
    mail_server.add("INBOX", raw)
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert tracker.bodies[0].startswith("A problem report that arrived by email on 2026-10-23. ")


def test_a_subject_in_an_unknown_charset_is_still_filed(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    # Raw bytes: EmailMessage would decode the encoded word on assignment.
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} PLACEHOLDER", "Body.").replace(b"PLACEHOLDER", b"=?bogus?q?x?="))
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert tracker.titles == ["=?bogus?q?x?="]


def test_a_refused_report_does_not_block_the_next(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} refused", "One.", "<one@example.org>"))
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} fine", "Two.", "<two@example.org>"))
    tracker: FakeTracker = FakeTracker(refused="refused")

    said: list[str] = bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert tracker.titles == ["fine"]
    assert said[0].startswith("not opened, tried again next run: refused: could not open the issue (HTTP 422")


def test_a_marker_quoted_in_a_report_does_not_count_as_filed(
    signed_in: MailboxBook, mail_server: FakeMailServer
) -> None:
    target: bytes = report(f"{SUBJECT_PREFIX} target", "Two.", "<target@example.org>")
    mail_server.add("INBOX", target)
    preview: list[str] = bridge(signed_in, FakeTracker(), "work", "INBOX", dry_run=True)
    target_marker: str = preview[1].strip().splitlines()[-1]
    mail_server.folders["INBOX"].clear()
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} quoting", f"See {target_marker}\n", "<quoting@example.org>"))
    tracker: FakeTracker = FakeTracker()
    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)
    mail_server.add("INBOX", target)

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert tracker.titles == ["quoting", "target"]


def test_a_huge_backtick_run_still_fits_a_github_issue(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    mail_server.add("INBOX", report(f"{SUBJECT_PREFIX} ticks", "`" * 59_000))
    tracker: FakeTracker = FakeTracker()

    bridge(signed_in, tracker, "work", "INBOX", dry_run=False)

    assert len(tracker.bodies[0]) < 65_536


@pytest.mark.parametrize(
    "text",
    [
        "a.b+tag@sub.example.co.uk",
        "<x@y.z>",
        "mailto:someone@example.org",
        "ü.ser@exämple.de",
        '"quoted" name@host',
        '"john doe"@example.com',
        "@@x@y.z",
    ],
)
def test_redact_removes_every_address(text: str) -> None:
    assert "@" not in redact(text)
    assert "john" not in redact(text)


def test_redact_keeps_a_mention_and_ordinary_words() -> None:
    assert redact('say "hi there" to @someone, (ok)') == 'say "hi there" to @someone, (ok)'


@pytest.mark.timeout(5)
def test_redact_is_linear_in_a_long_run_without_an_address() -> None:
    assert redact("a" * 1_000_000) == "a" * 1_000_000


def test_find_reports_does_not_mark_mail_or_move_it(signed_in: MailboxBook, mail_server: FakeMailServer) -> None:
    raw: bytes = report(f"{SUBJECT_PREFIX} crash", "It crashed.")
    mail_server.add("INBOX", raw)

    with signed_in.imap(signed_in.resolve("work")) as session:
        found: int = len(find_reports(session, "INBOX"))

    assert found == 1
    assert mail_server.folders == {"INBOX": {1: raw}, "Drafts": {}}


# ── the real tracker, over a stand-in for PyGithub's Repository ──────────────


@dataclass
class FakeUser:
    login: str


@dataclass
class FakeIssue:
    body: str | None
    user: FakeUser | None = field(default_factory=lambda: FakeUser(BOT))


@dataclass
class FakeRepository:
    """The calls BotTracker makes on a PyGithub Repository."""

    labels: list[str] = field(default_factory=list)
    issues: list[FakeIssue] = field(default_factory=list)

    def get_label(self, name: str) -> str:
        if name not in self.labels:
            raise GithubException(404, {"message": "Not Found"}, None)
        return name

    def create_label(self, name: str, color: str, description: str) -> str:
        self.labels.append(name)
        return name

    def get_issues(self, state: str) -> list[FakeIssue]:
        assert state == "all"
        return self.issues

    def create_issue(self, title: str, body: str, labels: list[str]) -> object:
        raise GithubException(403, {"message": "Resource not accessible by integration"}, None)


def test_the_bot_tracker_makes_the_label_once() -> None:
    repository: FakeRepository = FakeRepository()
    tracker: BotTracker = BotTracker(repository, BOT)  # type: ignore[arg-type]

    tracker.ensure_label()
    tracker.ensure_label()

    assert repository.labels == [LABEL]


def test_the_bot_tracker_counts_every_issue_the_bot_opened_and_no_other() -> None:
    issues: list[FakeIssue] = [
        FakeIssue("relabelled during triage"),
        FakeIssue(None),
        FakeIssue("a user's own issue", FakeUser("someone")),
        FakeIssue("ghost", None),
    ]

    filed: list[str] = BotTracker(FakeRepository(issues=issues), BOT).filed()  # type: ignore[arg-type]

    assert filed == ["relabelled during triage", ""]


def test_github_refusing_an_issue_is_said_plainly() -> None:
    with pytest.raises(BotError, match="HTTP 403: Resource not accessible"):
        BotTracker(FakeRepository(labels=[LABEL]), BOT).open_issue("t", "b")  # type: ignore[arg-type]
