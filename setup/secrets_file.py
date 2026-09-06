"""Read and update the machine-local secrets file.

The file is a plain list of ``export KEY=VALUE`` lines. Updates rewrite it in
place at mode 600, preserving every key this run was not asked to change.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Final

logger: Final[logging.Logger] = logging.getLogger(__name__)

_EXPORT_PREFIX: Final[str] = "export "
_OWNER_ONLY: Final[int] = stat.S_IRUSR | stat.S_IWUSR


def read_keys(secrets_file: Path) -> set[str]:
    """Return the names of every key bound in `secrets_file`."""
    if not secrets_file.is_file():
        return set()
    names: set[str] = set()
    for raw_line in secrets_file.read_text(encoding="utf-8").splitlines():
        line: str = raw_line.strip().removeprefix(_EXPORT_PREFIX)
        if "=" in line and not line.startswith("#"):
            names.add(line.split("=", 1)[0].strip())
    return names


def write_keys(secrets_file: Path, values: dict[str, str]) -> None:
    """Bind every key in `values`, leaving other keys untouched.

    Written through a mode-600 temporary file in the same directory and then
    renamed, so the secret is never briefly world-readable and a crash cannot
    leave a half-written file.
    """
    secrets_file.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = (
        secrets_file.read_text(encoding="utf-8").splitlines() if secrets_file.is_file() else []
    )
    kept: list[str] = [
        line for line in existing
        if line.strip().removeprefix(_EXPORT_PREFIX).split("=", 1)[0].strip() not in values
    ]
    while kept and not kept[-1].strip():
        kept.pop()
    body: str = "\n".join(kept + [f"{_EXPORT_PREFIX}{key}={value}" for key, value in values.items()])

    handle, temporary_name = tempfile.mkstemp(dir=str(secrets_file.parent), prefix=".secrets-")
    temporary: Path = Path(temporary_name)
    try:
        os.chmod(handle, _OWNER_ONLY)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body.strip() + "\n")
        temporary.replace(secrets_file)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    secrets_file.chmod(_OWNER_ONLY)
    logger.info("wrote %d key(s) to %s (mode 600)", len(values), secrets_file)
