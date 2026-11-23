"""Pick the text parts of a message from its BODYSTRUCTURE, so a quote never downloads an attachment.

Standard: RFC 3501 section 7.4.2 (BODYSTRUCTURE) and section 6.4.5 (part numbers), parsed by imapclient's BodyData.
Placement: src/email_tool_mcp/text_parts.py, between imap_session.py (fetches) and message_render.py (reads).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from imapclient.response_types import BodyData

_TEXT: Final[bytes] = b"text"
_PLAIN: Final[bytes] = b"plain"
_HTML: Final[bytes] = b"html"
_ATTACHMENT: Final[bytes] = b"attachment"
_FILE_NAME_KEYS: Final[tuple[bytes, ...]] = (b"filename", b"name")
_PARAMS_INDEX: Final[int] = 2
_TEXT_DISPOSITION_INDEX: Final[int] = 9


@dataclass(frozen=True)
class TextPart:
    """One fetched part: its MIME header block (ending in a blank line) and its body as sent."""

    mime: bytes
    content: bytes


@dataclass(frozen=True)
class TextParts:
    """A message's own headers and only its readable text parts."""

    headers: bytes
    parts: tuple[TextPart, ...]


def _names_a_file(params: Any) -> bool:
    """True when a parameter list (flat key, value pairs, or None) carries a file name."""
    if not params:
        return False
    return any(isinstance(key, bytes) and key.lower().startswith(_FILE_NAME_KEYS) for key in params[::2])


def _is_attachment(part: BodyData) -> bool:
    disposition: Any = part[_TEXT_DISPOSITION_INDEX] if len(part) > _TEXT_DISPOSITION_INDEX else None
    if disposition and disposition[0].lower() == _ATTACHMENT:
        return True
    return _names_a_file(part[_PARAMS_INDEX]) or (bool(disposition) and _names_a_file(disposition[1]))


def _text_leaves(structure: BodyData, prefix: str) -> list[tuple[str, BodyData]]:
    """Every text/* leaf with its IMAP section number, in message order, attachments left out."""
    if structure.is_multipart:
        found: list[tuple[str, BodyData]] = []
        for number, child in enumerate(structure[0], start=1):
            found.extend(_text_leaves(child, f"{prefix}.{number}" if prefix else str(number)))
        return found
    if structure[0].lower() != _TEXT or _is_attachment(structure):
        return []
    return [(prefix or "1", structure)]


def text_sections(structure: BodyData) -> list[str]:
    """The sections to fetch: the text/plain parts, or the text/html parts when there is no plain one."""
    leaves: list[tuple[str, BodyData]] = _text_leaves(structure, "")
    for subtype in (_PLAIN, _HTML):
        chosen: list[str] = [section for section, leaf in leaves if leaf[1].lower() == subtype]
        if chosen:
            return chosen
    return []
