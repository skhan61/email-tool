"""Mailbox passwords, held in the OS keyring.

Standard: the `keyring` library (Secret Service, macOS Keychain, Windows Credential Manager).
Placement: passwords.py in the src layout (Python Packaging User Guide).

Nothing here writes a password to a file, so no agent's own config rewrite
can erase it (issue #9).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import keyring

from email_tool_mcp.settings import ENV_PASSWORD

KEYRING_SERVICE: Final[str] = "email-tool"


class MissingPassword(LookupError):
    """Raised when a mailbox has no password on this machine."""

    def __init__(self, mailbox_name: str) -> None:
        super().__init__(
            f"No password for mailbox {mailbox_name!r} on this machine. "
            f"Run `email-tool-mcp add {mailbox_name}` in a terminal, then try again."
        )


def read_password(mailbox_name: str) -> str:
    """Return the keyring password for `mailbox_name`."""
    return clean_password(mailbox_name, keyring.get_password(KEYRING_SERVICE, mailbox_name))


def environment_password(mailbox_name: str, environment: Mapping[str, str]) -> str:
    """Return `EMAIL_TOOL_PASSWORD`, for the mailbox described by the environment."""
    return clean_password(mailbox_name, environment.get(ENV_PASSWORD))


def clean_password(mailbox_name: str, stored: str | None) -> str:
    """Strip spaces (Google shows app passwords in groups of four); raise when empty."""
    password: str = (stored or "").strip().replace(" ", "")
    if not password:
        raise MissingPassword(mailbox_name)
    return password


def has_password(mailbox_name: str) -> bool:
    """Return True when the keyring holds a password for `mailbox_name`."""
    return bool(keyring.get_password(KEYRING_SERVICE, mailbox_name))


def store_password(mailbox_name: str, password: str) -> None:
    """Save `password` for `mailbox_name` in the keyring, replacing any old one."""
    keyring.set_password(KEYRING_SERVICE, mailbox_name, password)


def delete_password(mailbox_name: str) -> None:
    """Remove the keyring entry for `mailbox_name`, if there is one."""
    if has_password(mailbox_name):
        keyring.delete_password(KEYRING_SERVICE, mailbox_name)
