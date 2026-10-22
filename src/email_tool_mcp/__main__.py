"""Command line: `email-tool-mcp add|remove|list|serve|audit`. Arguments and dispatch only.

Standard: `fire` builds the CLI from these typed signatures; `[project.scripts]` installs it.
Placement: __main__.py, so `python -m email_tool_mcp` and the console script share one entry.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import fire

from email_tool_mcp.audit import AuditLog, verify
from email_tool_mcp.credentials import TokenSource
from email_tool_mcp.diagnose import check_mailbox
from email_tool_mcp.enrol import add_mailbox, add_microsoft_mailbox, describe_mailboxes, remove_mailbox
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import MicrosoftTokens
from email_tool_mcp.policy import Policy, policy_paths, show_rules
from email_tool_mcp.providers import open_book, token_sources
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT, settings_path


class AuditCommands:
    """Inspect the audit log of agent actions."""

    def path(self) -> str:
        """Print where the audit log is written."""
        return str(AuditLog.from_environment(os.environ, with_syslog=False).path)

    def verify(self) -> str:
        """Check the hash chain; report the first edited, inserted or removed record."""
        return verify(AuditLog.from_environment(os.environ, with_syslog=False).path).render()


class PolicyCommands:
    """Inspect the policy that limits what agents may do."""

    def paths(self) -> str:
        """Print the administrator's and the user's policy file locations."""
        paths: tuple[Path, Path] = policy_paths()
        return f"administrator: {paths[0]}\nuser:          {paths[1]}"

    def show(self, mailbox: str, address: str = "") -> str:
        """Print the effective rules for MAILBOX; its address is looked up unless given with --address."""
        return show_rules(Policy(policy_paths()), settings_path(), mailbox, address)


class Cli:
    """Email for any MCP client. Passwords live in the OS keyring."""

    def __init__(self) -> None:
        self.audit: AuditCommands = AuditCommands()
        self.policy: PolicyCommands = PolicyCommands()

    def add(
        self,
        name: str,
        address: str = "",
        imap_host: str = "",
        imap_port: int = DEFAULT_IMAP_PORT,
        smtp_host: str = "",
        smtp_port: int = DEFAULT_SMTP_PORT,
        auth: str = "password",
        client_id: str = "",
        tenant: str = "",
        cloud: str = "commercial",
        device_code: bool = False,
    ) -> str:
        """Add or replace mailbox NAME.

        --auth password (default): asks for anything not given, and always for the password.
        --auth microsoft: --address and --client-id; signs in in the browser (--device-code
        without one); --cloud gcc-high for GCC High; --tenant to pin a directory.
        """
        if auth == "microsoft":
            tokens: TokenSource = token_sources()["microsoft"]
            assert isinstance(tokens, MicrosoftTokens)
            return add_microsoft_mailbox(name, settings_path(), tokens, address, client_id, tenant, cloud, device_code)
        if auth != "password":
            raise ValueError(f"--auth must be password or microsoft, not {auth!r}")
        return add_mailbox(name, settings_path(), address, imap_host, imap_port, smtp_host, smtp_port)

    def remove(self, name: str) -> str:
        """Forget mailbox NAME and delete its password or sign-in."""
        return remove_mailbox(name, open_book(os.environ, with_policy=False), settings_path())

    def check(self, name: str) -> str:
        """Log in to mailbox NAME and report the TLS version, cipher and FIPS state actually in use."""
        book: MailboxBook = open_book(os.environ, with_policy=True)
        return check_mailbox(book, AuditLog.from_environment(os.environ, with_syslog=True), name)

    def list(self) -> str:
        """Show every mailbox on this machine."""
        return describe_mailboxes(open_book(os.environ, with_policy=False), settings_path())

    def serve(self) -> None:
        """Run the MCP server on stdio (what an AI agent launches)."""
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)
        book: MailboxBook = open_book(os.environ, with_policy=True)
        audit: AuditLog = AuditLog.from_environment(os.environ, with_syslog=True)
        build_server(book, audit).run("stdio")


def main() -> None:
    """Console-script entry point."""
    fire.Fire(Cli)


if __name__ == "__main__":
    main()
