"""The bot-PR CLI. Argument parsing and nothing else.

    python -m tools.bot_pr discover                     # read the identity back
    python -m tools.bot_pr whoami                       # prove key + App ID work
    python -m tools.bot_pr push    --branch=feat/N-x    # push as the bot
    python -m tools.bot_pr open_pr --branch=feat/N-x --title="..." --body_file=/path
    python -m tools.bot_pr ready   --pr=N               # after the review is posted

The verbs and their flags are what CONTRIBUTING.md documents. They are
re-exported by `tools/bot_pr/__init__.py`; the logic lives in
`_github.py` and `_git.py`.
"""

from __future__ import annotations

import logging

import fire

from tools.bot_pr import discover, open_pr, push, ready, whoami

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    fire.Fire(
        {
            "discover": discover,
            "whoami": whoami,
            "push": push,
            "open_pr": open_pr,
            "ready": ready,
        }
    )
