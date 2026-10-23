"""Fuzz incoming-message parsing (body, attachments, reply headers) and the CUI check on send.

Standard: Atheris (`Setup`, `Fuzz`), libFuzzer's coverage-guided engine for Python.
Placement: fuzz/, one target per file, run by .github/workflows/fuzz.yml.

Incoming mail is parsed as the read tools parse it (`parse_message`, the classic parser), and
every attached part is read as the CUI check reads it. The same bytes, as text, then become an
outgoing message's subject, body and HTML, which an incoming email can steer, and go through
`message_markings`. Nothing here may raise, except `thread_headers`, which refuses a parent
without a Message-ID with ValueError by design.
"""

from __future__ import annotations

from email.message import EmailMessage, Message

from email_tool_mcp.attachments import attachment_text
from email_tool_mcp.cui import message_markings
from email_tool_mcp.message_compose import compose, message_ids, thread_headers
from email_tool_mcp.message_render import attachment_names, every_text, extract_body, header_block, parse_message
from fuzz._run import run


def test_one_input(data: bytes) -> None:
    """Read `data` as incoming mail, then check it as outgoing text."""
    incoming: Message = parse_message(data)
    extract_body(incoming)
    every_text(incoming)
    header_block(incoming)
    attachment_names(incoming)
    part: Message
    for part in incoming.walk():
        if part.get_filename():
            attachment_text(part)
    message_ids(incoming.get("References"))
    try:
        thread_headers(incoming)
    except ValueError:
        pass
    text: str = data.decode("utf-8", "replace")
    subject: str = " ".join(text[:200].split())
    outgoing: EmailMessage = compose("me@example.com", "you@example.com", subject, text, "", text)
    message_markings(outgoing)


if __name__ == "__main__":
    run(test_one_input)
