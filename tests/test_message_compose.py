"""`compose` builds plain or multipart messages; `envelope_recipients` covers To and Cc."""

from __future__ import annotations

from email.message import EmailMessage

from email_tool_mcp.message_compose import compose, envelope_recipients


def test_plain_body_stays_text_plain() -> None:
    message: EmailMessage = compose("me@example.com", "a@example.com", "Hi", "hello", "", "")
    assert message.get_content_type() == "text/plain"


def test_html_body_makes_multipart_alternative() -> None:
    message: EmailMessage = compose(
        "me@example.com", "a@example.com", "", "see link", "", '<a href="https://example.com">link</a>'
    )
    assert message.get_content_type() == "multipart/alternative"
    subtypes: list[str] = [part.get_content_type() for part in message.iter_parts()]
    assert subtypes == ["text/plain", "text/html"]


def test_envelope_includes_cc() -> None:
    message: EmailMessage = compose("me@example.com", "a@example.com, b@example.com", "", "", "c@example.com", "")
    assert envelope_recipients(message) == ["a@example.com", "b@example.com", "c@example.com"]


def test_envelope_keeps_a_quoted_comma_in_a_display_name() -> None:
    message: EmailMessage = compose("me@example.com", '"Doe, Jane" <jane@example.com>', "", "", "", "")
    assert envelope_recipients(message) == ["jane@example.com"]
