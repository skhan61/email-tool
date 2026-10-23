"""A short-lived, verified IMAP connection.

Standard: imapclient, which parses IMAP responses, quotes or literal-encodes
search values and encodes folder names (modified UTF-7) itself.
Placement: imap_session.py, the one module that talks IMAP.

TLS comes from tls.client_context(): certificate always verified, SNI always
sent (Gmail rejects an SNI-less handshake), TLS 1.2 minimum. There is no option
to turn verification off.

Every value a tool passes in comes from the model, which may be steered by the
text of an email, so line breaks are refused before anything reaches the wire.
"""

from __future__ import annotations

import logging
from datetime import date
from types import TracebackType
from typing import Any, Final

from imapclient import IMAPClient, imap_utf7

# imapclient sends a `_literal` as an IMAP literal ({n} + bytes), so a value
# such as `{12}` or `(urgent)` is never read as syntax. Its public API quotes a
# value only when it holds a space, quote or backslash.
from imapclient.imapclient import _literal

from email_tool_mcp.credentials import Credential, imap_login
from email_tool_mcp.settings import NETWORK_TIMEOUT_SECONDS, Mailbox
from email_tool_mcp.tls import client_context, socket_details

logger: Final[logging.Logger] = logging.getLogger(__name__)

_GMAIL_EXTENSION: Final[str] = "X-GM-EXT-1"
_UID_EXPUNGE: Final[str] = "UIDPLUS"
_HEADER_REQUEST: Final[str] = "BODY.PEEK[HEADER]"
_HEADER_KEY: Final[bytes] = b"BODY[HEADER]"
_MESSAGE_REQUEST: Final[str] = "BODY.PEEK[]"
_MESSAGE_KEY: Final[bytes] = b"BODY[]"
_FORBIDDEN: Final[tuple[str, ...]] = ("\r", "\n", "\0")
_TRASH_FLAG: Final[bytes] = b"\\trash"
_GMAIL_MESSAGE_ID: Final[bytes] = b"X-GM-MSGID"


def checked(value: str) -> str:
    """Return `value`, refusing line breaks and NUL, which would end an IMAP command."""
    if any(character in value for character in _FORBIDDEN):
        raise ValueError("line breaks are not allowed in a search value or folder name")
    return value


# A search is keywords (bare upper-case words such as FROM or ALL) followed by
# their arguments: `text()` values, UIDs as int, dates as `date`.
SearchItem = str | bytes | int | date


def text(value: str) -> bytes:
    """Wrap a search value so imapclient sends it as a literal or a quoted string, never as bare syntax."""
    wrapped: bytes = _literal(checked(value).encode("utf-8"))
    return wrapped


def decode_folder_name(raw: bytes | str) -> str:
    """Decode a modified UTF-7 folder name; a malformed one is shown as plain UTF-8."""
    if isinstance(raw, str):
        return raw
    try:
        return str(imap_utf7.decode(raw))
    except (UnicodeDecodeError, ValueError):
        return raw.decode("utf-8", "replace")


class ImapSession:
    """Context manager wrapping one authenticated IMAP connection."""

    def __init__(self, mailbox: Mailbox, credential: Credential) -> None:
        self._mailbox: Mailbox = mailbox
        self._credential: Credential = credential
        self._client: IMAPClient | None = None
        self._selected: str = ""
        self._trash: str | None = None

    def __enter__(self) -> ImapSession:
        client: IMAPClient = IMAPClient(
            self._mailbox.imap_host,
            port=self._mailbox.imap_port,
            ssl=True,
            ssl_context=client_context(),
            timeout=NETWORK_TIMEOUT_SECONDS,
        )
        try:
            imap_login(client, self._credential)
        except BaseException:
            client.shutdown()
            raise
        self._client = client
        logger.info("connected to %s as %s", self._mailbox.imap_host, self._mailbox.address)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        client: IMAPClient | None = self._client
        self._client = None
        if client is None:
            return
        try:
            client.logout()
        except (IMAPClient.Error, OSError) as error:
            logger.warning("error while closing connection: %s", error)

    @property
    def _live(self) -> IMAPClient:
        if self._client is None:
            raise RuntimeError("IMAP session is not open; use it inside `with`")
        return self._client

    def tls_details(self) -> str:
        """The negotiated protocol and cipher, e.g. "TLSv1.3 TLS_AES_256_GCM_SHA384"."""
        return socket_details(self._live.socket())

    def supports_gmail_search(self) -> bool:
        """Return True when the server is Gmail (advertises X-GM-EXT-1)."""
        return bool(self._live.has_capability(_GMAIL_EXTENSION))

    def _selectable(self) -> list[tuple[tuple[bytes, ...], str]]:
        """Every selectable folder with its flags, decoded one by one so a bad name cannot fail the rest."""
        client: IMAPClient = self._live
        client.folder_encode = False
        try:
            listing: list[tuple[tuple[bytes, ...], bytes, bytes]] = client.list_folders()
        finally:
            client.folder_encode = True
        return [
            (flags, decode_folder_name(name))
            for flags, _, name in listing
            if not any(flag.lower() == b"\\noselect" for flag in flags)
        ]

    # no-library: scikit-learn: list_folders lists IMAP mail folders, it is not a data split.
    def list_folders(self) -> list[str]:
        """Return every selectable folder name, decoded one by one so a bad name cannot fail the rest."""
        return [name for _, name in self._selectable()]

    def _gmail_trash(self) -> str:
        """Gmail's Trash folder (flagged \\Trash, RFC 6154), or "" when the server is not Gmail.

        Not imapclient's find_special_folder: it lists with folder names decoded all at once,
        so one malformed name fails it; _selectable decodes them one by one.
        """
        if self._trash is None:
            self._trash = (
                next((name for flags, name in self._selectable() if _TRASH_FLAG in map(bytes.lower, flags)), "")
                if self.supports_gmail_search()
                else ""
            )
        return self._trash

    def select(self, folder: str, readonly: bool) -> int:
        """Select `folder` (the name list_folders shows) and return its message count."""
        response: dict[bytes, Any] = self._live.select_folder(checked(folder), readonly=readonly)
        self._selected = folder
        return int(response[b"EXISTS"])

    def search(self, criteria: list[SearchItem]) -> list[int]:
        """Return the UIDs matching `criteria` in the selected folder."""
        for item in criteria:
            if isinstance(item, str) and not (item.isalpha() and item.isupper()):
                raise ValueError(f"{item!r} is not a search keyword; pass values through text()")
        needs_utf8: bool = any(isinstance(item, bytes) and not item.isascii() for item in criteria)
        return [int(uid) for uid in self._live.search(criteria, charset="UTF-8" if needs_utf8 else None)]

    def gmail_search(self, query: str) -> list[int]:
        """Return UIDs matching Gmail's own search syntax (X-GM-RAW)."""
        return [int(uid) for uid in self._live.gmail_search(text(query))]

    def exists(self, uid: int) -> bool:
        """Return True when `uid` is in the selected folder."""
        return uid in self.search(["UID", uid])

    def fetch_headers(self, uids: list[int]) -> dict[int, bytes]:
        """Return the raw headers of `uids` in one round trip, without marking them read."""
        if not uids:
            return {}
        response: dict[int, dict[bytes, Any]] = self._live.fetch(uids, [_HEADER_REQUEST])
        return {uid: items[_HEADER_KEY] for uid, items in response.items() if isinstance(items.get(_HEADER_KEY), bytes)}

    def fetch_message(self, uid: int) -> bytes | None:
        """Return the raw message `uid` without marking it read, or None when absent."""
        response: dict[int, dict[bytes, Any]] = self._live.fetch([uid], [_MESSAGE_REQUEST])
        found: Any = response.get(uid, {}).get(_MESSAGE_KEY)
        return found if isinstance(found, bytes) else None

    def append(self, folder: str, flags: tuple[str, ...], raw_message: bytes) -> None:
        """Append `raw_message` to `folder` with `flags`."""
        self._live.append(checked(folder), raw_message, flags=flags)

    def mark_deleted(self, uid: int) -> bool:
        """Delete `uid` from the selected folder; return True when it is gone.

        Gmail reads an expunge as "remove this label", so the message would stay in All Mail.
        There it moves to Trash and is expunged from Trash, Gmail's way to delete for good.
        """
        if not self.exists(uid):
            raise LookupError(f"no message with uid {uid} in this folder")
        trash: str = self._gmail_trash()
        if not trash or trash == self._selected:
            return self._expunge(uid)
        client: IMAPClient = self._live
        origin: str = self._selected
        message_id: Any = client.fetch([uid], [_GMAIL_MESSAGE_ID]).get(uid, {}).get(_GMAIL_MESSAGE_ID)
        if not isinstance(message_id, int):
            raise LookupError(f"no message with uid {uid} in this folder")
        client.move([uid], trash)
        try:
            self.select(trash, readonly=False)
            moved: list[int] = [int(found) for found in client.search([_GMAIL_MESSAGE_ID.decode(), message_id])]
            if not moved:
                raise LookupError("not found there after the move")
            for found in moved:
                self._expunge(found)
        except (IMAPClient.Error, OSError, LookupError) as failure:
            raise IMAPClient.Error(
                f"uid {uid} was moved to {trash!r} but not removed from it ({failure}); Gmail empties it after 30 days"
            ) from failure
        self.select(origin, readonly=False)
        return True

    def _expunge(self, uid: int) -> bool:
        """Flag and expunge `uid` in the selected folder; return True when it is gone.

        With UIDPLUS (Gmail, Dovecot, most servers) only `uid` is expunged. Without
        it, EXPUNGE would also purge every other message flagged \\Deleted, so it
        runs only when `uid` is the sole flagged one; otherwise `uid` stays flagged.
        """
        client: IMAPClient = self._live
        client.delete_messages([uid])
        if client.has_capability(_UID_EXPUNGE):
            client.uid_expunge([uid])
            return True
        if self.search(["DELETED"]) != [uid]:
            return False
        client.expunge()
        return True
