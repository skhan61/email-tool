"""The first-look CLI for .github/workflows/first-look.yml. Argument parsing and nothing else.

    python3 -m tools.first_look seen    ISSUE_COMMENTS.jsonl          # prints true/false
    python3 -m tools.first_look slot    TODAY_COMMENTS.jsonl ID DAY   # prints true/false
    python3 -m tools.first_look status  running|limit|failed          # prints a comment body
    python3 -m tools.first_look render  RESULT.json REPO SHA ISSUE    # prints a comment body

Standard: the standard library's `argparse` behind `python -m`; not `fire` (as `tools.bot_pr`
uses), because the runner's own `python3` has no project packages installed.
Placement: tools/first_look/__main__.py; the verbs live in `_verbs.py` and `_comment.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.first_look import _verbs, status_message

if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog="python3 -m tools.first_look")
    verbs: argparse._SubParsersAction[argparse.ArgumentParser] = parser.add_subparsers(dest="verb", required=True)
    seen: argparse.ArgumentParser = verbs.add_parser("seen")
    seen.add_argument("comments", type=Path)
    slot: argparse.ArgumentParser = verbs.add_parser("slot")
    slot.add_argument("comments", type=Path)
    slot.add_argument("claim_id", type=int)
    slot.add_argument("day")
    status: argparse.ArgumentParser = verbs.add_parser("status")
    status.add_argument("name", choices=["running", "limit", "failed"])
    render: argparse.ArgumentParser = verbs.add_parser("render")
    render.add_argument("result", type=Path)
    render.add_argument("repo")
    render.add_argument("sha")
    render.add_argument("issue", type=int)
    args: argparse.Namespace = parser.parse_args()

    output: str
    if args.verb == "seen":
        output = _verbs.seen(args.comments) + "\n"
    elif args.verb == "slot":
        output = _verbs.slot(args.comments, args.claim_id, args.day) + "\n"
    elif args.verb == "status":
        output = status_message(args.name)
    else:
        output = _verbs.render(args.result, args.repo, args.sha, args.issue)
    sys.stdout.write(output)
