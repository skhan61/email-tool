"""The four CLI verbs: read the files the workflow wrote, decide, and return the text to print.

Standard: JSON Lines input, as `gh api --paginate ... --jq '.[]'` writes it (one object per line).
Placement: tools/first_look/_verbs.py; `__main__.py` parses the arguments and prints the return value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.first_look._cap import already_looked, slot_granted
from tools.first_look._comment import Status, render_result, status_message


def _lines(path: Path) -> list[dict[str, Any]]:
    """The JSON objects in `path`, one per non-empty line."""
    text: str = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def seen(comments: Path) -> str:
    """`true` when the issue whose comments are in `comments` already has its first look."""
    return str(already_looked(_lines(comments))).lower()


def slot(comments: Path, claim_id: int, day: str) -> str:
    """`true` when claim `claim_id` of UTC date `day` is within the daily cap."""
    return str(slot_granted(_lines(comments), claim_id, day)).lower()


def status(name: Status) -> str:
    """The comment body for `name` (running, limit or failed)."""
    return status_message(name)


def render(result: Path, repo: str, sha: str, issue: int) -> str:
    """The finished comment from Claude's structured output in `result`.

    Raises ValueError when the file is not a JSON object or has no likely cause.
    """
    data: Any = json.loads(result.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the structured output is not a JSON object")
    return render_result(data, repo, sha, issue)
