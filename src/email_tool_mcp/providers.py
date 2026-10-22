"""The sign-in providers this version supports, as TokenSources keyed by `Mailbox.auth`.

Standard: one registry the CLI and the server share, so every entry point offers the same providers.
Placement: providers.py, built by __main__.py and passed into MailboxBook.
"""

from __future__ import annotations

from collections.abc import Mapping

from email_tool_mcp.credentials import TokenSource
from email_tool_mcp.google import PROVIDER as GOOGLE
from email_tool_mcp.google import GoogleTokens
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import PROVIDER as MICROSOFT
from email_tool_mcp.microsoft import MicrosoftTokens
from email_tool_mcp.policy import Policy, policy_paths
from email_tool_mcp.settings import settings_path
from email_tool_mcp.token_store import TokenStore, default_store_directory


def microsoft_tokens() -> MicrosoftTokens:
    """Microsoft sign-ins, kept in this user's encrypted sign-in store."""
    return MicrosoftTokens(TokenStore(default_store_directory()))


def google_tokens() -> GoogleTokens:
    """Google sign-ins, kept in this user's encrypted sign-in store."""
    return GoogleTokens(TokenStore(default_store_directory()))


def token_sources() -> dict[str, TokenSource]:
    """Every provider."""
    return {MICROSOFT: microsoft_tokens(), GOOGLE: google_tokens()}


def open_book(environment: Mapping[str, str], with_policy: bool) -> MailboxBook:
    """The mailbox book every command uses: this user's settings, every provider, and policy if asked."""
    policy: Policy | None = Policy(policy_paths()) if with_policy else None
    return MailboxBook(settings_path(), environment, policy=policy, token_sources=token_sources())
