"""MailboxBook resolves names and finds each password in the right place.

Standard: pytest with an in-memory keyring backend and an injected fake IMAP factory.
Placement: tests/test_mailbox_book.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from email_tool_mcp.mailbox_book import MailboxBook, UnknownMailbox
from email_tool_mcp.passwords import MissingPassword, store_password
from email_tool_mcp.settings import SETUP_COMMAND, save_mailboxes
from tests.conftest import WORK
from tests.fakes import FakeMailServer

ENVIRONMENT: dict[str, str] = {
    "EMAIL_TOOL_NAME": "desktop",
    "EMAIL_TOOL_ADDRESS": "desk@example.com",
    "EMAIL_TOOL_IMAP_HOST": "imap.example.com",
    "EMAIL_TOOL_SMTP_HOST": "smtp.example.com",
    "EMAIL_TOOL_PASSWORD": "from env",
}


def test_blank_name_picks_the_only_mailbox(tmp_path: Path, mail_server: FakeMailServer) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    save_mailboxes(path, {"work": WORK})
    assert MailboxBook(path, {}, mail_server.open_imap).resolve("") == WORK


def test_blank_name_with_several_mailboxes_lists_them(book: MailboxBook) -> None:
    with pytest.raises(UnknownMailbox, match="home, work"):
        book.resolve("")


def test_unknown_name_is_refused(book: MailboxBook) -> None:
    with pytest.raises(UnknownMailbox, match="'school'"):
        book.resolve("school")


def test_no_mailboxes_points_at_the_add_command(tmp_path: Path) -> None:
    with pytest.raises(UnknownMailbox, match=re.escape(SETUP_COMMAND)):
        MailboxBook(tmp_path / "absent.toml", {}).resolve("")


def test_missing_password_names_the_fix(book: MailboxBook) -> None:
    with pytest.raises(MissingPassword, match=re.escape(f"{SETUP_COMMAND} work")):
        book.imap(book.resolve("work"))


def test_keyring_password_reaches_the_login(book: MailboxBook, mail_server: FakeMailServer) -> None:
    store_password("work", "abcd efgh ijkl mnop")
    book.imap(book.resolve("work"))
    assert mail_server.logins == [("me@example.com", "abcdefghijklmnop")]


def test_environment_password_only_serves_the_environment_mailbox(
    settings_file: Path, mail_server: FakeMailServer
) -> None:
    book: MailboxBook = MailboxBook(settings_file, ENVIRONMENT, mail_server.open_imap)
    book.imap(book.resolve("desktop"))
    assert mail_server.logins == [("desk@example.com", "fromenv")]
    with pytest.raises(MissingPassword):
        book.imap(book.resolve("work"))


def test_environment_mailbox_falls_back_to_the_keyring(settings_file: Path, mail_server: FakeMailServer) -> None:
    without_password: dict[str, str] = dict(ENVIRONMENT)
    del without_password["EMAIL_TOOL_PASSWORD"]
    store_password("desktop", "from keyring")
    book: MailboxBook = MailboxBook(settings_file, without_password, mail_server.open_imap)
    book.imap(book.resolve("desktop"))
    assert mail_server.logins == [("desk@example.com", "fromkeyring")]


def test_malformed_environment_mailbox_leaves_the_others_working(settings_file: Path) -> None:
    broken: dict[str, str] = {"EMAIL_TOOL_ADDRESS": "x@example.com", "EMAIL_TOOL_IMAP_HOST": "imap.x"}
    assert set(MailboxBook(settings_file, broken).mailboxes()) == {"home", "work"}


def test_malformed_environment_mailbox_is_explained_when_nothing_resolves(tmp_path: Path) -> None:
    broken: dict[str, str] = {"EMAIL_TOOL_ADDRESS": "x@example.com", "EMAIL_TOOL_IMAP_HOST": "imap.x"}
    with pytest.raises(UnknownMailbox, match="app's settings was ignored.*EMAIL_TOOL_SMTP_HOST"):
        MailboxBook(tmp_path / "absent.toml", broken).resolve("")
