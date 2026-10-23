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
_MESSAGE_ID: Final[re.Pattern[str]] = re.compile(r"<[^<>\s]+>")
# A long thread keeps its first ID and the newest ones, as RFC 5322 allows trimming References.
_REFERENCES_KEPT: Final[int] = 20


def thread_headers(parent: Message) -> tuple[str, str]:
    """Return In-Reply-To and References for a reply to `parent` (RFC 5322 section 3.6.4).

    `parent` came from someone else's mail, so only well-formed `<...>` IDs are taken from it:
    a line break or any other text in its headers never reaches the reply.
    """
    own: list[str] = _MESSAGE_ID.findall(str(parent.get("Message-ID", "")))
    if not own:
        raise ValueError("the message being answered has no Message-ID, so a reply cannot join its thread")
    chain: list[str] = _MESSAGE_ID.findall(str(parent.get("References", ""))) or _MESSAGE_ID.findall(
        str(parent.get("In-Reply-To", ""))
    )
    chain.append(own[0])
    if len(chain) > _REFERENCES_KEPT:
        chain = chain[:1] + chain[1 - _REFERENCES_KEPT :]
    return own[0], " ".join(chain)


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
