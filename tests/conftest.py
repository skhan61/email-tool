"""Shared fixtures: an in-memory keyring, a mailbox book wired to fakes.

Standard: pytest conftest.py fixtures; keyring.set_keyring with an in-memory backend for tests.
Placement: tests/conftest.py, which pytest loads for every test in the folder.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend

from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.settings import Mailbox, save_mailboxes
from tests.fakes import FakeMailServer

WORK: Mailbox = Mailbox("work", "me@example.com", "imap.example.com", 993, "smtp.example.com", 465)
HOME: Mailbox = Mailbox("home", "me@gmail.com", "imap.gmail.com", 993, "smtp.gmail.com", 465)


class MemoryKeyring(KeyringBackend):
    """A keyring that forgets everything when the test ends."""

    priority: float = 1.0

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.entries[(service, username)]


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    """Every test gets an empty keyring and never touches the real one."""
    previous: KeyringBackend = keyring.get_keyring()
    backend: MemoryKeyring = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only."""
    return "asyncio"


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """A settings file holding the `work` and `home` mailboxes."""
    path: Path = tmp_path / "mailboxes.toml"
    save_mailboxes(path, {"work": WORK, "home": HOME})
    return path


@pytest.fixture
def mail_server() -> FakeMailServer:
    """One fake IMAP and SMTP server shared by every session a test opens."""
    return FakeMailServer()


@pytest.fixture
def book(settings_file: Path, mail_server: FakeMailServer) -> MailboxBook:
    """A mailbox book over the two settings mailboxes, connected to the fake server."""
    return MailboxBook(settings_file, {}, mail_server.open_imap, mail_server.open_smtp)
