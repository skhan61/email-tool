"""Run the documented install steps as a brand-new user and save each one's output as SVG.

Every command on docs/install.md and docs/mailboxes.md that needs no account runs in an
empty home folder, with uv installed by Astral's own script, so a step that only works on
a developer's machine fails here. Each step's real output becomes an SVG under
docs/assets/screens/, which the pages show.

LAYOUT
------
    _steps.py     the documented steps and the clean environment they run in
    _render.py    one step's command and output as an SVG terminal window (rich)
    __main__.py   `fire.Fire` over `run`, and nothing else
"""

from __future__ import annotations

from tools.clean_install._steps import run

__all__ = ["run"]
