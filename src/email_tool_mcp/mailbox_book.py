"""Turn a mailbox name from a tool call into a live IMAP or SMTP connection.

Standard: dependency injection; the session and SMTP factories are parameters so tests pass fakes.
Placement: mailbox_book.py in the src layout (Python Packaging User Guide).

Settings and passwords are read on every call, so `email-tool-mcp add` takes
effect without restarting the agent.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Final

from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.passwords import MissingPassword, environment_password, read_password
from email_tool_mcp.settings import Mailbox, environment_mailbox, load_mailboxes

SessionFactory = Callable[[Mailbox, str], ImapSession]
SmtpFactory = Callable[[Mailbox], smtplib.SMTP]

_SETUP_HINT: Final[str] = "Run `email-tool-mcp add <name>` in a terminal to add one."


class UnknownMailbox(LookupError):
    """Raised when a tool names a mailbox that is not configured."""


def open_smtp(mailbox: Mailbox) -> smtplib.SMTP:
    """Open an implicit-TLS SMTP connection with certificate verification on."""
    context: ssl.SSLContext = ssl.create_default_context()
    return smtplib.SMTP_SSL(host=mailbox.smtp_host, port=mailbox.smtp_port, context=context)


class MailboxBook:
    """Every mailbox the server may use, resolved fresh on each call."""

    def __init__(
        self,
        settings_file: Path,
        environment: Mapping[str, str],
        session_factory: SessionFactory = ImapSession,
        smtp_factory: SmtpFactory = open_smtp,
    ) -> None:
        self._settings_file: Path = settings_file
        self._environment: Mapping[str, str] = environment
        self._session_factory: SessionFactory = session_factory
        self._smtp_factory: SmtpFactory = smtp_factory

    def mailboxes(self) -> dict[str, Mailbox]:
        """Return every configured mailbox; the environment one wins a name clash."""
        known: dict[str, Mailbox] = load_mailboxes(self._settings_file)
        from_environment: Mailbox | None = environment_mailbox(self._environment)
        if from_environment is not None:
            known[from_environment.name] = from_environment
        return known

    def resolve(self, name: str) -> Mailbox:
        """Return the mailbox called `name`; a blank name means the only one."""
        known: dict[str, Mailbox] = self.mailboxes()
        if not known:
            raise UnknownMailbox(f"No mailbox is configured on this machine. {_SETUP_HINT}")
        if not name:
            if len(known) == 1:
                return next(iter(known.values()))
            raise UnknownMailbox(f"Several mailboxes are configured; name one of: {', '.join(sorted(known))}.")
        if name not in known:
            raise UnknownMailbox(f"No mailbox called {name!r}. Configured: {', '.join(sorted(known))}.")
        return known[name]

    def password(self, mailbox: Mailbox) -> str:
        """Return the password: from the environment for its own mailbox, else the keyring."""
        if environment_mailbox(self._environment) == mailbox:
            return environment_password(mailbox.name, self._environment)
        return read_password(mailbox.name)

    def has_password(self, mailbox: Mailbox) -> bool:
        """Return True when `password(mailbox)` would succeed."""
        try:
            self.password(mailbox)
        except MissingPassword:
            return False
        return True

    def imap(self, name: str) -> ImapSession:
        """Return an unopened IMAP session for the mailbox called `name`."""
        mailbox: Mailbox = self.resolve(name)
        return self._session_factory(mailbox, self.password(mailbox))

    def send(self, name: str, message: EmailMessage, recipients: list[str]) -> dict[str, tuple[int, bytes]]:
        """Send `message` from the mailbox called `name`; return refused recipients."""
        mailbox: Mailbox = self.resolve(name)
        password: str = self.password(mailbox)
        with self._smtp_factory(mailbox) as smtp:
            smtp.login(mailbox.address, password)
            refused: dict[str, tuple[int, bytes]] = smtp.send_message(message, to_addrs=recipients)
        return refused
