"""`add` checks the login before saving anything; `remove` clears the keyring too.

Standard: pytest; prompts and the login check are injected callables, never a real terminal or server.
Placement: tests/test_enrol.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from email_tool_mcp.credentials import Credential
from email_tool_mcp.enrol import add_by_auth, add_mailbox, describe_mailboxes, remove_mailbox, save_mailbox
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import MicrosoftTokens
from email_tool_mcp.passwords import has_password, read_password
from email_tool_mcp.settings import Mailbox, load_mailboxes
from email_tool_mcp.token_store import TokenStore


def accept(mailbox: Mailbox, credential: Credential) -> None:
    return None


def refuse(mailbox: Mailbox, credential: Credential) -> None:
    raise OSError("authentication failed")


def forget(mailbox: Mailbox) -> bool:
    raise AssertionError(f"nothing to forget: {mailbox.name} replaced no mailbox")


def test_gmail_hosts_are_offered_as_defaults(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    replies: Iterator[str] = iter(["me@gmail.com", "", ""])
    add_mailbox(
        "home", path, ask=lambda _: next(replies), ask_secret=lambda _: "abcd efgh", login_check=accept, forget=forget
    )
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
            forget=forget,
        )
    assert not path.exists()
    assert not has_password("work")


def test_unknown_domain_without_hosts_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="IMAP server"):
        add_mailbox(
            "work", tmp_path / "m.toml", ask=lambda _: "", ask_secret=lambda _: "x", login_check=accept, forget=forget
        )


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
        forget=forget,
    )
    book: MailboxBook = MailboxBook(path, {})
    assert "password in keyring" in describe_mailboxes(book, path)
    remove_mailbox("work", book, path)
    assert load_mailboxes(path) == {}
    assert not has_password("work")


def test_a_failed_clean_up_is_reported_not_raised(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    save_mailbox(path, Mailbox("work", "me@example.com", "i", 993, "s", 465, auth="microsoft", client_id="c"), forget)

    def locked(mailbox: Mailbox) -> bool:
        raise OSError("keyring locked")

    message: str = add_mailbox(
        "work",
        path,
        address="me@example.com",
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        ask_secret=lambda _: "secret",
        login_check=accept,
        forget=locked,
    )
    assert "could not be deleted (OSError)" in message
    assert load_mailboxes(path)["work"].auth == "password"


def test_removing_an_unsupported_sign_in_says_it_was_left(tmp_path: Path) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    save_mailbox(path, Mailbox("rit", "me@rit.edu", "i", 993, "s", 465, auth="google", client_id="c"), forget)
    assert "left in place" in remove_mailbox("rit", MailboxBook(path, {}), path)


@pytest.mark.parametrize(
    ("auth", "smtp_host", "client_id", "cloud", "complaint"),
    [
        ("microsoft", "smtp.custom.us", "c", "commercial", "drop --imap-"),
        ("password", "", "c", "commercial", "need --auth microsoft"),
        ("password", "", "", "gcc-high", "need --auth microsoft"),
        ("google", "", "", "commercial", "must be password or microsoft"),
    ],
)
def test_add_refuses_options_that_do_not_apply(
    tmp_path: Path, auth: str, smtp_host: str, client_id: str, cloud: str, complaint: str
) -> None:
    tokens: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "s"))
    with pytest.raises(ValueError, match=complaint):
        add_by_auth(
            "x", tmp_path / "m.toml", auth, tokens, forget, smtp_host=smtp_host, client_id=client_id, cloud=cloud
        )
