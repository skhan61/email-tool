"""`python -m tools.clean_install run [--source=PATH] [--out=docs/assets/screens]`."""

from __future__ import annotations

import logging

import fire

from tools.clean_install import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    fire.Fire({"run": run})
