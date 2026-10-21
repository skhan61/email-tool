"""A short-lived, verified IMAP connection.

Standard: imapclient, which parses IMAP responses, quotes search criteria and
encodes folder names (modified UTF-7) itself.
Placement: imap_session.py, the one module that talks IMAP.

TLS goes through `ssl.create_default_context()`, so the certificate is always
verified and SNI is always sent (Gmail rejects an SNI-less handshake). There is
no option to turn verification off.
"""

from __future__ import annotations

import logging
import ssl
from types import TracebackType
from typing import Any, Final

from imapclient import IMAPClient

from email_tool_mcp.settings import Mailbox

logger: Final[logging.Logger] = logging.getLogger(__name__)

_TIMEOUT_SECONDS: Final[float] = 60.0
_GMAIL_EXTENSION: Final[str] = "X-GM-EXT-1"
_UID_EXPUNGE: Final[str] = "UIDPLUS"
_HEADER_ITEM: Final[bytes] = b"BODY[HEADER]"
_FULL_ITEM: Final[bytes] = b"BODY[]"


class ImapSession:
    """Context manager wrapping one authenticated IMAP connection."""

    def __init__(self, mailbox: Mailbox, password: str) -> None:
        self._mailbox: Mailbox = mailbox
        self._password: str = password
        self._client: Any = None

    def __enter__(self) -> ImapSession:
        client: Any = IMAPClient(
            self._mailbox.imap_host,
            port=self._mailbox.imap_port,
            ssl=True,
            ssl_context=ssl.create_default_context(),
            timeout=_TIMEOUT_SECONDS,
        )
        client.login(self._mailbox.address, self._password)
        self._client = client
        logger.info("connected to %s as %s", self._mailbox.imap_host, self._mailbox.address)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        client: Any = self._client
        self._client = None
        if client is None:
            return
        try:
            client.logout()
        except (IMAPClient.Error, OSError) as error:
            logger.warning("error while closing connection: %s", error)

    def supports_gmail_search(self) -> bool:
        """Return True when the server is Gmail (advertises X-GM-EXT-1)."""
        return bool(self._client.has_capability(_GMAIL_EXTENSION))

    # no-library: scikit-learn: list_folders lists IMAP mail folders, it is not a data split.
    def list_folders(self) -> list[str]:
        """Return every selectable folder name, decoded for display."""
        names: list[str] = []
        for flags, _, name in self._client.list_folders():
            if not any(flag.lower() == b"\\noselect" for flag in flags):
                names.append(str(name))
        return names

    def select(self, folder: str, readonly: bool) -> int:
        """Select `folder` (the name list_folders shows) and return its message count."""
        response: dict[bytes, Any] = self._client.select_folder(folder, readonly=readonly)
        return int(response[b"EXISTS"])

    def search(self, criteria: list[str]) -> list[int]:
        """Return matching UIDs in the selected folder; imapclient quotes each value."""
        charset: str | None = None if all(value.isascii() for value in criteria) else "UTF-8"
        return [int(uid) for uid in self._client.search(criteria, charset=charset)]

    def gmail_search(self, query: str) -> list[int]:
        """Return UIDs matching Gmail's own search syntax (X-GM-RAW)."""
        return [int(uid) for uid in self._client.gmail_search(query)]

    def _fetch(self, uid: int, item: bytes) -> bytes | None:
        request: str = item.decode().replace("BODY[", "BODY.PEEK[")
        response: dict[int, dict[bytes, Any]] = self._client.fetch([uid], [request])
        found: Any = response.get(uid, {}).get(item)
        return found if isinstance(found, bytes) else None

    def fetch_header(self, uid: int) -> bytes | None:
        """Return the raw header of `uid` without marking it read, or None when absent."""
        return self._fetch(uid, _HEADER_ITEM)

    def fetch_message(self, uid: int) -> bytes | None:
        """Return the raw message `uid` without marking it read, or None when absent."""
        return self._fetch(uid, _FULL_ITEM)

    def append(self, folder: str, flags: tuple[str, ...], raw_message: bytes) -> None:
        """Append `raw_message` to `folder` with `flags`."""
        self._client.append(folder, raw_message, flags=flags)

    def mark_deleted(self, uid: int) -> bool:
        """Delete `uid` from the selected folder; return True when it is gone.

        With UIDPLUS (Gmail, Dovecot, most servers) only `uid` is expunged. Without
        it, EXPUNGE would also purge every other message flagged \\Deleted, so it
        runs only when `uid` is the sole flagged one; otherwise `uid` stays flagged.
        """
        self._client.delete_messages([uid])
        if self._client.has_capability(_UID_EXPUNGE):
            self._client.uid_expunge([uid])
            return True
        if self.search(["DELETED"]) != [uid]:
            return False
        self._client.expunge()
        return True
