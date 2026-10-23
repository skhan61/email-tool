"""The automatic first look at a new `user-report` issue (.github/workflows/first-look.yml).

The workflow does the GitHub calls with `gh`; this package makes the decisions, so they
are unit tested offline instead of living only in YAML.

Standard: a regular Python package run with `python -m`, laid out like `tools/bot_pr`.
Placement: tools/first_look/__init__.py re-exports the verbs; the logic is in the modules below.

LAYOUT
------
    _cap.py       the daily cap: has this issue had its look, and does this claim get a slot
    _comment.py   the one comment's text: running, limit reached, failed, and the result
    __main__.py   argument parsing over those, and nothing else

It runs on the runner's own `python3` with the standard library only, from the checkout
of `main`; nothing from the report is ever executed.
"""

from __future__ import annotations

from tools.first_look._cap import DAILY_CAP, already_looked, slot_granted
from tools.first_look._comment import MARKER, render_result, status_message

__all__: list[str] = ["DAILY_CAP", "MARKER", "already_looked", "render_result", "slot_granted", "status_message"]
