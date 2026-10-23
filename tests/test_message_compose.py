"""`compose` builds plain or multipart messages; `envelope_recipients` covers To and Cc."""

from __future__ import annotations

import socket
from email import message_from_bytes
from email.message import EmailMessage, Message

import pytest

from email_tool_mcp.message_compose import compose, envelope_recipients, thread_headers


def parent_with(headers: str) -> Message:
    return message_from_bytes(f"{headers}Subject: Hello\r\n\r\nbody\r\n".encode())


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


def test_message_id_uses_the_sender_domain_and_never_looks_up_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_lookup(name: str = "") -> str:
        raise AssertionError("compose must not resolve this machine's network name")

    monkeypatch.setattr(socket, "getfqdn", no_lookup)
    message: EmailMessage = compose("me@example.com", "a@example.com", "Hi", "hello", "", "")
    assert str(message["Message-ID"]).endswith("@example.com>")


def test_a_reply_names_its_parent_and_the_parents_thread() -> None:
    parent: Message = parent_with("Message-ID: <c@x.com>\r\nReferences: <a@x.com> <b@x.com>\r\n")
    reply: EmailMessage = compose("me@example.com", "a@x.com", "Re: Hello", "ok", "", "", parent)
    assert reply["In-Reply-To"] == "<c@x.com>"
    assert reply["References"] == "<a@x.com> <b@x.com> <c@x.com>"


def test_a_parent_without_references_falls_back_to_its_in_reply_to() -> None:
    assert thread_headers(parent_with("Message-ID: <c@x.com>\r\nIn-Reply-To: <b@x.com>\r\n")) == (
        "<c@x.com>",
        "<b@x.com> <c@x.com>",
    )


def test_a_first_reply_references_only_the_parent() -> None:
    assert thread_headers(parent_with("Message-ID: <c@x.com>\r\n")) == ("<c@x.com>", "<c@x.com>")


def test_a_parent_without_a_message_id_cannot_be_answered() -> None:
    with pytest.raises(ValueError, match="no Message-ID"):
        thread_headers(parent_with("From: a@x.com\r\n"))


def test_a_long_thread_keeps_its_first_and_newest_ids() -> None:
    chain: str = " ".join(f"<{n}@x.com>" for n in range(50))
    references: str = thread_headers(parent_with(f"Message-ID: <last@x.com>\r\nReferences: {chain}\r\n"))[1]
    ids: list[str] = references.split()
    assert len(ids) == 20
    assert ids[0] == "<0@x.com>" and ids[-2:] == ["<49@x.com>", "<last@x.com>"]


def test_only_well_formed_ids_are_copied_from_the_parent() -> None:
    parent: Message = parent_with(
        "Message-ID: junk <c@x.com>\r\n\tBcc: victim@x.com\r\nReferences: (comment) <a@x.com> Bcc: b@x.com\r\n"
    )
    reply: EmailMessage = compose("me@example.com", "a@x.com", "Re", "ok", "", "", parent)
    assert reply["In-Reply-To"] == "<c@x.com>"
    assert reply["References"] == "<a@x.com> <c@x.com>"
    assert reply["Bcc"] is None
    assert b"victim" not in reply.as_bytes()
