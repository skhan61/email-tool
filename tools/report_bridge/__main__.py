"""`python -m tools.report_bridge run [--mailbox=NAME] [--folder=INBOX] [--dry-run]`.

Standard: fire over the package's one verb, as tools/bot_pr and tools/clean_install do.
Placement: tools/report_bridge/__main__.py, Python's entry point for `python -m`; argument parsing only.
"""

from __future__ import annotations

import logging

import fire

from tools.report_bridge import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    fire.Fire({"run": run})
