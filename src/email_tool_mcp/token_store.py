"""Where a sign-in (an OAuth token cache) is kept between runs, encrypted.

Standard: envelope encryption: the cache is encrypted with Fernet (AES-128-CBC +
HMAC-SHA256, `cryptography`) in a per-user file, and only the random 44-byte key
lives in the OS keyring. A whole MSAL cache is several KB, more than Windows
Credential Manager holds (2.5 KB), so it cannot go in the keyring itself.
Placement: token_store.py; the Microsoft and Google token sources read and write it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import keyring
from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_path

from email_tool_mcp.settings import APP_NAME, SETUP_COMMAND, SettingsError

KEYRING_SERVICE: Final[str] = f"{APP_NAME}-sign-in"
_SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")


def default_store_directory() -> Path:
    """The per-user directory holding encrypted sign-ins on this OS."""
    return user_data_path(APP_NAME, appauthor=False) / "sign-ins"


class TokenStore:
    """One encrypted blob per (provider, mailbox name)."""

    def __init__(self, directory: Path) -> None:
        self._directory: Path = directory

    def _path(self, provider: str, mailbox: str) -> Path:
        return self._directory / f"{provider}-{_SAFE.sub('_', mailbox)}.bin"

    def _key(self, provider: str, mailbox: str, create: bool) -> bytes | None:
        name: str = f"{provider}:{mailbox}"
        stored: str | None = keyring.get_password(KEYRING_SERVICE, name)
        if stored is None and create:
            stored = Fernet.generate_key().decode("ascii")
            keyring.set_password(KEYRING_SERVICE, name, stored)
        return stored.encode("ascii") if stored is not None else None

    def exists(self, provider: str, mailbox: str) -> bool:
        """True when a sign-in is stored (file and key), without decrypting it."""
        return self._path(provider, mailbox).is_file() and self._key(provider, mailbox, create=False) is not None

    def read(self, provider: str, mailbox: str) -> str | None:
        """The stored sign-in, or None when there is none."""
        path: Path = self._path(provider, mailbox)
        key: bytes | None = self._key(provider, mailbox, create=False)
        if key is None or not path.is_file():
            return None
        try:
            return Fernet(key).decrypt(path.read_bytes()).decode("utf-8")
        except InvalidToken as error:
            raise SettingsError(
                f"the stored {provider} sign-in for {mailbox!r} cannot be decrypted; "
                f"sign in again with `{SETUP_COMMAND} {mailbox} --auth {provider}`"
            ) from error

    def write(self, provider: str, mailbox: str, value: str) -> None:
        """Encrypt and store `value`, replacing any earlier one; the file is readable by its owner only."""
        key: bytes | None = self._key(provider, mailbox, create=True)
        assert key is not None
        path: Path = self._path(provider, mailbox)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path = path.with_suffix(".tmp")
        temporary.write_bytes(Fernet(key).encrypt(value.encode("utf-8")))
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def delete(self, provider: str, mailbox: str) -> None:
        """Remove the stored sign-in and its key."""
        self._path(provider, mailbox).unlink(missing_ok=True)
        if self._key(provider, mailbox, create=False) is not None:
            keyring.delete_password(KEYRING_SERVICE, f"{provider}:{mailbox}")
