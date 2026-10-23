"""Turn raw RFC-822 bytes into readable headers and plain text."""

from __future__ import annotations

import email
import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from email_tool_mcp.imap_session import ImapSession

_HEADER_FIELDS: Final[tuple[str, ...]] = ("Date", "From", "To", "Cc", "Subject")
_DROPPED_HTML_TAGS: Final[frozenset[str]] = frozenset({"script", "style", "head", "title"})
_BREAKING_HTML_TAGS: Final[frozenset[str]] = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3"})
_BLANK_RUN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class MessageSummary:
    """The header-only view of a message, used for listings."""

    uid: int
    date: str
    sender: str
    recipients: str
    subject: str

    def render(self) -> str:
        """Return a one-block textual summary."""
        return (
            f"[uid {self.uid}] {self.date}\n"
            f"  From:    {self.sender}\n"
            f"  To:      {self.recipients}\n"
            f"  Subject: {self.subject}"
        )


class _HtmlTextExtractor(HTMLParser):
    """Collect the visible text of an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._suppressed: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROPPED_HTML_TAGS:
            self._suppressed += 1
        elif tag in _BREAKING_HTML_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROPPED_HTML_TAGS and self._suppressed > 0:
            self._suppressed -= 1
        elif tag in _BREAKING_HTML_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._suppressed == 0:
            self._chunks.append(data)

    def text(self) -> str:
        """Return the collected text with runs of blank lines collapsed."""
        joined: str = "".join(self._chunks)
        lines: list[str] = [line.strip() for line in joined.splitlines()]
        return _BLANK_RUN.sub("\n\n", "\n".join(line for line in lines if line))


def decode_header_value(raw: str | None) -> str:
    """Decode an RFC-2047 encoded header into plain text."""
    if not raw:
        return ""
    return str(make_header(decode_header(raw)))


def parse_message(raw_bytes: bytes) -> Message:
    """Parse raw RFC-822 bytes into a Message."""
    return email.message_from_bytes(raw_bytes)


def read_headers(session: ImapSession, folder: str, uid: int) -> Message:
    """The parsed headers of message `uid` in `folder`, without marking it read; LookupError if absent."""
    session.select(folder, readonly=True)
    headers: dict[int, bytes] = session.fetch_headers([uid])
    if uid not in headers:
        raise LookupError(f"no message with uid {uid} in folder {folder!r}; nothing was done")
    return parse_message(headers[uid])


def summarize(uid: int, message: Message) -> MessageSummary:
    """Build a MessageSummary from a parsed message's headers."""
    return MessageSummary(
        uid=uid,
        date=decode_header_value(message.get("Date")),
        sender=decode_header_value(message.get("From")),
        recipients=decode_header_value(message.get("To")),
        subject=decode_header_value(message.get("Subject")),
    )


def header_block(message: Message) -> str:
    """Return the standard header fields as a printable block."""
    lines: list[str] = []
    for field in _HEADER_FIELDS:
        value: str = decode_header_value(message.get(field))
        if value:
            lines.append(f"{field}: {value}")
    return "\n".join(lines)


def _decode_part(part: Message) -> str:
    payload: object = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset: str = part.get_content_charset() or "utf-8"
    return payload.decode(charset, "replace")


def extract_body(message: Message) -> str:
    """Return the message body as plain text, converting HTML when needed."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        content_type: str = part.get_content_type()
        if content_type == "text/plain":
            plain_parts.append(_decode_part(part))
        elif content_type == "text/html":
            html_parts.append(_decode_part(part))

    if plain_parts:
        return "\n".join(chunk for chunk in plain_parts if chunk.strip())
    if html_parts:
        extractor: _HtmlTextExtractor = _HtmlTextExtractor()
        extractor.feed("\n".join(html_parts))
        return extractor.text()
    return ""


def every_text(message: Message) -> str:
    """All readable text: every plain part and every HTML part converted, attachments included."""
    chunks: list[str] = []
    for part in message.walk():
        content_type: str = part.get_content_type()
        if content_type == "text/plain":
            chunks.append(_decode_part(part))
        elif content_type == "text/html":
            extractor: _HtmlTextExtractor = _HtmlTextExtractor()
            extractor.feed(_decode_part(part))
            chunks.append(extractor.text())
    return "\n".join(chunks)


def attached_parts(message: Message) -> list[Message]:
    """Every attached part (a part with a file name), in message order: attachment 1, 2, ..."""
    return [part for part in message.walk() if part.get_filename()]


def attachment_names(message: Message) -> list[str]:
    """Return the filenames of every attached part."""
    return [decode_header_value(part.get_filename()) for part in attached_parts(message)]
