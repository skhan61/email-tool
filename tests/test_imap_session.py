"""ImapSession over imapclient: safe deletes, safe search values, folder names that cannot break listing.

Standard: pytest with a stub standing in for the IMAPClient connection, plus imapclient's own criteria encoder.
Placement: tests/test_imap_session.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from imapclient import IMAPClient

# Private, but it is exactly what IMAPClient.search sends; pinned with imapclient==4.1.0.
from imapclient.imapclient import _literal, _normalise_search_criteria
from imapclient.response_parser import parse_response
from imapclient.response_types import BodyData

from email_tool_mcp.credentials import Credential
from email_tool_mcp.imap_session import ImapSession, SearchItem, decode_folder_name, text
from email_tool_mcp.text_parts import TextParts
from tests.conftest import WORK


class StubClient:
    """Records the IMAPClient calls ImapSession makes."""

    def __init__(self, uidplus: bool, flagged: list[int]) -> None:
        self.uidplus: bool = uidplus
        self.flagged: list[int] = flagged
        self.folder_encode: bool = True
        self.calls: list[tuple[str, Any]] = []

    def has_capability(self, name: str) -> bool:
        return name == "UIDPLUS" and self.uidplus

    def delete_messages(self, uids: list[int]) -> None:
        self.calls.append(("delete_messages", uids))

    def uid_expunge(self, uids: list[int]) -> None:
        self.calls.append(("uid_expunge", uids))

    def expunge(self) -> None:
        self.calls.append(("expunge", None))

    def search(self, criteria: list[SearchItem], charset: str | None = None) -> list[int]:
        self.calls.append(("search", (criteria, charset)))
        return self.flagged

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes, bytes]]:
        assert not self.folder_encode, "names must arrive raw so one bad name cannot fail the listing"
        return [
            ((b"\\HasNoChildren",), b"/", b"INBOX"),
            ((b"\\Noselect",), b"/", b"[Gmail]"),
            ((), b"/", b"Entw&APw-rfe"),
            ((), b"/", b"R&D"),
        ]


class GmailStub(StubClient):
    """A Gmail connection: X-GM-EXT-1, a Trash folder flagged \\Trash, and folders that can be selected."""

    def __init__(self, in_trash: list[int] | None = None) -> None:
        super().__init__(uidplus=True, flagged=[5])
        self.in_trash: list[int] = [41] if in_trash is None else in_trash

    def has_capability(self, name: str) -> bool:
        return name in ("UIDPLUS", "X-GM-EXT-1")

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes, bytes]]:
        self.calls.append(("list_folders", None))
        return [((b"\\HasNoChildren",), b"/", b"INBOX"), ((b"\\HasNoChildren", b"\\Trash"), b"/", b"[Gmail]/Trash")]

    def select_folder(self, folder: str, readonly: bool) -> dict[bytes, Any]:
        self.calls.append(("select_folder", folder))
        return {b"EXISTS": 1}

    def fetch(self, uids: list[int], items: list[bytes]) -> dict[int, dict[bytes, Any]]:
        return {uid: {b"X-GM-MSGID": 1797} for uid in uids}

    def move(self, uids: list[int], folder: str) -> None:
        self.calls.append(("move", (uids, folder)))

    def search(self, criteria: list[SearchItem], charset: str | None = None) -> list[int]:
        self.calls.append(("search", (criteria, charset)))
        return self.in_trash if criteria == ["X-GM-MSGID", 1797] else self.flagged


def session_over(client: StubClient) -> ImapSession:
    session: ImapSession = ImapSession(WORK, Credential(WORK.address, "secret", is_token=False))
    session._client = client
    return session


def test_uidplus_expunges_only_the_one_message() -> None:
    client: StubClient = StubClient(uidplus=True, flagged=[3, 5])
    assert session_over(client).mark_deleted(5)
    assert ("uid_expunge", [5]) in client.calls
    assert ("expunge", None) not in client.calls


@pytest.mark.parametrize(("flagged", "expected"), [([5], True), ([3, 5], False)], ids=["alone", "others flagged"])
def test_without_uidplus_expunges_only_when_alone(flagged: list[int], expected: bool) -> None:
    client: StubClient = StubClient(uidplus=False, flagged=flagged)
    assert session_over(client).mark_deleted(5) is expected
    assert (("expunge", None) in client.calls) is expected


def test_a_missing_uid_is_refused_before_anything_changes() -> None:
    client: StubClient = StubClient(uidplus=True, flagged=[])
    with pytest.raises(LookupError, match="uid 5"):
        session_over(client).mark_deleted(5)
    assert not any(name == "delete_messages" for name, _ in client.calls)


def test_folders_decode_one_by_one_and_noselect_is_hidden() -> None:
    client: StubClient = StubClient(uidplus=True, flagged=[])
    assert session_over(client).list_folders() == ["INBOX", "Entwürfe", "R&D"]
    assert client.folder_encode


def test_decode_folder_name_survives_bad_utf7() -> None:
    assert decode_folder_name(b"R&D") == "R&D"


@pytest.mark.parametrize("value", ["{12}", "(urgent)", "foo)", "*", "%"])
def test_syntax_looking_values_go_as_literals(value: str) -> None:
    sent: list[bytes] = _normalise_search_criteria(["SUBJECT", text(value)])
    assert isinstance(sent[1], _literal)


def test_dates_and_uids_stay_plain_imap_tokens() -> None:
    sent: list[bytes] = _normalise_search_criteria(["SINCE", date(2026, 1, 1), "UID", 5])
    assert sent == [b"SINCE", b"01-Jan-2026", b"UID", b"5"]


@pytest.mark.parametrize("value", ["x\r\nA1 DELETE Archive", "x\nfoo", "x\0"])
def test_line_breaks_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match="line breaks"):
        text(value)


def test_a_value_where_a_keyword_belongs_is_refused() -> None:
    with pytest.raises(ValueError, match="not a search keyword"):
        session_over(StubClient(uidplus=True, flagged=[])).search(["FROM", "jane"])


@pytest.mark.parametrize(("value", "charset"), [("invoice", None), ("Müller", "UTF-8")])
def test_search_declares_utf8_only_when_needed(value: str, charset: str | None) -> None:
    client: StubClient = StubClient(uidplus=True, flagged=[])
    session_over(client).search(["FROM", text(value)])
    assert client.calls[-1][1][1] == charset


def test_on_gmail_a_delete_moves_to_trash_and_is_expunged_there() -> None:
    """Gmail reads an expunge as "remove this label"; the message would stay in All Mail."""
    client: GmailStub = GmailStub()
    session: ImapSession = session_over(client)
    session.select("INBOX", readonly=False)
    assert session.mark_deleted(5)
    moves: list[tuple[str, Any]] = [
        call for call in client.calls if call[0] in ("move", "select_folder", "uid_expunge")
    ]
    assert moves == [
        ("select_folder", "INBOX"),
        ("move", ([5], "[Gmail]/Trash")),
        ("select_folder", "[Gmail]/Trash"),
        ("uid_expunge", [41]),
        ("select_folder", "INBOX"),
    ]


def test_in_gmail_trash_a_delete_expunges_at_once() -> None:
    client: GmailStub = GmailStub()
    session: ImapSession = session_over(client)
    session.select("[Gmail]/Trash", readonly=False)
    assert session.mark_deleted(5)
    assert ("uid_expunge", [5]) in client.calls
    assert not any(name == "move" for name, _ in client.calls)


def test_a_gmail_delete_that_stops_in_trash_says_so() -> None:
    """Not "flagged, pending deletion" in the inbox: the message is in Trash, which Gmail empties."""
    client: GmailStub = GmailStub(in_trash=[])
    session: ImapSession = session_over(client)
    session.select("INBOX", readonly=False)
    with pytest.raises(IMAPClient.Error, match=r"uid 5 was moved to '\[Gmail\]/Trash' but not removed"):
        session.mark_deleted(5)


def test_gmail_trash_is_looked_up_once_per_session() -> None:
    client: GmailStub = GmailStub()
    session: ImapSession = session_over(client)
    session.select("INBOX", readonly=False)
    session.mark_deleted(5)
    session.mark_deleted(5)
    assert [name for name, _ in client.calls].count("list_folders") == 1


PLAIN_LEAF: bytes = b'("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 5 1 NIL NIL NIL)'
HTML_LEAF: bytes = b'("text" "html" ("charset" "utf-8") NIL NIL "7bit" 12 1 NIL NIL NIL)'
PDF_LEAF: bytes = (
    b'("application" "pdf" ("name" "big.pdf") NIL NIL "base64" 99999999 NIL'
    b' ("attachment" ("filename" "big.pdf")) NIL NIL)'
)
# multipart/mixed [ multipart/alternative [ text/plain, text/html ], application/pdf attachment ]
MIXED_STRUCTURE: bytes = (
    b"(("
    + PLAIN_LEAF
    + HTML_LEAF
    + b' "alternative" ("boundary" "a") NIL NIL) '
    + PDF_LEAF
    + b' "mixed" ("boundary" "m") NIL NIL)'
)


class TextStub(StubClient):
    """Answers the two fetches fetch_text_parts makes, and records what was asked for."""

    def __init__(self, structure: bytes, serves_mime: bool = True) -> None:
        super().__init__(uidplus=True, flagged=[])
        self.serves_mime: bool = serves_mime
        self.structure: BodyData = BodyData.create(parse_response([structure])[0])
        self.requests: list[list[str]] = []
        self.fetch_nothing: bool = False

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        self.requests.append(items)
        if items[0] == "BODY.PEEK[HEADER]":
            return {uids[0]: {b"BODY[HEADER]": b"Subject: Plan\r\n\r\n", b"BODYSTRUCTURE": self.structure}}
        if self.fetch_nothing:
            return {}
        return {
            uids[0]: {
                item.replace(".PEEK", "").encode(): item.encode()
                for item in items
                if self.serves_mime or not item.endswith(".MIME]")
            }
        }


def test_only_the_text_parts_are_fetched_never_the_attachment() -> None:
    client: TextStub = TextStub(MIXED_STRUCTURE)
    fetched: TextParts | None = session_over(client).fetch_text_parts(7)
    assert fetched is not None
    assert client.requests[1] == ["BODY.PEEK[1.1]", "BODY.PEEK[1.1.MIME]"]
    assert [part.content for part in fetched.parts] == [b"BODY.PEEK[1.1]"]


def test_a_single_html_part_is_fetched_as_section_one() -> None:
    client: TextStub = TextStub(HTML_LEAF)
    assert session_over(client).fetch_text_parts(7) is not None
    assert client.requests[1] == ["BODY.PEEK[1]", "BODY.PEEK[1.MIME]"]


def test_a_server_without_mime_headers_still_quotes_from_the_structure() -> None:
    client: TextStub = TextStub(PLAIN_LEAF, serves_mime=False)
    fetched: TextParts | None = session_over(client).fetch_text_parts(7)
    assert fetched is not None
    assert (
        fetched.parts[0].mime == b'Content-Type: text/plain; charset="utf-8"\r\nContent-Transfer-Encoding: 7bit\r\n\r\n'
    )


def test_a_body_with_only_a_content_type_name_is_still_text() -> None:
    leaf: bytes = b'("text" "plain" ("charset" "utf-8" "name" "message.txt") NIL NIL "7bit" 5 1 NIL NIL NIL)'
    client: TextStub = TextStub(leaf)
    assert session_over(client).fetch_text_parts(7) is not None
    assert client.requests[1] == ["BODY.PEEK[1]", "BODY.PEEK[1.MIME]"]


def test_text_that_cannot_be_fetched_leaves_the_headers_alone() -> None:
    client: TextStub = TextStub(PLAIN_LEAF)
    client.fetch_nothing = True
    fetched: TextParts | None = session_over(client).fetch_text_parts(7)
    assert fetched is not None and fetched.parts == ()
