"""Read one secret out of a machine-local `export KEY=VALUE` secrets file.

Deliberately does NOT consult os.environ. The shell is not on the path between
this server and the password, so a Claude Code process launched from a context
that never sourced the secrets file cannot silently lose its credentials.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

logger: Final[logging.Logger] = logging.getLogger(__name__)

_EXPORT_PREFIX: Final[str] = "export "


def read_secret(secrets_file: Path, key: str) -> str:
    """Return the value bound to `key` in `secrets_file`.

    Raises FileNotFoundError if the file is absent, KeyError if the key is not
    bound or is bound to an empty value. Values are stripped of surrounding
    quotes and of the spaces Google renders app passwords with.
    """
    if not secrets_file.is_file():
        raise FileNotFoundError(f"secrets file not found: {secrets_file}")

    raw_text: str = secrets_file.read_text(encoding="utf-8")
    for raw_line in raw_text.splitlines():
        line: str = raw_line.strip()
        if line.startswith(_EXPORT_PREFIX):
            line = line[len(_EXPORT_PREFIX) :]
        if "=" not in line or line.startswith("#"):
            continue
        candidate_key, _, candidate_value = line.partition("=")
        if candidate_key.strip() != key:
            continue
        value: str = candidate_value.strip().strip('"').strip("'").replace(" ", "")
        if not value:
            raise KeyError(f"key {key!r} is bound to an empty value in {secrets_file}")
        logger.debug("resolved secret %s from %s", key, secrets_file)
        return value

    raise KeyError(f"key {key!r} not found in {secrets_file}")
