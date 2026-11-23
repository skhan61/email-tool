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
_FILE_NAME_KEY: Final[bytes] = b"filename"
_PARAMS_INDEX: Final[int] = 2
_ENCODING_INDEX: Final[int] = 5
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


def _is_attachment(part: BodyData) -> bool:
    """True when the Content-Disposition says attachment or names a file; a Content-Type name does not count."""
    disposition: Any = part[_TEXT_DISPOSITION_INDEX] if len(part) > _TEXT_DISPOSITION_INDEX else None
    if not disposition:
        return False
    params: Any = disposition[1]
    named: bool = bool(params) and any(
        isinstance(key, bytes) and key.lower().startswith(_FILE_NAME_KEY) for key in params[::2]
    )
    return disposition[0].lower() == _ATTACHMENT or named


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


def text_leaves(structure: BodyData) -> list[tuple[str, BodyData]]:
    """The leaves to fetch with their sections: the text/plain parts, or the text/html parts when none is plain."""
    leaves: list[tuple[str, BodyData]] = _text_leaves(structure, "")
    for subtype in (_PLAIN, _HTML):
        chosen: list[tuple[str, BodyData]] = [pair for pair in leaves if pair[1][1].lower() == subtype]
        if chosen:
            return chosen
    return []


def mime_header(leaf: BodyData) -> bytes:
    """A part's MIME header block rebuilt from its BODYSTRUCTURE, for a server that does not serve `.MIME`."""
    params: Any = leaf[_PARAMS_INDEX] or ()
    lines: list[str] = [
        f"Content-Type: {leaf[0].decode()}/{leaf[1].decode()}"
        + "".join(f'; {key.decode()}="{value.decode()}"' for key, value in zip(params[::2], params[1::2], strict=True)),
        f"Content-Transfer-Encoding: {leaf[_ENCODING_INDEX].decode()}",
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()
