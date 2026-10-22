"""Build outbound MIME messages.

Shared by the draft tools and the send tool so a draft and a sent message are
composed by exactly one piece of code.
"""

from __future__ import annotations

from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid

from email_tool_mcp.attachments import Attachment, attach


def compose(
    sender: str, to: str, subject: str, body: str, cc: str, html: str, attachments: Sequence[Attachment] = ()
) -> EmailMessage:
    """Build a message from `sender`; with `html` it becomes multipart/alternative, with attachments multipart/mixed.

    multipart/alternative makes mail clients show the HTML part and open a saved
    draft in rich-text mode, with `body` as the plain-text fallback.
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
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    attach(message, attachments)
    return message


def envelope_recipients(message: EmailMessage) -> list[str]:
    """Return every address the message must actually be delivered to."""
    pairs: list[tuple[str, str]] = getaddresses(message.get_all("To", []) + message.get_all("Cc", []))
    return [address for _, address in pairs if address]
