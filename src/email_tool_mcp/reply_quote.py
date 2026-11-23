"""Quote the message being answered below a reply, as mail clients do.

Standard: the attribution line plus `>`-prefixed lines of RFC 3676 section 4.5 for the plain part,
and a `<blockquote type="cite">` (the form Thunderbird and Apple Mail write) for the HTML part.
Placement: reply_quote.py, used only by message_compose.compose, so a draft, a sent reply and the
approval prompt all carry the same quote.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Final

from email_tool_mcp.message_render import decode_header_value, extract_body

_BODY_END: Final[re.Pattern[str]] = re.compile(r"</body\s*>", re.IGNORECASE)
_HTML_END: Final[re.Pattern[str]] = re.compile(r"</html\s*>", re.IGNORECASE)
_QUOTE_STYLE: Final[str] = "margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex;white-space:pre-wrap"
# The quote block quoted_html writes, found again to take it out when a draft moves to another conversation.
_HTML_QUOTE: Final[re.Pattern[str]] = re.compile(
    r"<br><div>On [^<]*wrote:</div><blockquote type=\"cite\" style=\""
    + re.escape(_QUOTE_STYLE)
    + r"\">.*?</blockquote>",
    re.DOTALL,
)
# The plain quote quoted_plain writes: an attribution line, then only '>' lines to the end.
_PLAIN_QUOTE: Final[re.Pattern[str]] = re.compile(r"\n*^On .* wrote:\n(?:>.*(?:\n|$))+\Z", re.MULTILINE)
# English names, so the line reads the same whatever the computer's language.
_DAYS: Final[tuple[str, ...]] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS: Final[tuple[str, ...]] = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _header(parent: Message, field: str) -> str:
    """A header decoded, or as it came when its charset is unknown or its bytes are broken."""
    try:
        return decode_header_value(parent.get(field))
    except (LookupError, UnicodeError):
        return str(parent.get(field) or "")


def attribution(parent: Message) -> str:
    """'On Sat, Nov 21, 2026 at 3:09 AM, Jane <jane@x.com> wrote:', in this computer's time zone.

    The raw date is kept when it does not parse.
    """
    sender: str = _header(parent, "From") or "someone"
    raw_date: str = _header(parent, "Date")
    when: str = raw_date
    try:
        parsed: datetime = parsedate_to_datetime(raw_date)
        # A date with no zone ('-0000' or none) is UTC, not this computer's time.
        sent: datetime = (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone()
        hour: int = sent.hour % 12 or 12
        day: str = f"{_DAYS[sent.weekday()]}, {_MONTHS[sent.month - 1]} {sent.day}, {sent.year}"
        when = f"{day} at {hour}:{sent.minute:02d} {'AM' if sent.hour < 12 else 'PM'}"
    except (TypeError, ValueError, IndexError):
        pass
    return f"On {when}, {sender} wrote:" if when else f"{sender} wrote:"


def quote_lines(text: str) -> str:
    """Each line prefixed with '>', and a space before text that is not itself a quote (RFC 3676 4.5)."""
    lines: list[str] = text.splitlines() or [""]
    return "\n".join(">" + line if line.startswith(">") else ("> " + line if line else ">") for line in lines)


def _earlier(parent: Message) -> str:
    """The parent's text with its line endings made '\n' and blank lines trimmed from both ends."""
    return "\n".join(extract_body(parent).splitlines()).strip("\n")


def _html_lines(earlier: str) -> str:
    return "<br>".join(html.escape(line) for line in earlier.splitlines())


def without_quote(body: str) -> str:
    """`body` without a quote quoted_plain wrote at its end, for a draft moving to another conversation."""
    return _PLAIN_QUOTE.sub("", "\n".join(body.splitlines())).rstrip("\n") + ("\n" if body.endswith("\n") else "")


def without_quote_html(markup: str) -> str:
    """`markup` without the quote block quoted_html wrote."""
    return _HTML_QUOTE.sub("", markup)


def quoted_plain(body: str, parent: Message) -> str:
    """`body`, a blank line, the attribution and the parent's text quoted.

    `body` alone when the parent has no text. Call it on a body without a quote (see without_quote).
    """
    earlier: str = _earlier(parent)
    if not earlier.strip():
        return body
    lead: str = f"{body.rstrip()}\n\n" if body.strip() else ""
    return f"{lead}{attribution(parent)}\n{quote_lines(earlier)}\n"


def quoted_html(markup: str, parent: Message) -> str:
    """`markup` with the attribution and the parent's text in a cited blockquote, before `</body>` when there is one.

    The parent's text is escaped, never its own HTML: that came from someone else and could carry
    scripts, styles or tracking images into a message this mailbox sends.
    """
    earlier: str = _earlier(parent)
    lines: str = _html_lines(earlier)
    if not earlier.strip():
        return markup
    block: str = (
        f"<br><div>{html.escape(attribution(parent))}</div>"
        f'<blockquote type="cite" style="{_QUOTE_STYLE}">{lines}</blockquote>'
    )
    ends: list[re.Match[str]] = list(_BODY_END.finditer(markup)) or list(_HTML_END.finditer(markup))
    if not ends:
        return markup + block
    cut: int = ends[-1].start()
    return markup[:cut] + block + markup[cut:]
