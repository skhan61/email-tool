"""Quote the message being answered below a reply, as mail clients do.

Standard: the attribution line plus `>`-prefixed lines of RFC 3676 section 4.5 for the plain part,
and a `<blockquote type="cite">` (the form Thunderbird and Apple Mail write) for the HTML part.
Placement: reply_quote.py, used only by message_compose.compose, so a draft, a sent reply and the
approval prompt all carry the same quote.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Final

from email_tool_mcp.message_render import decode_header_value, extract_body

_BODY_END: Final[re.Pattern[str]] = re.compile(r"</body\s*>", re.IGNORECASE)
_QUOTE_STYLE: Final[str] = "margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex"


def attribution(parent: Message) -> str:
    """'On Sat, Nov 21, 2026 at 3:09 AM, Jane <jane@x.com> wrote:', with the raw date when it does not parse."""
    sender: str = decode_header_value(parent.get("From")) or "someone"
    raw_date: str = decode_header_value(parent.get("Date"))
    when: str = raw_date
    try:
        sent: datetime = parsedate_to_datetime(raw_date)
        hour: int = sent.hour % 12 or 12
        when = f"{sent:%a, %b} {sent.day}, {sent.year} at {hour}:{sent:%M} {'AM' if sent.hour < 12 else 'PM'}"
    except (TypeError, ValueError, IndexError):
        pass
    return f"On {when}, {sender} wrote:" if when else f"{sender} wrote:"


def quote_lines(text: str) -> str:
    """Each line prefixed with '>', and a space before text that is not itself a quote (RFC 3676 4.5)."""
    lines: list[str] = text.splitlines() or [""]
    return "\n".join(">" + line if line.startswith(">") else ("> " + line if line else ">") for line in lines)


def quoted_plain(body: str, parent: Message) -> str:
    """`body`, a blank line, the attribution and the parent's text quoted; `body` alone when the parent has no text."""
    earlier: str = extract_body(parent).strip("\n")
    if not earlier.strip():
        return body
    return f"{body.rstrip()}\n\n{attribution(parent)}\n{quote_lines(earlier)}\n"


def quoted_html(markup: str, parent: Message) -> str:
    """`markup` with the attribution and the parent's text in a cited blockquote, before `</body>` when there is one.

    The parent's text is escaped, never its own HTML: that came from someone else and could carry
    scripts, styles or tracking images into a message this mailbox sends.
    """
    earlier: str = extract_body(parent).strip("\n")
    if not earlier.strip():
        return markup
    block: str = (
        f"<br><div>{html.escape(attribution(parent))}</div>"
        f'<blockquote type="cite" style="{_QUOTE_STYLE}">'
        f"{html.escape(earlier).replace(chr(10), '<br>')}</blockquote>"
    )
    ends: list[re.Match[str]] = list(_BODY_END.finditer(markup))
    if not ends:
        return markup + block
    cut: int = ends[-1].start()
    return markup[:cut] + block + markup[cut:]
