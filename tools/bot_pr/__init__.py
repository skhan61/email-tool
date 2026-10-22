"""Open a pull request as the repository's GitHub App, never as a person.

WHY THIS PACKAGE EXISTS
-----------------------
GitHub forbids approving your own pull request. So a PR opened with the owner's
account makes the one required approval unsatisfiable BY THE OWNER: the only way
left to merge is for an agent holding his token to approve on his behalf. The
rule does not merely lapse, it INVERTS, and "the owner reviews and approves"
becomes "the agent approves its own work".

That is not hypothetical. It happened in the repository this template was
extracted from, and nothing caught it, because the whole procedure lived in one
session's context: no script, no documentation, not even the App ID written
down. This package is that procedure, on disk, where amnesia cannot reach it.
The `PR opened by the bot` gate in `.github/workflows/gates.yml` is the other
half, and it fails closed.

LAYOUT
------
    _identity.py  who the bot is, where its key lives, `BotError`
    _github.py    the four verbs and the token, through PyGithub (toolpath#129)
    _git.py       the merge-base range, filter-branch, `push`
    __main__.py   `fire.Fire` over those verbs, and nothing else

`owner` and `repo` are derived from `git remote get-url origin`, so adopting
this template cannot leave the tooling pointed at the repository it came from.
Everything else is configured under `[tool.bot_pr]` in `pyproject.toml` and
ships empty; `discover` reads all of it back from the API.
"""

from __future__ import annotations

from tools.bot_pr._git import push
from tools.bot_pr._github import discover, open_pr, ready, whoami
from tools.bot_pr._identity import BotError

__all__ = ["BotError", "discover", "open_pr", "push", "ready", "whoami"]
