"""Find Controlled Unclassified Information markings in an outgoing message (NIST SP 800-171 3.1.3).

Standard: the marking formats of DoD Instruction 5200.48 and the NARA CUI Marking
Handbook: a banner line that is only `CUI` or `CONTROLLED`, optionally followed by
category and dissemination parts (`CUI//SP-CTI/SP-EXPT//NOFORN`: `//` between
groups, `/` within one); portion markings such as `(CUI)` or `(CUI//SP-EXPT)`;
and a subject carrying a banner, also after `Re:`/`Fwd:` prefixes.
Placement: cui.py; MailboxBook checks every message it sends or saves as a draft.

Text is normalised first (Unicode NFKC, zero-width characters and Markdown
emphasis removed), and HTML is also read with a line break at every tag, so a
banner in `<span>` or `**CUI**` is still a banner. A sentence that only mentions
CUI ("CUI training next week", "we discussed CUI rules") is not a marking, and
neither is lowercase or embedded use ("cuisine", "cui bono").
"""

from __future__ import annotations

import re
import unicodedata
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Final

from email_tool_mcp.attachments import attachment_text
from email_tool_mcp.message_render import every_text

# One or more category groups: `//` between groups, `/` inside one, optional spaces.
_PARTS: Final[str] = r"(?:[ \t]*/{1,2}[ \t]*[A-Z0-9][A-Z0-9,-]*(?:[ \t]+[A-Z0-9][A-Z0-9,-]*)*)*"
_TOKEN: Final[str] = r"(?:CUI|CONTROLLED)"
BANNER: Final[re.Pattern[str]] = re.compile(rf"^[ \t]*{_TOKEN}{_PARTS}[ \t]*$", re.MULTILINE)
PORTION: Final[re.Pattern[str]] = re.compile(rf"\({_TOKEN}{_PARTS}\)")
_REPLY_PREFIX: Final[re.Pattern[str]] = re.compile(r"^(?:\s*(?:re|fwd?|aw|wg|sv|tr)\s*:\s*)*", re.IGNORECASE)
# A subject banner: the token with categories, alone, or before a separator; never a word in a sentence.
_CATEGORIES: Final[str] = r"(?:[ \t]*/{1,2}[ \t]*[A-Z0-9][A-Z0-9,-]*)+"
_ALONE_OR_SEPARATED: Final[str] = r"(?=\s*$|\s*[:|]|\s+-\s)"
SUBJECT_BANNER: Final[re.Pattern[str]] = re.compile(rf"^{_TOKEN}(?:{_CATEGORIES}|{_ALONE_OR_SEPARATED})")
_INVISIBLE: Final[re.Pattern[str]] = re.compile("[\u200b-\u200d\u2060\ufeff\u00ad]")
_EMPHASIS: Final[re.Pattern[str]] = re.compile(r"[*_~`]+")


def normalise(text: str) -> str:
    """Fold look-alike and invisible characters so they cannot hide a marking."""
    folded: str = unicodedata.normalize("NFKC", text)
    return _EMPHASIS.sub("", _INVISIBLE.sub("", folded))


class _TagLines(HTMLParser):
    """HTML text with a line break at every tag, so an inline banner stands on its own line."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._hidden: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._hidden += tag in ("script", "style")
        self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._hidden:
            self._hidden -= 1
        self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.chunks.append(data)


def tag_lines(html: str) -> str:
    """`html` as text, one line per run between tags."""
    parser: _TagLines = _TagLines()
    parser.feed(html)
    return "".join(parser.chunks)


def markings(subject: str, body: str) -> list[str]:
    """Every CUI marking found: subject first, then banner lines, then portion marks."""
    found: list[str] = []
    clean_subject: str = _REPLY_PREFIX.sub("", normalise(subject)).strip()
    subject_match: re.Match[str] | None = SUBJECT_BANNER.match(clean_subject)
    if subject_match is not None:
        found.append(f"subject: {clean_subject}")
    found.extend(f"subject: {match.group(0)}" for match in PORTION.finditer(clean_subject))
    text: str = normalise(body)
    found.extend(f"banner: {match.group(0).strip()}" for match in BANNER.finditer(text))
    found.extend(f"portion: {match.group(0)}" for match in PORTION.finditer(text))
    return found


def message_markings(message: EmailMessage) -> list[str]:
    """CUI markings in the subject, every text part and every readable attachment (text, Word, PDF).

    HTML is read both as rendered text and tag by tag.
    """
    html_parts: list[str] = [part.get_content() for part in message.walk() if part.get_content_type() == "text/html"]
    attached: list[str] = [
        attachment_text(part)
        for part in message.walk()
        if part.get_filename() and part.get_content_type() not in ("text/plain", "text/html")
    ]
    body: str = "\n".join([every_text(message), *(tag_lines(html) for html in html_parts), *attached])
    return list(dict.fromkeys(markings(str(message.get("Subject", "")), body)))
