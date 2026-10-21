"""Build outbound MIME messages.

Shared by the draft tools and the send tool so a draft and a sent message are
composed by exactly one piece of code.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from typing import Any, Final

COMPOSE_PROPERTIES: Final[dict[str, Any]] = {
    "to": {"type": "string", "description": "Comma-separated recipient addresses."},
    "cc": {"type": "string", "description": "Comma-separated Cc addresses."},
    "subject": {"type": "string", "description": "Subject line."},
    "body": {
        "type": "string",
        "description": "Plain text body. When `html` is also given, this is the plain-text fallback.",
    },
    "html": {
        "type": "string",
        "description": "Optional HTML body for links and formatting, sent as multipart/alternative with `body`.",
    },
}


def compose(sender: str, arguments: dict[str, Any]) -> EmailMessage:
    """Build an EmailMessage from `sender` and the tool `arguments`.

    Recognises the keys `to`, `cc`, `subject`, `body` and `html`. `to` is
    required. With `html`, the message becomes multipart/alternative so mail
    clients show the HTML part and open drafts in rich-text mode.
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
    html_body: str | None = arguments.get("html")
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


def envelope_recipients(message: EmailMessage) -> list[str]:
    """Return every address the message must actually be delivered to."""
    pairs: list[tuple[str, str]] = getaddresses(message.get_all("To", []) + message.get_all("Cc", []))
    return [address for _, address in pairs if address]
