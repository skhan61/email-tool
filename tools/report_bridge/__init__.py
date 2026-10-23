"""Emailed problem reports become GitHub issues, opened by the repository's bot (#96).

Standard: a package run with `python -m` (Python's `__main__.py` convention), as tools/bot_pr is.
Placement: tools/report_bridge/__init__.py, a maintainer tool beside tools/bot_pr and tools/clean_install.

`report_problem` (#93) emails a redacted report to the maintainer with a subject starting
`email-tool problem report:`. This reads the maintainer's mailbox on his own computer, through
email-tool's own settings and sign-ins, so no mailbox password leaves it, and opens one
`user-report` issue per report, with every address removed. It never deletes or moves mail.

LAYOUT
------
    _mail.py      the reports in one folder, and address removal
    _github.py    the `user-report` label and issues, as the bot (`tools.bot_pr`'s token)
    _run.py       one issue per new report, never two
    __main__.py   `fire.Fire` over `run`, and nothing else
"""

from __future__ import annotations

from tools.report_bridge._run import run

__all__: list[str] = ["run"]
