"""A reply quotes the message it answers below the new text (#154).

Standard: pytest, parents built with the standard library's email package.
Placement: tests/test_reply_quote.py, beside src/email_tool_mcp/reply_quote.py (pytest's tests/ layout).
"""

from __future__ import annotations

from email import message_from_bytes
from email.message import EmailMessage, Message, MIMEPart

import pytest

from email_tool_mcp.message_compose import compose
from email_tool_mcp.reply_quote import attribution, quote_lines

HEAD: str = "Message-ID: <p@x.com>\r\nFrom: Jane Doe <jane@x.com>\r\nDate: Sat, 21 Nov 2026 03:09:15 -0500\r\n"


def parent_from(raw: str) -> Message:
    return message_from_bytes((HEAD + raw).encode())


def plain_parent(text: str) -> Message:
    return parent_from(f"Subject: Plan\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{text}")


def text_part(message: EmailMessage, subtype: str) -> str:
    part: MIMEPart | None = message.get_body(preferencelist=(subtype,))
    assert part is not None
    return str(part.get_content())


def test_a_plain_parent_is_quoted_below_the_reply() -> None:
    reply: EmailMessage = compose(
        "me@x.com", "jane@x.com", "Re: Plan", "Yes.", "", "", parent=plain_parent("Thoughts?\r\n"), quote=True
    )
    assert (
        text_part(reply, "plain")
        == "Yes.\n\nOn Sat, Nov 21, 2026 at 3:09 AM, Jane Doe <jane@x.com> wrote:\n> Thoughts?\n"
    )


def test_the_parents_own_quoted_history_is_carried() -> None:
    parent: Message = plain_parent("Fine.\r\n\r\nOn Fri, Bob wrote:\r\n> First?\r\n")
    reply: EmailMessage = compose("me@x.com", "jane@x.com", "Re", "Thanks.", "", "", parent=parent, quote=True)
    plain: str = text_part(reply, "plain")
    assert "> Fine.\n>\n> On Fri, Bob wrote:\n>> First?" in plain


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


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ("Sat, 21 Nov 2026 15:09:15 -0500", "On Sat, Nov 21, 2026 at 3:09 PM, Jane Doe <jane@x.com> wrote:"),
        ("not a date", "On not a date, Jane Doe <jane@x.com> wrote:"),
    ],
)
def test_the_attribution_names_the_sender_and_date(date: str, expected: str) -> None:
    parent: Message = message_from_bytes(f"From: Jane Doe <jane@x.com>\r\nDate: {date}\r\n\r\nx".encode())
    assert attribution(parent) == expected


def test_quote_lines_nests_an_existing_quote_without_a_space() -> None:
    assert quote_lines("a\n> b\n\nc") == "> a\n>> b\n>\n> c"
