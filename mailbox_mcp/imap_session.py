"""A short-lived, verified IMAP connection.

`imaplib.IMAP4_SSL` builds its TLS socket through `ssl.SSLContext.wrap_socket`
with `server_hostname` set to the target host, so the SNI extension is always
sent. That is the whole reason this module exists: the previous Node client
(imap 0.8.19, abandoned 2022) handed `tls.connect` a pre-connected socket,
which makes Node drop SNI, and Gmail answers an SNI-less handshake with a
default certificate that fails verification.

Certificate verification is never disabled here, and there is no option to
disable it.
"""

from __future__ import annotations

import imaplib
import logging
import re
import ssl
from collections.abc import Sequence
from types import TracebackType
from typing import Final

import imap_utf7
from config import MailboxConfig

logger: Final[logging.Logger] = logging.getLogger(__name__)

_GMAIL_EXTENSION: Final[str] = "X-GM-EXT-1"
_LIST_RESPONSE: Final[re.Pattern[str]] = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+(?P<delimiter>"[^"]*"|NIL)\s+(?P<name>.+)$'
)


class ImapError(RuntimeError):
    """Raised when the IMAP server returns a non-OK response."""


class ImapSession:
    """Context manager wrapping one authenticated IMAP connection."""

    def __init__(self, config: MailboxConfig) -> None:
        self._config: MailboxConfig = config
        self._connection: imaplib.IMAP4_SSL | None = None
        self._selected_folder: str | None = None

    def __enter__(self) -> ImapSession:
        context: ssl.SSLContext = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        connection: imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
            host=self._config.imap_host,
            port=self._config.imap_port,
            ssl_context=context,
        )
        typ, _ = connection.login(self._config.imap_user, self._config.password)
        if typ != "OK":
            raise ImapError(f"login failed for {self._config.imap_user}")
        self._connection = connection
        logger.info("connected to %s as %s", self._config.imap_host, self._config.imap_user)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection: imaplib.IMAP4_SSL | None = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            if self._selected_folder is not None:
                closed_status: str = connection.close()[0]
                logger.debug("closed folder: %s", closed_status)
            logout_status: str = connection.logout()[0]
            logger.debug("logout: %s", logout_status)
        except (imaplib.IMAP4.error, OSError) as error:
            logger.warning("error while closing connection: %s", error)

    @property
    def _live(self) -> imaplib.IMAP4_SSL:
        if self._connection is None:
            raise ImapError("IMAP session is not open")
        return self._connection

    def supports_gmail_search(self) -> bool:
        """Return True when the server advertises Gmail's X-GM-EXT-1 extension."""
        capabilities: tuple[str, ...] = self._live.capabilities
        return _GMAIL_EXTENSION in capabilities

    def list_folders(self) -> list[str]:
        """Return every selectable folder name on the server.

        Servers differ on whether the name is quoted: Gmail quotes it, Dovecot
        (HostGator) sends a bare atom. `_LIST_RESPONSE` accepts both, and
        \\Noselect entries are dropped because they cannot be opened.
        """
        typ, data = self._live.list()
        if typ != "OK":
            raise ImapError("LIST command failed")
        names: list[str] = []
        for entry in data:
            if entry is None:
                continue
            decoded: str = entry.decode("utf-8", "replace") if isinstance(entry, bytes) else str(entry)
            match: re.Match[str] | None = _LIST_RESPONSE.match(decoded.strip())
            if match is None:
                logger.debug("unparsed LIST entry: %s", decoded)
                continue
            if "\\noselect" in match.group("flags").lower():
                continue
            name: str = match.group("name").strip().strip('"')
            if name:
                names.append(imap_utf7.decode(name))
        return names

    def select(self, folder: str, readonly: bool) -> int:
        """Select `folder` and return the number of messages it holds.

        `folder` is accepted as the human-readable name shown by `list_folders`
        and re-encoded here, so a listed folder is always selectable.
        """
        typ, data = self._live.select(f'"{imap_utf7.encode(folder)}"', readonly=readonly)
        if typ != "OK":
            raise ImapError(f"cannot select folder {folder!r}")
        self._selected_folder = folder
        first: bytes | None = data[0] if data else None
        return int(first) if first is not None else 0

    def search(self, criteria: Sequence[str]) -> list[int]:
        """Return matching UIDs, oldest first, for the selected folder."""
        typ, data = self._live.uid("SEARCH", *criteria)
        if typ != "OK":
            raise ImapError(f"SEARCH failed for criteria {list(criteria)!r}")
        payload: bytes | None = data[0] if data else None
        if not payload:
            return []
        return [int(token) for token in payload.split()]

    def fetch(self, uid: int, parts: str) -> bytes | None:
        """Return the raw bytes of `parts` for `uid`, or None when absent."""
        typ, data = self._live.uid("FETCH", str(uid), parts)
        if typ != "OK":
            raise ImapError(f"FETCH failed for uid {uid}")
        for entry in data:
            if isinstance(entry, tuple) and len(entry) >= 2 and isinstance(entry[1], bytes):
                return entry[1]
        return None

    def append(self, folder: str, flags: str, raw_message: bytes) -> None:
        """Append `raw_message` to `folder` with `flags`."""
        typ, _ = self._live.append(f'"{imap_utf7.encode(folder)}"', flags, None, raw_message)
        if typ != "OK":
            raise ImapError(f"APPEND to {folder!r} failed")

    def mark_deleted(self, uid: int) -> None:
        """Flag `uid` as deleted in the selected folder and expunge it."""
        typ, _ = self._live.uid("STORE", str(uid), "+FLAGS", r"(\Deleted)")
        if typ != "OK":
            raise ImapError(f"STORE \\Deleted failed for uid {uid}")
        expunged: tuple[str, list[bytes | None]] = self._live.expunge()
        if expunged[0] != "OK":
            raise ImapError(f"EXPUNGE failed after deleting uid {uid}")
