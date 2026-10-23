"""The first look's daily cap, its comment text, and the workflow's read-only guarantees (#97).

Standard: pytest, offline: the comment lists are the JSON objects `gh api` returns, written
here by hand, and the workflow file is read as text.
Placement: tests/test_first_look.py, one test file per tool as in the rest of tests/.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.first_look import DAILY_CAP, MARKER, _verbs, already_looked, render_result, slot_granted, status_message

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
WORKFLOW: Path = REPO_ROOT / ".github" / "workflows" / "first-look.yml"
DAY: str = "2026-10-23"
BOT: str = "github-actions[bot]"
SHA: str = "0123456789abcdef0123456789abcdef01234567"


def comment(comment_id: int, created_at: str = f"{DAY}T10:00:00Z", login: str = BOT, body: str = "") -> dict[str, Any]:
    """One issue comment as the GitHub API returns it, with only the fields the cap reads."""
    text: str = body or status_message("running")
    return {"id": comment_id, "created_at": created_at, "user": {"login": login}, "body": text}


# --- the daily cap -----------------------------------------------------------------------------


def test_the_cap_is_three_a_day() -> None:
    assert DAILY_CAP == 3


@pytest.mark.parametrize("earlier", [0, 1, 2])
def test_a_claim_within_the_cap_runs(earlier: int) -> None:
    today: list[dict[str, Any]] = [comment(i) for i in range(1, earlier + 1)] + [comment(100)]
    assert slot_granted(today, 100, DAY)


def test_the_fourth_claim_of_the_day_does_not_run() -> None:
    today: list[dict[str, Any]] = [comment(1), comment(2), comment(3), comment(4)]
    assert not slot_granted(today, 4, DAY)


def test_claims_posted_together_grant_exactly_the_cap() -> None:
    # Five reports at once: every run sees the same five claims and ranks them the same way.
    today: list[dict[str, Any]] = [comment(i) for i in (50, 10, 40, 20, 30)]
    granted: list[int] = [i for i in (10, 20, 30, 40, 50) if slot_granted(today, i, DAY)]
    assert granted == [10, 20, 30]


def test_a_claim_not_yet_listed_still_ranks_after_earlier_ones() -> None:
    assert slot_granted([comment(1), comment(2)], 9, DAY)
    assert not slot_granted([comment(1), comment(2), comment(3)], 9, DAY)


def test_yesterdays_claims_do_not_count() -> None:
    # `since` filters on updated_at, so yesterday's claims edited today are in the list.
    yesterday: list[dict[str, Any]] = [comment(i, created_at="2026-10-22T23:59:59Z") for i in (1, 2, 3)]
    assert slot_granted([*yesterday, comment(9)], 9, DAY)


def test_text_a_reporter_types_cannot_use_up_slots() -> None:
    forged: list[dict[str, Any]] = [comment(i, login="mallory", body=MARKER) for i in (1, 2, 3)]
    assert slot_granted([*forged, comment(9)], 9, DAY)


def test_other_workflow_comments_do_not_count() -> None:
    others: list[dict[str, Any]] = [comment(i, body="CI passed") for i in (1, 2, 3)]
    assert slot_granted([*others, comment(9)], 9, DAY)


def test_malformed_comments_are_skipped() -> None:
    odd: list[dict[str, Any]] = [
        {"id": "1", "created_at": f"{DAY}T00:00:00Z", "user": {"login": BOT}, "body": MARKER},
        {"id": 2, "user": None, "body": MARKER},
        {"id": 3, "created_at": 5, "user": {"login": BOT}, "body": MARKER},
    ]
    assert slot_granted(odd, 9, DAY, cap=1)


def test_an_issue_with_its_comment_is_not_looked_at_twice() -> None:
    assert already_looked([comment(1, login="reporter", body="more detail"), comment(2)])
    assert already_looked([comment(2, body=status_message("limit"))])
    assert not already_looked([comment(1, login="reporter", body=MARKER)])
    assert not already_looked([])


# --- the comment text --------------------------------------------------------------------------


def full_result() -> dict[str, Any]:
    """A structured output as the workflow's JSON schema allows it."""
    return {
        "likely_cause": "The IMAP login fails because the app password expired.",
        "related_code": [
            {"path": "src/email_tool_mcp/imap_session.py", "line": 42, "why": "where login happens"},
            {"path": "README.md", "why": "app password steps"},
        ],
        "related_issues": [{"number": 12, "why": "same error"}],
    }


def test_every_status_message_carries_the_marker() -> None:
    texts: set[str] = {status_message("running"), status_message("limit"), status_message("failed")}
    assert len(texts) == 3
    assert all(text.startswith(MARKER) for text in texts)


def test_the_result_has_cause_code_links_and_issues() -> None:
    body: str = render_result(full_result(), "skhan61/email-tool", SHA, 97)
    assert body.startswith(MARKER)
    assert "The IMAP login fails because the app password expired." in body
    assert (
        f"[`src/email_tool_mcp/imap_session.py` line 42](https://github.com/skhan61/email-tool/blob/{SHA}"
        "/src/email_tool_mcp/imap_session.py#L42): where login happens"
    ) in body
    assert f"[`README.md`](https://github.com/skhan61/email-tool/blob/{SHA}/README.md): app password steps" in body
    assert "- #12: same error" in body


def test_empty_lists_say_none_found() -> None:
    body: str = render_result({"likely_cause": "Too little to tell."}, "o/r", SHA, 1)
    assert body.count("None found.") == 2


def test_no_likely_cause_is_an_error() -> None:
    with pytest.raises(ValueError):
        render_result({"likely_cause": "   ", "related_code": []}, "o/r", SHA, 1)


def test_mentions_cannot_ping_anyone() -> None:
    result: dict[str, Any] = full_result()
    result["likely_cause"] = "Ask @skhan61 and @org/team, mail a@b.c"
    result["related_issues"] = [{"number": 3, "why": "cc @someone"}]
    body: str = render_result(result, "o/r", SHA, 1)
    assert re.search(r"@[A-Za-z0-9_-]", body) is None
    assert "@\u200bskhan61" in body


@pytest.mark.parametrize(
    "path", ["../secrets", "/etc/passwd", "src/../x.py", "a//b.py", "src/x.py)](http://evil", "x y.py", ".git/config/"]
)
def test_unsafe_code_paths_are_dropped(path: str) -> None:
    result: dict[str, Any] = {"likely_cause": "c", "related_code": [{"path": path, "line": 1, "why": "w"}]}
    body: str = render_result(result, "o/r", SHA, 1)
    assert "**Related code**\n\nNone found." in body


def test_bad_issue_numbers_and_the_report_itself_are_dropped() -> None:
    issues: list[Any] = [{"number": 97}, {"number": True}, {"number": 0}, {"number": "5"}, "#6", {"number": 8}]
    body: str = render_result({"likely_cause": "c", "related_issues": issues}, "o/r", SHA, 97)
    assert re.findall(r"^- #(\d+)", body, flags=re.MULTILINE) == ["8"]


def test_lists_and_texts_are_cut_to_their_limits() -> None:
    result: dict[str, Any] = {
        "likely_cause": "x" * 5000,
        "related_issues": [{"number": n, "why": "y\n\n## heading " * 100} for n in range(1, 20)],
    }
    body: str = render_result(result, "o/r", SHA, 999)
    assert len(re.findall(r"^- #", body, flags=re.MULTILINE)) == 5
    assert "x" * 1500 not in body
    assert "\n## heading" not in body


# --- the CLI the workflow calls ----------------------------------------------------------------


def write_lines(path: Path, items: list[dict[str, Any]]) -> Path:
    """`items` as JSON lines, the way `gh api --paginate --jq '.[]'` writes them."""
    path.write_text("".join(json.dumps(item) + "\n" for item in items) + "\n", encoding="utf-8")
    return path


def test_verbs_read_the_files_the_workflow_writes(tmp_path: Path) -> None:
    today: Path = write_lines(tmp_path / "today.jsonl", [comment(1), comment(2), comment(3), comment(4)])
    assert _verbs.slot(today, 3, DAY) == "true"
    assert _verbs.slot(today, 4, DAY) == "false"
    assert _verbs.seen(today) == "true"
    assert _verbs.seen(write_lines(tmp_path / "none.jsonl", [])) == "false"
    result: Path = tmp_path / "result.json"
    result.write_text(json.dumps(full_result()), encoding="utf-8")
    assert _verbs.render(result, "o/r", SHA, 97).startswith(MARKER)


@pytest.mark.parametrize("text", ["", "[]", "not json"])
def test_render_rejects_a_missing_or_broken_result(tmp_path: Path, text: str) -> None:
    result: Path = tmp_path / "result.json"
    result.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        _verbs.render(result, "o/r", SHA, 1)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """`python -m tools.first_look ARGS` from the repository root, as the workflow runs it."""
    return subprocess.run(
        [sys.executable, "-m", "tools.first_look", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
    )


def test_the_cli_prints_what_the_workflow_reads(tmp_path: Path) -> None:
    today: Path = write_lines(tmp_path / "today.jsonl", [comment(1), comment(2)])
    assert run_cli("slot", str(today), "2", DAY).stdout == "true\n"
    assert run_cli("seen", str(today)).stdout == "true\n"
    assert run_cli("status", "limit").stdout == status_message("limit")
    empty: Path = tmp_path / "result.json"
    empty.write_text("", encoding="utf-8")
    assert run_cli("render", str(empty), "o/r", SHA, "1").returncode != 0


# --- the workflow ------------------------------------------------------------------------------


def test_the_workflow_runs_only_on_user_reports() -> None:
    text: str = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert "types: [opened, labeled]" in text
    assert "contains(github.event.issue.labels.*.name, 'user-report')" in text


def test_the_workflow_cannot_push_or_do_more_than_comment() -> None:
    text: str = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions: {}" in text
    granted: set[str] = set(re.findall(r"^\s+([a-z-]+): write$", text, flags=re.MULTILINE))
    assert granted == {"issues"}
    assert text.count("persist-credentials: false") == text.count("actions/checkout@")


def test_claude_gets_read_only_tools_and_no_write_token() -> None:
    text: str = WORKFLOW.read_text(encoding="utf-8")
    look: str = text.split("\n  look:\n", 1)[1].split("\n  comment:\n", 1)[0]
    assert "issues: write" not in look
    assert "--allowedTools Read,Grep,Glob\n" in look
    assert "--disallowedTools Bash,Edit,MultiEdit,Write,NotebookEdit,WebFetch,WebSearch\n" in look
    assert "--strict-mcp-config" in look
    # Read reaches outside the checkout; /proc/self/environ would hand over the OAuth token.
    assert "Read(//proc/**)" in look
    assert "Read(./.git/**)" in look
    # The report reaches Claude as a file, never pasted into the prompt.
    assert "github.event.issue.title" not in text
    assert "github.event.issue.body" not in text


def test_every_action_is_pinned_to_a_commit() -> None:
    uses: list[str] = re.findall(r"uses: (\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert uses
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref) for ref in uses), uses
