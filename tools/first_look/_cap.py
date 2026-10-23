"""The daily cap on first looks, decided from the comments the workflow has already posted.

Standard: GitHub's issue comments API as the only state. Each run first posts its own
comment (the claim), then ranks every claim created that UTC day by comment id, which
GitHub assigns in increasing order. A claim among the first `DAILY_CAP` gets a Claude run;
a later one is told the limit is reached. Two runs that start together still agree,
because both rank the same ids, so no lock or stored counter is needed.
A claim is recognised by `MARKER` in a comment written by the workflow's own token
(`github-actions[bot]`), so text a reporter types cannot use up or free a slot.
Placement: tools/first_look/_cap.py; the workflow feeds it `gh api` output as JSON lines.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from tools.first_look._comment import MARKER

DAILY_CAP: Final[int] = 3
WORKFLOW_LOGIN: Final[str] = "github-actions[bot]"


def is_claim(comment: Mapping[str, Any]) -> bool:
    """Whether `comment` is a first-look comment posted by the workflow itself."""
    user: Any = comment.get("user")
    login: Any = user.get("login") if isinstance(user, Mapping) else None
    body: Any = comment.get("body")
    return login == WORKFLOW_LOGIN and isinstance(body, str) and MARKER in body


def already_looked(comments: Iterable[Mapping[str, Any]]) -> bool:
    """Whether the issue already has a first-look comment, so this run must not add another.

    An issue opened with the label fires both `opened` and `labeled`; the second run sees
    the first one's comment here and stops.
    """
    return any(is_claim(comment) for comment in comments)


def slot_granted(comments: Iterable[Mapping[str, Any]], claim_id: int, day: str, cap: int = DAILY_CAP) -> bool:
    """Whether the claim `claim_id`, posted on UTC date `day` (YYYY-MM-DD), is within today's cap.

    `comments` is the repository's comments created that day or earlier; only claims whose
    `created_at` falls on `day` count. The claim itself may be missing from a list fetched
    a moment after it was posted; it still ranks after every claim with a smaller id.
    """
    earlier: set[int] = set()
    for comment in comments:
        created: Any = comment.get("created_at")
        comment_id: Any = comment.get("id")
        if not is_claim(comment) or not isinstance(created, str) or not isinstance(comment_id, int):
            continue
        if created.startswith(f"{day}T") and comment_id < claim_id:
            earlier.add(comment_id)
    return len(earlier) < cap
