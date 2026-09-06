"""Build outbound MIME messages.

Shared by the draft tools and the send tool so a draft and a sent message are
composed by exactly one piece of code.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any


def compose(sender: str, arguments: dict[str, Any]) -> EmailMessage:
    """Build an EmailMessage from `sender` and the tool `arguments`.

    Recognises the keys `to`, `cc`, `subject` and `body`. `to` is required.
    """
    recipients: str = arguments["to"]
    message: EmailMessage = EmailMessage()
    message["From"] = sender
    message["To"] = recipients
    carbon_copy: str | None = arguments.get("cc")
    if carbon_copy:
        message["Cc"] = carbon_copy
    message["Subject"] = arguments.get("subject", "")
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(arguments.get("body", ""))
    return message


def envelope_recipients(message: EmailMessage) -> list[str]:
    """Return every address the message must actually be delivered to."""
    addresses: list[str] = []
    for field in ("To", "Cc"):
        value: str | None = message.get(field)
        if not value:
            continue
        addresses.extend(part.strip() for part in value.split(",") if part.strip())
    return addresses
