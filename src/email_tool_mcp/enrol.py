"""Add, remove and list mailboxes on this machine from a terminal.

Standard: getpass for hidden password entry; credentials stored with `keyring` (passwords.py).
Placement: enrol.py, the module `__main__.py` dispatches the add/remove/list commands to.

`add` proves the login works over both IMAP and SMTP before it saves anything,
so a typo never leaves a half-configured mailbox behind.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable
from pathlib import Path
from typing import Final

from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.mailbox_book import open_smtp
from email_tool_mcp.passwords import delete_password, has_password, normalize_password, store_password
from email_tool_mcp.settings import (
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    SETUP_COMMAND,
    Mailbox,
    load_mailboxes,
    save_mailboxes,
)

Ask = Callable[[str], str]
LoginCheck = Callable[[Mailbox, str], None]

KNOWN_HOSTS: Final[dict[str, tuple[str, str]]] = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
}
_GMAIL_NOTE: Final[str] = "Gmail needs an App Password (Google Account > Security > App passwords), not your password."


def check_login(mailbox: Mailbox, password: str) -> None:
    """Log in over IMAP and SMTP; raise if either refuses."""
    with ImapSession(mailbox, password):
        pass
    with open_smtp(mailbox) as smtp:
        smtp.login(mailbox.address, password)


def ask_with_default(ask: Ask, prompt: str, default: str) -> str:
    """Ask `prompt`, returning `default` when the answer is blank."""
    shown: str = f"{prompt} [{default}]: " if default else f"{prompt}: "
    return ask(shown).strip() or default


def add_mailbox(
    name: str,
    settings_file: Path,
    address: str = "",
    imap_host: str = "",
    imap_port: int = DEFAULT_IMAP_PORT,
    smtp_host: str = "",
    smtp_port: int = DEFAULT_SMTP_PORT,
    ask: Ask = input,
    ask_secret: Ask = getpass.getpass,
    login_check: LoginCheck = check_login,
) -> str:
    """Ask for anything missing, check the login, then save the mailbox and its password."""
    address = address or ask_with_default(ask, "Email address", "")
    domain: str = address.rpartition("@")[2].lower()
    known: tuple[str, str] = KNOWN_HOSTS.get(domain, ("", ""))
    imap_host = imap_host or ask_with_default(ask, "IMAP server", known[0])
    smtp_host = smtp_host or ask_with_default(ask, "SMTP server", known[1])
    if not (address and imap_host and smtp_host):
        raise ValueError("an address, an IMAP server and an SMTP server are all required")
    mailbox: Mailbox = Mailbox(name, address, imap_host, imap_port, smtp_host, smtp_port)

    note: str = f" ({_GMAIL_NOTE})" if known[0] == "imap.gmail.com" else ""
    password: str = normalize_password(ask_secret(f"Password for {address}{note}: "))
    if not password:
        raise ValueError("no password entered")
    login_check(mailbox, password)

    # Password first: a keyring that refuses it must not leave a mailbox saved without one.
    store_password(name, password)
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    mailboxes[name] = mailbox
    save_mailboxes(settings_file, mailboxes)
    return f"Mailbox {name!r} ({address}) added. Login checked over IMAP and SMTP; password is in the OS keyring."


def remove_mailbox(name: str, settings_file: Path) -> str:
    """Forget the mailbox called `name` and delete its keyring password."""
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    if mailboxes.pop(name, None) is None:
        raise ValueError(f"no mailbox called {name!r}")
    save_mailboxes(settings_file, mailboxes)
    delete_password(name)
    return f"Mailbox {name!r} removed, password deleted from the OS keyring."


def describe_mailboxes(settings_file: Path) -> str:
    """Return one line per mailbox: name, address, servers, password state."""
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    if not mailboxes:
        return f"No mailboxes yet ({settings_file}). Add one with `{SETUP_COMMAND} <name>`."
    lines: list[str] = [f"Settings: {settings_file}"]
    for name, mailbox in sorted(mailboxes.items()):
        state: str = "password in keyring" if has_password(name) else "NO PASSWORD"
        lines.append(
            f"{name}: {mailbox.address}  imap {mailbox.imap_host}:{mailbox.imap_port}  "
            f"smtp {mailbox.smtp_host}:{mailbox.smtp_port}  ({state})"
        )
    return "\n".join(lines)
