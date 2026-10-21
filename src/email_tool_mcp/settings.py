"""Which mailboxes this machine knows, and where their servers are.

Standard: per-user config folder from platformdirs, TOML via tomllib/tomli-w.
Placement: settings.py in the src layout (Python Packaging User Guide).

Holds addresses and hosts only; passwords live in the OS keyring
(`passwords.py`). A host that keeps secrets itself (a Claude Desktop extension,
say) can instead describe one mailbox entirely in `EMAIL_TOOL_*` variables.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import tomli_w
from platformdirs import user_config_path
from pydantic import ConfigDict, ValidationError
from pydantic.dataclasses import dataclass

APP_NAME: Final[str] = "email-tool"
SETTINGS_FILE: Final[str] = "mailboxes.toml"

ENV_NAME: Final[str] = "EMAIL_TOOL_NAME"
ENV_ADDRESS: Final[str] = "EMAIL_TOOL_ADDRESS"
ENV_IMAP_HOST: Final[str] = "EMAIL_TOOL_IMAP_HOST"
ENV_IMAP_PORT: Final[str] = "EMAIL_TOOL_IMAP_PORT"
ENV_SMTP_HOST: Final[str] = "EMAIL_TOOL_SMTP_HOST"
ENV_SMTP_PORT: Final[str] = "EMAIL_TOOL_SMTP_PORT"
ENV_PASSWORD: Final[str] = "EMAIL_TOOL_PASSWORD"

# Where a missing-password or no-mailbox message sends the user.
SETUP_COMMAND: Final[str] = "uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp add"

DEFAULT_IMAP_PORT: Final[int] = 993
DEFAULT_SMTP_PORT: Final[int] = 465


class SettingsError(ValueError):
    """Raised when the settings file or the EMAIL_TOOL_* variables are malformed."""


@dataclass(frozen=True, config=ConfigDict(extra="forbid", strict=True))
class Mailbox:
    """One mailbox: its address and its implicit-TLS IMAP and SMTP servers."""

    name: str
    address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int


def settings_path() -> Path:
    """Return the settings file for this user on this OS."""
    return user_config_path(APP_NAME, appauthor=False) / SETTINGS_FILE


def load_mailboxes(path: Path) -> dict[str, Mailbox]:
    """Return every mailbox in `path`, keyed by name; empty when the file is absent."""
    if not path.is_file():
        return {}
    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        tables: dict[str, dict[str, Any]] = document.get("mailboxes", {})
        return {name: Mailbox(name=name, **fields) for name, fields in tables.items()}
    except (tomllib.TOMLDecodeError, ValidationError, TypeError) as error:
        raise SettingsError(f"{path} is malformed: {error}") from error


def save_mailboxes(path: Path, mailboxes: Mapping[str, Mailbox]) -> None:
    """Write `mailboxes` to `path`, replacing its contents."""
    tables: dict[str, dict[str, Any]] = {}
    for name, mailbox in sorted(mailboxes.items()):
        fields: dict[str, Any] = asdict(mailbox)
        del fields["name"]
        tables[name] = fields
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps({"mailboxes": tables}), encoding="utf-8")


def environment_mailbox(environment: Mapping[str, str]) -> Mailbox | None:
    """Return the mailbox described by `EMAIL_TOOL_*` variables, or None when unset."""
    address: str = environment.get(ENV_ADDRESS, "").strip()
    if not address:
        return None
    missing: list[str] = [key for key in (ENV_IMAP_HOST, ENV_SMTP_HOST) if not environment.get(key, "").strip()]
    if missing:
        raise SettingsError(f"{ENV_ADDRESS} is set but {', '.join(missing)} is not")
    try:
        return Mailbox(
            name=environment.get(ENV_NAME, "").strip() or "default",
            address=address,
            imap_host=environment[ENV_IMAP_HOST].strip(),
            imap_port=int(environment.get(ENV_IMAP_PORT, "").strip() or DEFAULT_IMAP_PORT),
            smtp_host=environment[ENV_SMTP_HOST].strip(),
            smtp_port=int(environment.get(ENV_SMTP_PORT, "").strip() or DEFAULT_SMTP_PORT),
        )
    except ValueError as error:
        raise SettingsError(f"EMAIL_TOOL_* variables are invalid: {error}") from error
