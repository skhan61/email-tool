"""Immutable per-mailbox configuration, built from explicit arguments.

Every value is required. There are no defaults, so a mailbox is never reached
over a host, port or account that nobody chose.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from credentials import read_secret


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
    parser.add_argument("--user-key", required=True, help="Key inside the secrets file holding the mailbox login.")
    parser.add_argument("--smtp-host", required=True, help="SMTP hostname, also sent as the TLS SNI name.")
    parser.add_argument("--smtp-port", required=True, type=int, help="Implicit-TLS SMTP port, normally 465.")
    parser.add_argument("--secrets-file", required=True, type=Path, help="Path to the machine-local secrets file.")
    parser.add_argument("--password-key", required=True, help="Key inside the secrets file holding the password.")
    return parser


def parse_config(argv: Sequence[str]) -> MailboxConfig:
    """Parse `argv` and resolve the mailbox password from the secrets file."""
    parser: argparse.ArgumentParser = build_parser()
    namespace: argparse.Namespace = parser.parse_args(argv)
    secrets_file: Path = Path(namespace.secrets_file).expanduser()
    password: str = read_secret(secrets_file, namespace.password_key)
    imap_user: str = read_secret(secrets_file, namespace.user_key)
    return MailboxConfig(
        label=namespace.label,
        imap_host=namespace.imap_host,
        imap_port=namespace.imap_port,
        imap_user=imap_user,
        smtp_host=namespace.smtp_host,
        smtp_port=namespace.smtp_port,
        password=password,
    )
