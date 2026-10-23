"""Build outbound MIME messages.

Shared by the draft tools and the send tool so a draft and a sent message are
composed by exactly one piece of code.
"""

from __future__ import annotations

import re
from email.message import EmailMessage, Message
from email.utils import formatdate, getaddresses, make_msgid
from typing import Final

# One message ID in its angle-bracket form (RFC 5322 section 3.6.4); nothing else of a header is copied.
_MESSAGE_ID: Final[re.Pattern[str]] = re.compile(r"<[^<>\s()]+>")
# An RFC 5322 comment with nothing nested inside; removed innermost first.
_COMMENT: Final[re.Pattern[str]] = re.compile(r"\([^()]*\)")
# A long thread keeps its first ID and the newest ones, as RFC 5322 allows trimming References.
_REFERENCES_KEPT: Final[int] = 20
_THREAD_FIELDS: Final[tuple[str, ...]] = ("In-Reply-To", "References")


def message_ids(value: object) -> list[str]:
    """The well-formed `<...>` IDs in a header value, outside comments, each once, in order.

    The value came from someone else's mail, so a line break, a comment or any other
    text in it never reaches an outgoing message.
    """
    text: str = str(value or "")
    stripped: str = _COMMENT.sub(" ", text)
    while stripped != text:
        text, stripped = stripped, _COMMENT.sub(" ", stripped)
    if "(" in text or ")" in text:
        # An unbalanced comment: nothing after its opening bracket can be trusted.
        text = text.split("(", 1)[0]
    return list(dict.fromkeys(_MESSAGE_ID.findall(text)))


def thread_headers(parent: Message) -> tuple[str, str]:
    """Return In-Reply-To and References for a reply to `parent` (RFC 5322 section 3.6.4)."""
    own: list[str] = message_ids(parent.get("Message-ID"))
    if not own:
        raise ValueError(
            "the message being answered has no Message-ID, so a reply cannot join its thread; "
            "leave in_reply_to_uid out to send it as a new conversation"
        )
    chain: list[str] = message_ids(parent.get("References"))
    if not chain:
        # In-Reply-To stands in for References only when it names a single parent.
        parents: list[str] = message_ids(parent.get("In-Reply-To"))
        chain = parents if len(parents) == 1 else []
    chain = [identifier for identifier in chain if identifier != own[0]] + [own[0]]
    if len(chain) > _REFERENCES_KEPT:
        chain = chain[:1] + chain[1 - _REFERENCES_KEPT :]
    return own[0], " ".join(chain)


def keep_thread(message: EmailMessage, previous: Message) -> None:
    """Give `message` the thread headers of `previous`, the draft it replaces, when it has none of its own."""
    field: str
    for field in _THREAD_FIELDS:
        identifiers: list[str] = message_ids(previous.get(field))
        if identifiers and field not in message:
            message[field] = " ".join(identifiers)


def compose(
    sender: str, to: str, subject: str, body: str, cc: str, html: str, parent: Message | None = None
) -> EmailMessage:
    """Build a message from `sender`; with `html` it becomes multipart/alternative.

    multipart/alternative makes mail clients show the HTML part and open a saved
    draft in rich-text mode, with `body` as the plain-text fallback. With `parent`
    the message is a reply and joins that message's conversation.
    """
    message: EmailMessage = EmailMessage()
    message["From"] = sender
    header: str
    value: str
    for header, value in (("To", to), ("Cc", cc)):
        if not value and header == "Cc":
            continue
        try:
            message[header] = value
        except IndexError as error:
            # Python 3.11/3.12's header parser crashes on a lone quote (`"`); 3.13 fixed it.
            raise ValueError(f"{header.lower()} is not a valid address list: {value!r}") from error
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    # The sender's own domain: the default looks up this machine's network name (a
    # reverse DNS call that can hang) and would leak the internal hostname to recipients.
    message["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or "localhost")
    if parent is not None:
        in_reply_to: str
        references: str
        in_reply_to, references = thread_headers(parent)
        message["In-Reply-To"] = in_reply_to
        message["References"] = references
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def envelope_recipients(message: EmailMessage) -> list[str]:
    """Return every address the message must actually be delivered to."""
    pairs: list[tuple[str, str]] = getaddresses(message.get_all("To", []) + message.get_all("Cc", []))
    return [address for _, address in pairs if address]
