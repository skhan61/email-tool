"""`compose` builds plain or multipart messages; `envelope_recipients` covers To and Cc."""

from email.message import EmailMessage

from message_compose import compose, envelope_recipients


def test_plain_body_stays_text_plain() -> None:
    message: EmailMessage = compose("me@example.com", {"to": "a@example.com", "subject": "Hi", "body": "hello"})
    assert message.get_content_type() == "text/plain"


def test_html_body_makes_multipart_alternative() -> None:
    message: EmailMessage = compose(
        "me@example.com",
        {"to": "a@example.com", "body": "see link", "html": '<a href="https://example.com">link</a>'},
    )
    assert message.get_content_type() == "multipart/alternative"
    subtypes: list[str] = [part.get_content_type() for part in message.iter_parts()]
    assert subtypes == ["text/plain", "text/html"]


def test_envelope_includes_cc() -> None:
    message: EmailMessage = compose("me@example.com", {"to": "a@example.com, b@example.com", "cc": "c@example.com"})
    assert sorted(envelope_recipients(message)) == ["a@example.com", "b@example.com", "c@example.com"]
