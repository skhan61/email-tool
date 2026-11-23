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
_NAME_KEY: Final[bytes] = b"name"
_MESSAGE: Final[bytes] = b"message"
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


def _is_attachment(part: BodyData) -> bool:
    """The rule `extract_body` uses (`get_filename()` plus an attachment disposition), read from BODYSTRUCTURE.

    A Content-Disposition of attachment or with a filename, or a Content-Type `name`, makes a part a file.
    Only text leaves reach here, so the disposition is at index 9 (after body lines and md5).
    """
    params: Any = part[_PARAMS_INDEX] or ()
    if any(isinstance(key, bytes) and key.lower() == _NAME_KEY for key in params[::2]):
        return True
    disposition: Any = part[_TEXT_DISPOSITION_INDEX] if len(part) > _TEXT_DISPOSITION_INDEX else None
    if not disposition:
        return False
    disposition_params: Any = disposition[1] or ()
    named: bool = any(
        isinstance(key, bytes) and key.lower().startswith(_FILE_NAME_KEY) for key in disposition_params[::2]
    )
    return disposition[0].lower() == _ATTACHMENT or named


def _text_leaves(structure: BodyData, prefix: str) -> list[tuple[str, BodyData]] | None:
    """Every text/* leaf with its IMAP section number, in message order, attachments left out.

    None when the message holds another message (message/rfc822): its text sits under that part's own
    numbering, so the caller reads the whole message instead.
    """
    if structure.is_multipart:
        found: list[tuple[str, BodyData]] = []
        for number, child in enumerate(structure[0], start=1):
            inner: list[tuple[str, BodyData]] | None = _text_leaves(
                child, f"{prefix}.{number}" if prefix else str(number)
            )
            if inner is None:
                return None
            found.extend(inner)
        return found
    if structure[0].lower() == _MESSAGE:
        return None
    if structure[0].lower() != _TEXT or _is_attachment(structure):
        return []
    return [(prefix or "1", structure)]


def text_leaves(structure: BodyData) -> list[tuple[str, BodyData]] | None:
    """The leaves to fetch with their sections: the text/plain parts, or the text/html parts when none is plain.

    None when only the whole message can be read correctly (see _text_leaves).
    """
    leaves: list[tuple[str, BodyData]] | None = _text_leaves(structure, "")
    if leaves is None:
        return None
    for subtype in (_PLAIN, _HTML):
        chosen: list[tuple[str, BodyData]] = [pair for pair in leaves if pair[1][1].lower() == subtype]
        if chosen:
            return chosen
    return []


def complete_header(mime: object) -> bool:
    """True for a part's MIME header block as RFC 3501 serves it: bytes ending in a blank line."""
    return isinstance(mime, bytes) and (mime.endswith(b"\r\n\r\n") or mime.endswith(b"\n\n"))
