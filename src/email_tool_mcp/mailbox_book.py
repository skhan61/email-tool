"""Turn a mailbox name from a tool call into a live IMAP or SMTP connection.

Standard: dependency injection; the session and SMTP factories are parameters so tests pass fakes.
Placement: mailbox_book.py in the src layout (Python Packaging User Guide).

Settings and passwords are read on every call, so `email-tool-mcp add` takes
effect without restarting the agent.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Final

from keyring.errors import KeyringError

from email_tool_mcp.credentials import Credential, TokenSource, smtp_login
from email_tool_mcp.cui import message_markings
from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.message_compose import envelope_recipients
from email_tool_mcp.passwords import MissingPassword, delete_password, environment_password, read_password
from email_tool_mcp.policy import Policy, PolicyRefusal
from email_tool_mcp.settings import (
    ENV_PASSWORD,
    NETWORK_TIMEOUT_SECONDS,
    SETUP_COMMAND,
    STARTTLS_PORTS,
    Mailbox,
    SettingsError,
    environment_mailbox,
    load_mailboxes,
)
from email_tool_mcp.tls import client_context

SessionFactory = Callable[[Mailbox, Credential], ImapSession]
SmtpFactory = Callable[[Mailbox], smtplib.SMTP]

logger: Final[logging.Logger] = logging.getLogger(__name__)


class UnknownMailbox(LookupError):
    """Raised when a tool names a mailbox that is not configured."""


def open_smtp(mailbox: Mailbox) -> smtplib.SMTP:
    """Ports 25 and 587: STARTTLS, refused if the server does not offer it. Any other port: implicit TLS.

    Both use tls.client_context(): certificate verified, TLS 1.2 minimum.
    """
    if mailbox.smtp_port in STARTTLS_PORTS:
        connection: smtplib.SMTP = smtplib.SMTP(
            host=mailbox.smtp_host, port=mailbox.smtp_port, timeout=NETWORK_TIMEOUT_SECONDS
        )
        try:
            connection.starttls(context=client_context())
        except BaseException:
            connection.close()
            raise
        return connection
    return smtplib.SMTP_SSL(
        host=mailbox.smtp_host, port=mailbox.smtp_port, context=client_context(), timeout=NETWORK_TIMEOUT_SECONDS
    )


class MailboxBook:
    """Every mailbox the server may use, resolved fresh on each call."""

    def __init__(
        self,
        settings_file: Path,
        environment: Mapping[str, str],
        session_factory: SessionFactory = ImapSession,
        smtp_factory: SmtpFactory = open_smtp,
        policy: Policy | None = None,
        token_sources: Mapping[str, TokenSource] | None = None,
    ) -> None:
        self._settings_file: Path = settings_file
        self._environment: Mapping[str, str] = environment
        self._session_factory: SessionFactory = session_factory
        self._smtp_factory: SmtpFactory = smtp_factory
        self.policy: Policy = policy if policy is not None else Policy(())
        self._token_sources: Mapping[str, TokenSource] = token_sources or {}
        self.environment_problem: str = ""

    def _environment_mailbox(self, enrolled: dict[str, Mailbox]) -> tuple[Mailbox | None, str]:
        """The EMAIL_TOOL_* mailbox and, when it is kept out, why: malformed, disallowed, or name taken.

        Pure: it changes no state, so worker threads can call it concurrently.
        """
        try:
            found: Mailbox | None = environment_mailbox(self._environment)
        except SettingsError as error:
            return None, f"The mailbox from the app's settings was ignored: {error}."
        if found is None:
            return None, ""
        if not self.policy.rules_for(found.name, found.address).allow_environment_mailbox:
            return None, "The mailbox from the app's settings was ignored: policy disallows it."
        if found.name in enrolled:
            return None, f"The mailbox from the app's settings was ignored: {found.name!r} is already enrolled here."
        return found, ""

    def mailboxes(self) -> dict[str, Mailbox]:
        """Return every configured mailbox; an enrolled mailbox always wins a name clash."""
        known: dict[str, Mailbox] = load_mailboxes(self._settings_file)
        from_environment: Mailbox | None
        from_environment, self.environment_problem = self._environment_mailbox(known)
        if self.environment_problem:
            logger.warning("%s", self.environment_problem)
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

    def label(self, name: str) -> str:
        """The mailbox a call acts on, as audit records and policy name it; `name` if it cannot resolve."""
        try:
            return self.resolve(name).name
        except Exception:
            return name

    def password(self, mailbox: Mailbox) -> str:
        """Return EMAIL_TOOL_PASSWORD for the environment's own mailbox when set, else the keyring."""
        admitted: Mailbox | None = self._environment_mailbox(load_mailboxes(self._settings_file))[0]
        if self._environment.get(ENV_PASSWORD) and admitted == mailbox:
            return environment_password(mailbox.name, self._environment)
        return read_password(mailbox.name)

    def credential(self, mailbox: Mailbox) -> Credential:
        """How `mailbox` logs in now: its password, or a fresh access token from its sign-in."""
        if mailbox.auth == "password":
            return Credential(mailbox.address, self.password(mailbox), is_token=False)
        source: TokenSource | None = self._token_sources.get(mailbox.auth)
        if source is None:
            raise SettingsError(f"{mailbox.auth} sign-in is not available in this version of email-tool")
        return Credential(mailbox.address, source.access_token(mailbox), is_token=True)

    def has_credential(self, mailbox: Mailbox) -> bool:
        """True when `mailbox` can log in without asking: a stored password or sign-in."""
        return not self.login_problem(mailbox)

    def login_problem(self, mailbox: Mailbox) -> str:
        """Why `mailbox` cannot log in right now, or "" when it can. Never raises."""
        if mailbox.auth == "password":
            return "" if self.has_password(mailbox) else "no password"
        source: TokenSource | None = self._token_sources.get(mailbox.auth)
        if source is None:
            return f"{mailbox.auth} sign-in is not available in this version"
        try:
            # Reading the sign-in decrypts it, so require_fips applies before that too.
            self.policy.check_fips(mailbox.name, mailbox.address, keeps_sign_in=True)
            return "" if source.is_signed_in(mailbox) else f"not signed in to {mailbox.auth}"
        except PolicyRefusal as refusal:
            return f"refused: {refusal}"
        except Exception as error:
            return f"cannot read the {mailbox.auth} sign-in: {type(error).__name__}"

    def forget(self, mailbox: Mailbox) -> bool:
        """Delete what lets `mailbox` log in: its keyring password or its stored sign-in.

        False when this version has no provider for its sign-in, so nothing was deleted.
        """
        if mailbox.auth == "password":
            delete_password(mailbox.name)
            return True
        source: TokenSource | None = self._token_sources.get(mailbox.auth)
        if source is None:
            return False
        source.forget(mailbox)
        return True

    def has_password(self, mailbox: Mailbox) -> bool:
        """Return True when `password(mailbox)` would succeed."""
        try:
            self.password(mailbox)
        except (MissingPassword, KeyringError):
            return False
        return True

    def imap(self, mailbox: Mailbox) -> ImapSession:
        """Return an unopened IMAP session for `mailbox`; refused first if FIPS is required and absent."""
        self.policy.check_fips(mailbox.name, mailbox.address, keeps_sign_in=mailbox.keeps_sign_in)
        return self._session_factory(mailbox, self.credential(mailbox))

    def approve(self, mailbox: Mailbox, message: EmailMessage) -> list[str]:
        """Check the message's real recipient list against policy and return it."""
        recipients: list[str] = envelope_recipients(message)
        addressed: bool = bool(str(message.get("To", "")).strip() or str(message.get("Cc", "")).strip())
        self.policy.check_message(
            mailbox.name, mailbox.address, recipients, addressed, lambda: message_markings(message)
        )
        return recipients

    def smtp(self, mailbox: Mailbox) -> smtplib.SMTP:
        """Return an unauthenticated SMTP connection for `mailbox`; refused first if FIPS is required and absent."""
        self.policy.check_fips(mailbox.name, mailbox.address, keeps_sign_in=mailbox.keeps_sign_in)
        return self._smtp_factory(mailbox)

    def send(self, mailbox: Mailbox, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        """Send `message` from `mailbox` to its approved recipients; return the refused ones."""
        recipients: list[str] = self.approve(mailbox, message)
        if not recipients:
            raise ValueError("no recipients resolved from the 'to' and 'cc' arguments")
        with self.smtp(mailbox) as smtp:
            smtp_login(smtp, self.credential(mailbox))
            refused: dict[str, tuple[int, bytes]] = smtp.send_message(message, to_addrs=recipients)
        return refused
