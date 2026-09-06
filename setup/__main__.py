"""Interactive credential setup for the email-tool plugin.

    python3 setup/__main__.py --mailbox gmail
    python3 setup/__main__.py --list

Prompts on the terminal, with the password hidden, verifies the login against
the real server, and only then writes the keys to the machine-local secrets
file at mode 600.

The password is read from the terminal and never appears in an argument, an
environment variable, or any output, so it cannot be captured by shell history,
a process listing, or a Claude Code transcript.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path
from typing import Final, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import secrets_file  # noqa: E402
from credential_check import check_imap, check_smtp  # noqa: E402
from mailbox_catalog import Mailbox, load  # noqa: E402

logger: Final[logging.Logger] = logging.getLogger("email-tool-setup")

_PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_MCP_CONFIG: Final[Path] = _PLUGIN_ROOT / ".mcp.json"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for setup."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="email-tool setup",
        description="Store credentials for one mailbox in the machine-local secrets file.",
    )
    parser.add_argument("--mailbox", help="Which mailbox to configure, as named in .mcp.json.")
    parser.add_argument("--list", action="store_true", help="Show every mailbox and whether it is configured.")
    return parser


def report(mailboxes: dict[str, Mailbox]) -> None:
    """Print each mailbox and whether this machine already has its keys."""
    for mailbox in mailboxes.values():
        present: set[str] = secrets_file.read_keys(mailbox.secrets_file)
        have: bool = mailbox.user_key in present and mailbox.password_key in present
        state: str = "configured" if have else "NOT configured"
        sys.stdout.write(f"  {mailbox.name:<12} {mailbox.imap_host:<28} {state}\n")


def configure(mailbox: Mailbox) -> int:
    """Prompt for one mailbox's credentials, verify them, then store them."""
    sys.stdout.write(f"\nConfiguring '{mailbox.name}' ({mailbox.imap_host})\n")
    sys.stdout.write(f"Credentials are stored in {mailbox.secrets_file} at mode 600.\n\n")

    user: str = input(f"  {mailbox.name} address: ").strip()
    if not user:
        logger.error("no address given, nothing written")
        return 2
    if mailbox.imap_host == "imap.gmail.com":
        sys.stdout.write("  Gmail needs a Google App Password, not your account password.\n")
    password: str = getpass.getpass("  password (hidden, not echoed): ").strip().replace(" ", "")
    if not password:
        logger.error("no password given, nothing written")
        return 2

    sys.stdout.write("\n  verifying against the real server...\n")
    imap_problem: str | None = check_imap(mailbox, user, password)
    if imap_problem is not None:
        logger.error("%s", imap_problem)
        logger.error("nothing was written")
        return 1
    sys.stdout.write("  IMAP  ok\n")

    smtp_problem: str | None = check_smtp(mailbox, user, password)
    if smtp_problem is not None:
        sys.stdout.write(f"  SMTP  FAILED: {smtp_problem}\n")
        sys.stdout.write("  Reading mail will work; sending will not.\n")
    else:
        sys.stdout.write("  SMTP  ok\n")

    secrets_file.write_keys(mailbox.secrets_file, {
        mailbox.user_key: user,
        mailbox.password_key: password,
    })
    sys.stdout.write(f"\n  saved {mailbox.user_key} and {mailbox.password_key}\n")
    sys.stdout.write("  restart Claude Code for the mailbox to appear.\n")
    return 0


def main(argv: Sequence[str]) -> int:
    """Run setup for the requested mailbox."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    namespace: argparse.Namespace = build_parser().parse_args(argv)

    try:
        mailboxes: dict[str, Mailbox] = load(_MCP_CONFIG, Path.home())
    except (OSError, ValueError) as error:
        logger.error("cannot read %s: %s", _MCP_CONFIG, error)
        return 2

    if namespace.list or namespace.mailbox is None:
        sys.stdout.write("\nMailboxes this plugin can reach:\n")
        report(mailboxes)
        sys.stdout.write("\nConfigure one with:  --mailbox <name>\n")
        return 0

    mailbox: Mailbox | None = mailboxes.get(namespace.mailbox)
    if mailbox is None:
        logger.error("unknown mailbox %r; known: %s", namespace.mailbox, ", ".join(sorted(mailboxes)))
        return 2
    return configure(mailbox)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
