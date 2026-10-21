"""CUI marking detection: banners, portion marks and subjects; mentions and look-alikes are not markings.

Standard: pytest, parametrized over marking examples from the DoD/NARA formats; the guard is driven through the server.
Placement: tests/test_cui.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest
from mcp import Client
from mcp_types import CallToolResult

from email_tool_mcp.audit import AuditLog
from email_tool_mcp.cui import markings, message_markings
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy
from email_tool_mcp.server import build_server
from tests.fakes import FakeMailServer


@pytest.mark.parametrize(
    "body",
    [
        "CUI\nThe drawings are attached.",
        "CONTROLLED\nText",
        "CUI//SP-PROPIN\nText",
        "CUI//SP-EXPT//NOFORN\nText",
        "  CUI//SP-CTI  \nText",
        "Text\n\nCUI",
        "(CUI) The tolerance is 5 um.",
        "(CUI//SP-PROPIN) Pricing follows.",
    ],
)
def test_markings_in_the_body_are_found(body: str) -> None:
    assert markings("", body)


@pytest.mark.parametrize("subject", ["CUI", "CUI//SP-PROPIN Quote", "CUI: drawings", "CONTROLLED - test data"])
def test_markings_in_the_subject_are_found(subject: str) -> None:
    assert markings(subject, "")


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Lunch", "We discussed CUI rules at the meeting."),
        ("Cuisine", "cui bono? the CUIsine menu is attached"),
        ("Re: SCUI board", "ACUITY test results"),
        ("Notes", "cui\nlowercase is not a marking"),
        ("Notes", "Uncontrolled release, CONTROLLED by the vendor"),
        ("Notes", "the value (cui) in lowercase"),
    ],
)
def test_mentions_and_look_alikes_are_not_markings(subject: str, body: str) -> None:
    assert markings(subject, body) == []


def test_a_banner_only_in_the_html_part_is_found() -> None:
    message: EmailMessage = compose(
        "me@x.com", "a@x.com", "Hello", "plain text, nothing here", "", "<p>CUI</p><p>x</p>"
    )
    assert message_markings(message) == ["banner: CUI"]


@pytest.fixture
def cui_book(settings_file: Path, tmp_path: Path, mail_server: FakeMailServer) -> MailboxBook:
    store_password("work", "pw")
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text('[default]\ncui_recipient_domains = ["example.com"]\n', encoding="utf-8")
    return MailboxBook(settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=Policy([policy_file]))


@pytest.mark.parametrize("tool", ["send_email", "create_draft"])
@pytest.mark.parametrize(
    ("to", "subject", "body", "refused"),
    [
        ("partner@gmail.com", "CUI//SP-PROPIN Quote", "price list", True),
        ("partner@gmail.com", "Quote", "(CUI) price list", True),
        ("a@example.com", "CUI//SP-PROPIN Quote", "price list", False),
        ("partner@gmail.com", "Lunch", "we discussed CUI rules", False),
    ],
)
@pytest.mark.anyio
async def test_cui_marked_mail_stays_inside_the_allowed_domains(
    cui_book: MailboxBook,
    audit: AuditLog,
    mail_server: FakeMailServer,
    tool: str,
    to: str,
    subject: str,
    body: str,
    refused: bool,
) -> None:
    arguments: dict[str, object] = {"mailbox": "work", "to": to, "subject": subject, "body": body}
    if tool == "create_draft":
        arguments["folder"] = "Drafts"
    async with Client(build_server(cui_book, audit)) as client:
        result: CallToolResult = await client.call_tool(tool, arguments)
    assert result.is_error is refused
    went_out: bool = bool(mail_server.sent) or bool(mail_server.folders["Drafts"])
    assert went_out is not refused
    if refused:
        assert "CUI markings" in audit.path.read_text(encoding="utf-8")
