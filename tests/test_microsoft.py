"""Microsoft sign-in: presets, silent refresh, wrong-account refusal, encrypted storage, add and remove.

Standard: pytest; a fake MSAL application stands in for Microsoft's servers, with the real
msal.SerializableTokenCache and the real encrypted TokenStore.
Placement: tests/test_microsoft.py, beside microsoft.py, token_store.py and the add flow in enrol.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import msal
import pytest

from email_tool_mcp.credentials import Credential
from email_tool_mcp.enrol import add_microsoft_mailbox, describe_mailboxes, remove_mailbox
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import MicrosoftTokens, SignInRequired, cloud_of, preset, scopes_for
from email_tool_mcp.settings import Mailbox, load_mailboxes
from email_tool_mcp.token_store import TokenStore

ADDRESS: str = "sayem@outlook.com"


class FakeMsal:
    """Records calls; the token cache it is given is the real MSAL cache, so storage is real."""

    instances: list[FakeMsal] = []

    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        self.client_id: str = client_id
        self.authority: str = authority
        self.cache: msal.SerializableTokenCache = cache
        self.signed_in_as: str = ADDRESS
        self.silent: dict[str, Any] | None = {"access_token": "fresh-token"}
        FakeMsal.instances.append(self)

    def get_accounts(self, username: str | None = None) -> list[dict[str, Any]]:
        stored: list[dict[str, Any]] = list(self.cache.search(msal.TokenCache.CredentialType.ACCOUNT))
        return [account for account in stored if username is None or account["username"].lower() == username.lower()]

    def acquire_token_silent(self, scopes: list[str], account: dict[str, Any]) -> dict[str, Any] | None:
        return self.silent

    def _signed_in(self, scopes: list[str]) -> dict[str, Any]:
        self.cache.add(
            {
                "client_id": self.client_id,
                "scope": scopes,
                "token_endpoint": f"{self.authority}/oauth2/v2.0/token",
                "response": {
                    "access_token": "first-token",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "client_info": "eyJ1aWQiOiJ1IiwidXRpZCI6InQifQ",
                    "token_type": "Bearer",
                },
                "environment": "login.microsoftonline.com",
                "realm": "consumers",
                "username": self.signed_in_as,
                "home_account_id": "u.t",
                "local_account_id": "u",
                "authority_type": "MSSTS",
            }
        )
        return {"access_token": "first-token", "id_token_claims": {"preferred_username": self.signed_in_as}}

    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]:
        return self._signed_in(scopes)

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]:
        return {"user_code": "ABCD", "message": "Go to https://microsoft.com/devicelogin and enter ABCD"}

    def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        return self._signed_in(scopes_for(cloud_of(OUTLOOK)))


OUTLOOK: Mailbox = preset("outlook", ADDRESS, "client-123", "", "commercial")


@pytest.fixture
def tokens(tmp_path: Path) -> MicrosoftTokens:
    FakeMsal.instances = []
    return MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), FakeMsal)


def accept(mailbox: Mailbox, credential: Credential) -> None:
    assert credential.is_token and credential.secret == "fresh-token"


def test_presets_pick_servers_and_directory_for_each_kind_of_account() -> None:
    assert (OUTLOOK.imap_host, OUTLOOK.smtp_host, OUTLOOK.smtp_port, OUTLOOK.tenant) == (
        "outlook.office365.com",
        "smtp-mail.outlook.com",
        587,
        "consumers",
    )
    work: Mailbox = preset("w", "me@contoso.com", "c", "", "commercial")
    assert (work.smtp_host, work.tenant) == ("smtp.office365.com", "organizations")
    gcc: Mailbox = preset("g", "me@agency.us", "c", "tenant-id", "gcc-high")
    assert (gcc.imap_host, gcc.smtp_host, gcc.tenant) == ("outlook.office365.us", "smtp.office365.us", "tenant-id")
    assert scopes_for(cloud_of(gcc)) == [
        "https://outlook.office365.us/IMAP.AccessAsUser.All",
        "https://outlook.office365.us/SMTP.Send",
    ]
    with pytest.raises(ValueError):
        preset("x", "me@outlook.com", "c", "", "gcc-high")


@pytest.mark.parametrize("device_code", [False, True])
def test_sign_in_then_silent_tokens(tokens: MicrosoftTokens, device_code: bool) -> None:
    shown: list[str] = []
    tokens.sign_in(OUTLOOK, device_code, shown.append)
    assert tokens.is_signed_in(OUTLOOK)
    assert tokens.access_token(OUTLOOK) == "fresh-token"
    assert FakeMsal.instances[0].authority == "https://login.microsoftonline.com/consumers"
    assert ("ABCD" in shown[0]) is device_code


class OtherAccount(FakeMsal):
    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        super().__init__(client_id, authority, cache)
        self.signed_in_as = "someone.else@outlook.com"


class Expired(FakeMsal):
    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        super().__init__(client_id, authority, cache)
        self.silent = {"error": "invalid_grant", "error_description": "AADSTS70043: refresh token expired\nTrace"}


def test_signing_in_as_another_account_is_refused_and_nothing_is_stored(tmp_path: Path) -> None:
    tokens: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), OtherAccount)
    with pytest.raises(RuntimeError, match="someone.else@outlook.com"):
        tokens.sign_in(OUTLOOK, False, print)
    assert not tokens.is_signed_in(OUTLOOK)


def test_an_expired_sign_in_names_the_command_to_fix_it(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    tokens.sign_in(OUTLOOK, False, print)
    expired: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), Expired)
    with pytest.raises(SignInRequired, match="--auth microsoft") as raised:
        expired.access_token(OUTLOOK)
    assert "AADSTS70043: refresh token expired" in str(raised.value) and "Trace" not in str(raised.value)


def test_the_stored_sign_in_is_encrypted(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    tokens.sign_in(OUTLOOK, False, print)
    stored: bytes = next((tmp_path / "sign-ins").iterdir()).read_bytes()
    assert b"refresh" not in stored and b"first-token" not in stored and ADDRESS.encode() not in stored


def test_add_signs_in_checks_and_saves_without_a_password(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    settings: Path = tmp_path / "mailboxes.toml"
    message: str = add_microsoft_mailbox(
        "outlook", settings, tokens, ADDRESS, "client-123", show=print, login_check=accept
    )
    assert "No password stored" in message
    assert load_mailboxes(settings)["outlook"] == OUTLOOK
    book: MailboxBook = MailboxBook(settings, {}, token_sources={"microsoft": tokens})
    assert "signed in to microsoft" in describe_mailboxes(book, settings)
    remove_mailbox("outlook", book, settings)
    assert not tokens.is_signed_in(OUTLOOK)


def test_a_failed_check_removes_the_sign_in(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    def refuse(mailbox: Mailbox, credential: Credential) -> None:
        raise OSError("AUTHENTICATE failed")

    with pytest.raises(OSError):
        add_microsoft_mailbox("outlook", tmp_path / "m.toml", tokens, ADDRESS, "client-123", login_check=refuse)
    assert not tokens.is_signed_in(OUTLOOK)
    assert not (tmp_path / "m.toml").exists()


def test_add_needs_a_client_id(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Application \\(client\\) ID"):
        add_microsoft_mailbox("outlook", tmp_path / "m.toml", tokens, ADDRESS, "")
