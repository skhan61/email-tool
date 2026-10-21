"""Turn a mailbox name from a tool call into a live IMAP or SMTP connection.

Standard: dependency injection; the session and SMTP factories are parameters so tests pass fakes.
Placement: mailbox_book.py in the src layout (Python Packaging User Guide).

Settings and passwords are read on every call, so `email-tool-mcp add` takes
effect without restarting the agent.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Final

from keyring.errors import KeyringError

from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.message_compose import envelope_recipients
from email_tool_mcp.passwords import MissingPassword, environment_password, read_password
from email_tool_mcp.policy import Policy
from email_tool_mcp.settings import (
    ENV_PASSWORD,
    SETUP_COMMAND,
    Mailbox,
    SettingsError,
    environment_mailbox,
    load_mailboxes,
)

SessionFactory = Callable[[Mailbox, str], ImapSession]
SmtpFactory = Callable[[Mailbox], smtplib.SMTP]

logger: Final[logging.Logger] = logging.getLogger(__name__)


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
        policy: Policy | None = None,
    ) -> None:
        self._settings_file: Path = settings_file
        self._environment: Mapping[str, str] = environment
        self._session_factory: SessionFactory = session_factory
        self._smtp_factory: SmtpFactory = smtp_factory
        self.policy: Policy = policy if policy is not None else Policy(())
        self.environment_problem: str = ""

    def _environment_mailbox(self) -> Mailbox | None:
        """The EMAIL_TOOL_* mailbox; a malformed one is skipped and kept in `environment_problem`."""
        try:
            found: Mailbox | None = environment_mailbox(self._environment)
        except SettingsError as error:
            logger.warning("ignoring the EMAIL_TOOL_* mailbox: %s", error)
            self.environment_problem = f"The mailbox from the app's settings was ignored: {error}."
            return None
        self.environment_problem = ""
        return found

    def mailboxes(self) -> dict[str, Mailbox]:
        """Return every configured mailbox; the environment one wins a name clash."""
        known: dict[str, Mailbox] = load_mailboxes(self._settings_file)
        from_environment: Mailbox | None = self._environment_mailbox()
        if from_environment is not None:
            known[from_environment.name] = from_environment
        return known

    def resolve(self, name: str) -> Mailbox:
        """Return the mailbox called `name`; a blank name means the only one."""
        known: dict[str, Mailbox] = self.mailboxes()
        if name in known or (not name and len(known) == 1):
            return known[name] if name else next(iter(known.values()))
        problem: str = ""
        if not known:
            problem = f"No mailbox is configured. Run `{SETUP_COMMAND} <name>` in a terminal."
        elif not name:
            problem = f"Several mailboxes are configured; name one of: {', '.join(sorted(known))}."
        else:
            problem = f"No mailbox called {name!r}. Configured: {', '.join(sorted(known))}."
        raise UnknownMailbox(f"{problem} {self.environment_problem}".strip())

    def password(self, mailbox: Mailbox) -> str:
        """Return EMAIL_TOOL_PASSWORD for the environment's own mailbox when set, else the keyring."""
        if self._environment.get(ENV_PASSWORD) and self._environment_mailbox() == mailbox:
            return environment_password(mailbox.name, self._environment)
        return read_password(mailbox.name)

    def has_password(self, mailbox: Mailbox) -> bool:
        """Return True when `password(mailbox)` would succeed."""
        try:
            self.password(mailbox)
        except (MissingPassword, KeyringError):
            return False
        return True

    def imap(self, mailbox: Mailbox) -> ImapSession:
        """Return an unopened IMAP session for `mailbox`."""
        return self._session_factory(mailbox, self.password(mailbox))

    def approve(self, mailbox: Mailbox, message: EmailMessage) -> list[str]:
        """Check the message's real recipient list against policy and return it."""
        recipients: list[str] = envelope_recipients(message)
        addressed: bool = bool(str(message.get("To", "")).strip() or str(message.get("Cc", "")).strip())
        self.policy.check_recipients(mailbox.name, recipients, addressed)
        return recipients

    def send(self, mailbox: Mailbox, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        """Send `message` from `mailbox` to its approved recipients; return the refused ones."""
        recipients: list[str] = self.approve(mailbox, message)
        if not recipients:
            raise ValueError("no recipients resolved from the 'to' and 'cc' arguments")
        password: str = self.password(mailbox)
        with self._smtp_factory(mailbox) as smtp:
            smtp.login(mailbox.address, password)
            refused: dict[str, tuple[int, bytes]] = smtp.send_message(message, to_addrs=recipients)
        return refused
