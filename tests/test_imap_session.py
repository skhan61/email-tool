"""ImapSession over imapclient: safe deletes, selectable folders, UTF-8 search.

Standard: pytest with a stub standing in for the IMAPClient connection the session wraps.
Placement: tests/test_imap_session.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from typing import Any

import pytest

from email_tool_mcp.imap_session import ImapSession
from tests.conftest import WORK


class StubClient:
    """Records the IMAPClient calls ImapSession makes."""

    def __init__(self, uidplus: bool, flagged: list[int]) -> None:
        self.uidplus: bool = uidplus
        self.flagged: list[int] = flagged
        self.calls: list[tuple[str, Any]] = []

    def has_capability(self, name: str) -> bool:
        return name == "UIDPLUS" and self.uidplus

    def delete_messages(self, uids: list[int]) -> None:
        self.calls.append(("delete_messages", uids))

    def uid_expunge(self, uids: list[int]) -> None:
        self.calls.append(("uid_expunge", uids))

    def expunge(self) -> None:
        self.calls.append(("expunge", None))

    def search(self, criteria: list[str], charset: str | None = None) -> list[int]:
        self.calls.append(("search", (criteria, charset)))
        return self.flagged

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes, str]]:
        return [((b"\\HasNoChildren",), b"/", "INBOX"), ((b"\\Noselect",), b"/", "[Gmail]"), ((), b"/", "Entwürfe")]


def session_over(client: StubClient) -> ImapSession:
    session: ImapSession = ImapSession(WORK, "secret")
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


def test_noselect_folders_are_hidden_and_names_stay_decoded() -> None:
    assert session_over(StubClient(uidplus=True, flagged=[])).list_folders() == ["INBOX", "Entwürfe"]


@pytest.mark.parametrize(("value", "charset"), [("invoice", None), ("Müller", "UTF-8")])
def test_search_declares_utf8_only_when_needed(value: str, charset: str | None) -> None:
    client: StubClient = StubClient(uidplus=True, flagged=[])
    session_over(client).search(["FROM", value])
    assert client.calls[-1] == ("search", (["FROM", value], charset))
