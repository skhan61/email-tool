"""Build outbound MIME messages.

Shared by the draft tools and the send tool so a draft and a sent message are
composed by exactly one piece of code.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid


def compose(sender: str, to: str, subject: str, body: str, cc: str, html: str) -> EmailMessage:
    """Build a message from `sender`; with `html` it becomes multipart/alternative.

    multipart/alternative makes mail clients show the HTML part and open a saved
    draft in rich-text mode, with `body` as the plain-text fallback.
    """
    fields: dict[str, str] = {"to": to, "cc": cc, "subject": subject, "body": body, "html": html}
    for name, value in fields.items():
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            # JSON can carry a lone surrogate (\ud800) that is not a character; refuse it by name.
            raise ValueError(f"{name} contains invalid text (a broken Unicode character); nothing composed") from error
    message: EmailMessage = EmailMessage()
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    # The sender's own domain: the default looks up this machine's network name (a
    # reverse DNS call that can hang) and would leak the internal hostname to recipients.
    message["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or "localhost")
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def envelope_recipients(message: EmailMessage) -> list[str]:
    """Return every address the message must actually be delivered to."""
    pairs: list[tuple[str, str]] = getaddresses(message.get_all("To", []) + message.get_all("Cc", []))
    return [address for _, address in pairs if address]
