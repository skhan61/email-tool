"""Immutable per-mailbox configuration.

Split by sensitivity, on purpose:

- Host, port and label are plain arguments in `.mcp.json`. They are not secret
  and they belong in version control.
- The address and password arrive as environment variables, which Claude Code
  fills from `userConfig` in `plugin.json`. Anything marked `sensitive` there is
  masked on entry and kept in secure storage, never in `settings.json` and never
  in this repository.

Credentials are therefore never arguments, so they cannot appear in a process
listing, and never live in a file this plugin manages.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

USER_VARIABLE: Final[str] = "MAILBOX_USER"
PASSWORD_VARIABLE: Final[str] = "MAILBOX_PASSWORD"


class MailboxNotConfigured(RuntimeError):
    """Raised when this machine has no credentials for the mailbox."""


@dataclass(frozen=True)
class MailboxConfig:
    """Everything needed to reach one mailbox over IMAP and SMTP."""

    label: str
    imap_host: str
    imap_port: int
    imap_user: str
    smtp_host: str
    smtp_port: int
    password: str


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the mailbox MCP server."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="mailbox_mcp",
        description="Dependency-free IMAP/SMTP MCP server for a single mailbox.",
    )
    parser.add_argument("--label", required=True, help="Human name for this mailbox, used in logs.")
    parser.add_argument("--imap-host", required=True, help="IMAP hostname, also sent as the TLS SNI name.")
    parser.add_argument("--imap-port", required=True, type=int, help="IMAP port, normally 993.")
    parser.add_argument("--smtp-host", required=True, help="SMTP hostname, also sent as the TLS SNI name.")
    parser.add_argument("--smtp-port", required=True, type=int, help="Implicit-TLS SMTP port, normally 465.")
    return parser


def parse_config(argv: Sequence[str], environment: dict[str, str] | None = None) -> MailboxConfig:
    """Parse `argv` and take the credentials from the environment.

    Raises MailboxNotConfigured when either credential is absent or blank, which
    is the normal state for a mailbox the user chose not to configure on this
    machine.
    """
    namespace: argparse.Namespace = build_parser().parse_args(argv)
    source: dict[str, str] = dict(os.environ) if environment is None else environment

    imap_user: str = source.get(USER_VARIABLE, "").strip()
    password: str = source.get(PASSWORD_VARIABLE, "").strip().replace(" ", "")
    if not imap_user or not password:
        raise MailboxNotConfigured(
            f"mailbox {namespace.label!r} has no credentials on this machine; "
            f"run /plugin to set them, or leave it unconfigured to keep it off here"
        )

    return MailboxConfig(
        label=namespace.label,
        imap_host=namespace.imap_host,
        imap_port=namespace.imap_port,
        imap_user=imap_user,
        smtp_host=namespace.smtp_host,
        smtp_port=namespace.smtp_port,
        password=password,
    )
