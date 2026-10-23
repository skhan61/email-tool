"""Live tests use this computer's real mailboxes: the real keyring, settings and sign-ins.

Standard: a nested conftest.py whose fixture overrides the parent's fixture of the same name.
Placement: tests/live/conftest.py, so the override reaches tests/live only.

tests/conftest.py replaces the keyring with an in-memory one for every test, which is right
for every test but these: here the real mailboxes must log in. The tests themselves are
skipped unless EMAIL_TOOL_LIVE=1, so CI and ordinary runs never reach a real mailbox.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[None]:
    """Keep the real keyring: overrides tests/conftest.py's in-memory one for this folder only."""
    yield
