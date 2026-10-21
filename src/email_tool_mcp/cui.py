"""Find Controlled Unclassified Information markings in an outgoing message (NIST SP 800-171 3.1.3).

Standard: the marking formats of DoD Instruction 5200.48 and the NARA CUI Marking
Handbook: a banner line that is only `CUI` or `CONTROLLED` (optionally with
`//` category or dissemination parts, e.g. `CUI//SP-PROPIN//NOFORN`), portion
markings such as `(CUI)` or `(CUI//SP-EXPT)`, and a subject that starts with a banner.
Placement: cui.py; MailboxBook checks every message it sends or saves as a draft.

A sentence that only mentions CUI ("we discussed CUI rules") is not a marking, and
neither is any lowercase or embedded use ("cuisine", "cui bono").
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from typing import Final

from email_tool_mcp.message_render import every_text

_PARTS: Final[str] = r"(?://[A-Z0-9][A-Z0-9 ,-]*)*"
BANNER: Final[re.Pattern[str]] = re.compile(rf"^[ \t]*(?:CUI|CONTROLLED){_PARTS}[ \t]*$", re.MULTILINE)
PORTION: Final[re.Pattern[str]] = re.compile(rf"\(CUI{_PARTS}\)")
SUBJECT_BANNER: Final[re.Pattern[str]] = re.compile(rf"^\s*(?:CUI|CONTROLLED){_PARTS}(?:\s|:|-|$)")


def markings(subject: str, body: str) -> list[str]:
    """Return every CUI marking found, in the order: subject, banners, portions."""
    found: list[str] = []
    subject_match: re.Match[str] | None = SUBJECT_BANNER.match(subject)
    if subject_match is not None:
        found.append(f"subject: {subject_match.group(0).strip(' :-')}")
    found.extend(f"banner: {match.group(0).strip()}" for match in BANNER.finditer(body))
    found.extend(f"portion: {match.group(0)}" for match in PORTION.finditer(body))
    return found


def message_markings(message: EmailMessage) -> list[str]:
    """CUI markings in a composed message's subject and every text part (plain, HTML, text attachments)."""
    return markings(str(message.get("Subject", "")), every_text(message))
