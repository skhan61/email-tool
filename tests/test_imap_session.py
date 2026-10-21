"""`mark_deleted` never purges another message's pending deletion.

Standard: pytest with a stub standing in for the imaplib connection the session wraps.
Placement: tests/test_imap_session.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import pytest

from email_tool_mcp.imap_session import ImapSession
from tests.conftest import WORK


class StubConnection:
    """Answers UID STORE / UID SEARCH DELETED and records EXPUNGE."""

    def __init__(self, flagged: list[int]) -> None:
        self.flagged: list[int] = flagged
        self.expunged: bool = False

    def uid(self, command: str, *args: str) -> tuple[str, list[bytes]]:
        if command == "SEARCH":
            return ("OK", [" ".join(str(uid) for uid in self.flagged).encode()])
        return ("OK", [b""])

    def expunge(self) -> tuple[str, list[None]]:
        self.expunged = True
        return ("OK", [None])


@pytest.mark.parametrize(("flagged", "expected"), [([5], True), ([3, 5], False)], ids=["alone", "others flagged"])
def test_expunges_only_when_the_message_is_the_only_one_flagged(flagged: list[int], expected: bool) -> None:
    session: ImapSession = ImapSession(WORK, "secret")
    stub: StubConnection = StubConnection(flagged)
    session._connection = stub  # type: ignore[assignment]
    assert session.mark_deleted(5) is expected
    assert stub.expunged is expected
