"""Read the mailbox definitions out of the plugin's own .mcp.json.

Single source of truth: `.mcp.json` already states every mailbox, its hosts and
the secrets keys it reads. Setup derives its questions from that file rather
than repeating the list, so adding a mailbox stays a one-file change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Mailbox:
    """One mailbox the plugin knows how to reach."""

    name: str
    label: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    user_key: str
    password_key: str
    secrets_file: Path


def _flags(args: list[str]) -> dict[str, str]:
    """Turn a flat ``--flag value`` argument list into a mapping."""
    pairs: dict[str, str] = {}
    for index in range(0, len(args) - 1):
        token: str = args[index]
        if token.startswith("--"):
            pairs[token[2:]] = args[index + 1]
    return pairs


def load(mcp_config: Path, home: Path) -> dict[str, Mailbox]:
    """Return every mailbox declared in `mcp_config`, keyed by server name.

    `${HOME}` and `${CLAUDE_PLUGIN_ROOT}` appear in the file verbatim, so
    `home` is substituted here to produce a real secrets-file path.
    """
    raw: dict[str, Any] = json.loads(mcp_config.read_text(encoding="utf-8"))
    mailboxes: dict[str, Mailbox] = {}
    for name, server in raw.get("mcpServers", {}).items():
        flags: dict[str, str] = _flags(server.get("args", []))
        missing: list[str] = [
            key for key in ("label", "imap-host", "imap-port", "smtp-host", "smtp-port",
                            "user-key", "password-key", "secrets-file")
            if key not in flags
        ]
        if missing:
            raise ValueError(f"server {name!r} in {mcp_config} is missing {missing}")
        secrets: str = flags["secrets-file"].replace("${HOME}", str(home))
        mailboxes[name] = Mailbox(
            name=name,
            label=flags["label"],
            imap_host=flags["imap-host"],
            imap_port=int(flags["imap-port"]),
            smtp_host=flags["smtp-host"],
            smtp_port=int(flags["smtp-port"]),
            user_key=flags["user-key"],
            password_key=flags["password-key"],
            secrets_file=Path(secrets).expanduser(),
        )
    return mailboxes
