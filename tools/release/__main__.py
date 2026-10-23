"""`python -m tools.release prepare --part=patch|minor|major`, then open the PR with `tools.bot_pr`.

Standard: python-fire turns the function into the command line, as in tools/bot_pr.
Placement: tools/release/__main__.py, the entry point `python -m` runs; argument parsing only.
"""

from __future__ import annotations

import logging

import fire

from tools.release import prepare

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    fire.Fire({"prepare": prepare})
