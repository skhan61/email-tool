"""`add` checks the login before saving anything; `remove` clears the keyring too.

Standard: pytest; prompts and the login check are injected callables, never a real terminal or server.
Placement: tests/test_enrol.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from email_tool_mcp.credentials import Credential
from email_tool_mcp.enrol import add_mailbox, describe_mailboxes, remove_mailbox
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import has_password, read_password
from email_tool_mcp.settings import Mailbox, load_mailboxes


def accept(mailbox: Mailbox, credential: Credential) -> None:
    return None


def refuse(mailbox: Mailbox, credential: Credential) -> None:
    raise OSError("authentication failed")


def test_gmail_hosts_are_offered_as_defaults(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    replies: Iterator[str] = iter(["me@gmail.com", "", ""])
    add_mailbox("home", path, ask=lambda _: next(replies), ask_secret=lambda _: "abcd efgh", login_check=accept)
    assert load_mailboxes(path)["home"] == Mailbox("home", "me@gmail.com", "imap.gmail.com", 993, "smtp.gmail.com", 465)
    assert read_password("home") == "abcdefgh"


def test_failed_login_saves_nothing(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    with pytest.raises(OSError):
        add_mailbox(
            "work",
            path,
            address="me@example.com",
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            ask_secret=lambda _: "wrong",
            login_check=refuse,
        )
    assert not path.exists()
    assert not has_password("work")


def test_unknown_domain_without_hosts_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="IMAP server"):
        add_mailbox("work", tmp_path / "m.toml", ask=lambda _: "", ask_secret=lambda _: "x", login_check=accept)


def test_remove_deletes_settings_and_password(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    add_mailbox(
        "work",
        path,
        address="me@example.com",
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        ask_secret=lambda _: "secret",
        login_check=accept,
    )
    book: MailboxBook = MailboxBook(path, {})
    assert "password in keyring" in describe_mailboxes(book, path)
    remove_mailbox("work", book, path)
    assert load_mailboxes(path) == {}
    assert not has_password("work")
