"""ImapSession over imapclient: safe deletes, safe search values, folder names that cannot break listing.

Standard: pytest with a stub standing in for the IMAPClient connection, plus imapclient's own criteria encoder.
Placement: tests/test_imap_session.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

# Private, but it is exactly what IMAPClient.search sends; pinned with imapclient==4.1.0.
from imapclient.imapclient import _literal, _normalise_search_criteria

from email_tool_mcp.credentials import Credential
from email_tool_mcp.imap_session import ImapSession, SearchItem, decode_folder_name, text
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
