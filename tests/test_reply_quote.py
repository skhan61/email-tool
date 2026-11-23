"""A reply quotes the message it answers below the new text (#154).

Standard: pytest, parents built with the standard library's email package.
Placement: tests/test_reply_quote.py, beside src/email_tool_mcp/reply_quote.py (pytest's tests/ layout).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from email import message_from_bytes
from email.message import EmailMessage, Message, MIMEPart

import pytest

from email_tool_mcp.message_compose import compose
from email_tool_mcp.reply_quote import attribution, quote_lines

HEAD: str = "Message-ID: <p@x.com>\r\nFrom: Jane Doe <jane@x.com>\r\nDate: Sat, 21 Nov 2026 03:09:15 -0500\r\n"
# The attribution is in this computer's time zone, so exact times are checked only where the zone can be set.
NEEDS_TZSET: pytest.MarkDecorator = pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX only")
ATTRIBUTION: re.Pattern[str] = re.compile(r"On \w{3}, \w{3} \d+, 2026 at \d+:\d\d [AP]M, Jane Doe <jane@x\.com> wrote:")


def parent_from(raw: str) -> Message:
    return message_from_bytes((HEAD + raw).encode())


def plain_parent(text: str) -> Message:
    return parent_from(f"Subject: Plan\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{text}")


def text_part(message: EmailMessage, subtype: str) -> str:
    part: MIMEPart | None = message.get_body(preferencelist=(subtype,))
    assert part is not None
    return str(part.get_content())


@pytest.fixture
def new_york(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield None
    monkeypatch.undo()
    time.tzset()


def test_a_plain_parent_is_quoted_below_the_reply() -> None:
    reply: EmailMessage = compose(
        "me@x.com", "jane@x.com", "Re: Plan", "Yes.", "", "", parent=plain_parent("Thoughts?\r\n"), quote=True
    )
    head: str
    quote: str
    head, quote = text_part(reply, "plain").split("\n\n", 1)
    assert head == "Yes."
    assert ATTRIBUTION.fullmatch(quote.splitlines()[0])
    assert quote.splitlines()[1:] == ["> Thoughts?"]


def test_the_parents_own_quoted_history_is_carried() -> None:
    parent: Message = plain_parent("Fine.\r\n\r\nOn Fri, Bob wrote:\r\n> First?\r\n")
    reply: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Thanks.", "", "", parent=parent, quote=True)
    assert "> Fine.\n>\n> On Fri, Bob wrote:\n>> First?" in text_part(reply, "plain")


def test_an_html_only_parent_is_quoted_as_its_text() -> None:
    parent: Message = parent_from(
        "Subject: Plan\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Meet <b>Monday</b>?</p><script>x()</script>"
    )
    reply: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Yes.", "", "", parent=parent, quote=True)
    plain: str = text_part(reply, "plain")
    assert "> Meet Monday?" in plain and "x()" not in plain


def test_a_multipart_parent_is_quoted_in_both_parts_and_its_html_never_copied() -> None:
    parent_message: EmailMessage = compose(
        "jane@x.com", "me@x.com", "Plan", "See <b>this</b>", "", "<p>See <img src=t></p>"
    )
    parent_message.replace_header("Message-ID", "<p@x.com>")
    parent: Message = message_from_bytes(parent_message.as_bytes())
    reply: EmailMessage = compose(
        "me@x.com", "jane@x.com", "Re", "Done.", "", "<html><body><p>Done.</p></body></html>", parent=parent, quote=True
    )
    assert "> See <b>this</b>" in text_part(reply, "plain")
    markup: str = text_part(reply, "html")
    assert '<blockquote type="cite"' in markup and "See &lt;b&gt;this&lt;/b&gt;" in markup
    assert "<img" not in markup
    assert markup.index("</blockquote>") < markup.index("</body>")


def test_a_parent_with_no_text_part_adds_no_quote() -> None:
    parent: Message = parent_from(
        "Subject: Scan\r\nContent-Type: application/pdf\r\n"
        "Content-Disposition: attachment; filename=a.pdf\r\n\r\nJVBE\r\n"
    )
    reply: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Got it.", "", "", parent=parent, quote=True)
    assert text_part(reply, "plain") == "Got it.\n"


def test_quoting_can_be_turned_off() -> None:
    reply: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Yes.", "", "", parent=plain_parent("Thoughts?\r\n"))
    assert text_part(reply, "plain") == "Yes.\n"
    assert reply["In-Reply-To"] == "<p@x.com>"


def test_an_edited_reply_draft_keeps_one_quote() -> None:
    """A draft read back with get_draft and passed to update_draft already holds its quote."""
    parent: Message = plain_parent("Thoughts?\r\n")
    first: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Yes.", "", "<p>Yes.</p>", parent=parent, quote=True)
    edited_plain: str = text_part(first, "plain").replace("Yes.", "Yes, Monday.")
    edited_html: str = text_part(first, "html").replace("Yes.", "Yes, Monday.")
    second: EmailMessage = compose(
        "me@x.com", "jane@x.com", "Re", edited_plain, "", edited_html, parent=parent, quote=True
    )
    assert text_part(second, "plain").count("> Thoughts?") == 1
    assert text_part(second, "html").count("<blockquote") == 1


def test_a_sender_in_an_unknown_charset_still_quotes() -> None:
    parent: Message = message_from_bytes(
        b"Message-ID: <p@x.com>\r\nFrom: =?x-unknown?B?SmFuZQ==?= <j@x.com>\r\n\r\nHello\r\n"
    )
    reply: EmailMessage = compose("me@x.com", "j@x.com", "Re", "Hi.", "", "", parent=parent, quote=True)
    assert "<j@x.com> wrote:\n> Hello" in text_part(reply, "plain")


def test_an_html_only_reply_starts_with_the_quote_and_keeps_line_breaks() -> None:
    reply: EmailMessage = compose(
        "me@x.com", "jane@x.com", "Re", "", "", "<p>Hi</p>", parent=plain_parent("a\r\n  b\r\n"), quote=True
    )
    assert ATTRIBUTION.match(text_part(reply, "plain"))
    markup: str = text_part(reply, "html")
    assert "a<br>  b</blockquote>" in markup and "\r" not in markup and "pre-wrap" in markup


@NEEDS_TZSET
@pytest.mark.usefixtures("new_york")
@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ("Sat, 21 Nov 2026 15:09:15 -0500", "On Sat, Nov 21, 2026 at 3:09 PM, Jane Doe <jane@x.com> wrote:"),
        ("Sat, 21 Nov 2026 12:09:15 -0800", "On Sat, Nov 21, 2026 at 3:09 PM, Jane Doe <jane@x.com> wrote:"),
        ("not a date", "On not a date, Jane Doe <jane@x.com> wrote:"),
    ],
)
def test_the_attribution_names_the_sender_and_the_time_here(date: str, expected: str) -> None:
    parent: Message = message_from_bytes(f"From: Jane Doe <jane@x.com>\r\nDate: {date}\r\n\r\nx".encode())
    assert attribution(parent) == expected


def test_quote_lines_nests_an_existing_quote_without_a_space() -> None:
    assert quote_lines("a\n> b\n\nc") == "> a\n>> b\n>\n> c"
