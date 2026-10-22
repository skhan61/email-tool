"""Open a pull request as the repository's GitHub App, never as a person.

WHY THIS PACKAGE EXISTS
-----------------------
GitHub forbids approving your own pull request. So a PR opened with the owner's
account makes the one required approval unsatisfiable BY THE OWNER: the only way
left to merge is for an agent holding his token to approve on his behalf. The
rule does not merely lapse, it INVERTS, and "the owner reviews and approves"
becomes "the agent approves its own work".

Copied from skhan61/project-template. The `PR not opened by the owner` and
`code review posted` gates in `.github/workflows/gates.yml` are the other half,
and they fail closed; CONTRIBUTING.md describes the flow.

LAYOUT
------
    _identity.py  who the bot is, where its key lives, `BotError`
    _github.py    the four verbs and the token, through PyGithub (toolpath#129)
    _git.py       the merge-base range, filter-branch, `push`
    __main__.py   `fire.Fire` over those verbs, and nothing else

`owner` and `repo` are derived from `git remote get-url origin`. The shared app's
numbers live in ~/.config/github-apps/bot.toml; `discover` reads them back from
the API.
"""

from __future__ import annotations

from tools.bot_pr._git import push
from tools.bot_pr._github import discover, open_pr, ready, whoami
from tools.bot_pr._identity import BotError

__all__: list[str] = ["BotError", "discover", "open_pr", "push", "ready", "whoami"]
