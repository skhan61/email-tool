"""The text of the one first-look comment: while running, when the cap is reached, on failure, and the result.

Standard: Claude Code's structured output (`--json-schema` in the workflow) gives a JSON
object; this module checks it field by field and writes GitHub-flavored Markdown. The
object comes from a model that read text anyone can write, so it is treated as untrusted:
unknown fields are ignored, code paths must be plain repository paths, issue references
must be numbers, and every text is cut to a length limit and shown only as code (a fenced
block or an inline code span, backticks removed), where GitHub renders no links, images,
HTML, `@` mentions or cross-repository references.
Placement: tools/first_look/_comment.py; `_cap.py` imports `MARKER` from here.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from typing import Any, Final, Literal, TypeAlias

MARKER: Final[str] = "<!-- email-tool-first-look -->"

Status: TypeAlias = Literal["running", "limit", "failed"]

_STATUS_TEXT: Final[dict[str, str]] = {
    "running": (
        "A first automatic look at this report is running. It reads the code and earlier issues "
        "only and changes nothing. Its result will replace this comment."
    ),
    "limit": "Today's automatic first looks are used up. The maintainer will read this report by hand.",
    "failed": "The automatic first look could not finish. The maintainer will read this report by hand.",
}

_MAX_ITEMS: Final[int] = 5
_MAX_CAUSE: Final[int] = 1500
_MAX_WHY: Final[int] = 300
_MAX_PATH: Final[int] = 200
_WRAP: Final[int] = 100
_PATH: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*")
_FOOTER: Final[str] = (
    "_Written by Claude from the code and earlier issues only, with read-only access. "
    "It may be wrong; the maintainer reads every report._"
)


def status_message(status: Status) -> str:
    """The comment body for a run that is still going, over the cap, or failed."""
    return f"{MARKER}\n{_STATUS_TEXT[status]}\n"


def _text(value: Any, limit: int) -> str:
    """`value` as one line of plain text with no backticks, at most `limit` characters."""
    if not isinstance(value, str):
        return ""
    flat: str = " ".join(value.replace("`", "'").split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def _code_span(text: str) -> str:
    """`text` as an inline code span, or nothing when it is empty."""
    return f": `{text}`" if text else ""


def _safe_path(value: Any) -> str | None:
    """`value` if it is a plain repository-relative path, else None."""
    if not isinstance(value, str) or len(value) > _MAX_PATH or not _PATH.fullmatch(value):
        return None
    parts: list[str] = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return value


def _positive_int(value: Any) -> int | None:
    """`value` if it is a positive integer (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _items(result: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """The first `_MAX_ITEMS` objects of the list `result[key]`, ignoring anything else."""
    raw: Any = result.get(key)
    if not isinstance(raw, list):
        return []
    found: list[Mapping[str, Any]] = [item for item in raw if isinstance(item, Mapping)]
    return found[:_MAX_ITEMS]


def render_result(result: Mapping[str, Any], repo: str, sha: str, issue: int) -> str:
    """The finished comment for `issue` from Claude's structured output.

    Code links point at `sha`, the commit Claude read, so they stay right after `main` moves.
    Raises ValueError when there is no likely cause, so the workflow posts the failed text.
    """
    cause: str = _text(result.get("likely_cause"), _MAX_CAUSE)
    if not cause:
        raise ValueError("the structured output has no likely_cause")

    code_lines: list[str] = []
    for item in _items(result, "related_code"):
        path: str | None = _safe_path(item.get("path"))
        if path is None:
            continue
        line: int | None = _positive_int(item.get("line"))
        anchor: str = f"#L{line}" if line is not None else ""
        label: str = f"`{path}` line {line}" if line is not None else f"`{path}`"
        code_why: str = _code_span(_text(item.get("why"), _MAX_WHY))
        code_lines.append(f"- [{label}](https://github.com/{repo}/blob/{sha}/{path}{anchor}){code_why}")

    issue_lines: list[str] = []
    for item in _items(result, "related_issues"):
        number: int | None = _positive_int(item.get("number"))
        if number is None or number == issue:
            continue
        issue_why: str = _code_span(_text(item.get("why"), _MAX_WHY))
        issue_lines.append(f"- #{number}{issue_why}")

    parts: list[str] = [
        MARKER,
        "### First automatic look",
        "",
        "**Likely cause**",
        "",
        "```text",
        textwrap.fill(cause, width=_WRAP),
        "```",
        "",
        "**Related code**",
        "",
        *(code_lines or ["None found."]),
        "",
        "**Related issues**",
        "",
        *(issue_lines or ["None found."]),
        "",
        _FOOTER,
        "",
    ]
    return "\n".join(parts)
