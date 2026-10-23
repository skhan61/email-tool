"""Microsoft sign-in: presets, account kinds, silent refresh, encrypted storage, add, re-add and remove.

Standard: pytest; a fake MSAL application stands in for Microsoft's servers, with the real
msal.SerializableTokenCache and the real encrypted TokenStore.
Placement: tests/test_microsoft.py, beside microsoft.py, token_store.py and the add flow in enrol.py.
"""

from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import msal
import pytest
import requests
from msal.oauth2cli.oauth2 import BrowserInteractionTimeoutError
from requests.adapters import HTTPAdapter

from email_tool_mcp import enrol
from email_tool_mcp.credentials import Credential
from email_tool_mcp.enrol import add_by_auth, add_microsoft_mailbox, describe_mailboxes, remove_mailbox, save_mailbox
from email_tool_mcp.google import GoogleTokens
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import (
    DEFAULT_CLIENT_ID,
    PERSONAL_SMTP_HOST,
    PERSONAL_TENANT_ID,
    REDIRECT,
    MicrosoftTokens,
    SignIn,
    SignInRequired,
    authority_of,
    cloud_of,
    preset,
    scopes_for,
)
from email_tool_mcp.passwords import has_password, store_password
from email_tool_mcp.settings import NETWORK_TIMEOUT_SECONDS, Mailbox, load_mailboxes
from email_tool_mcp.tls import https_session
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
        self.tenant_id: str = PERSONAL_TENANT_ID
        self.scopes: list[str] = []
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
        claims: dict[str, str] = {"preferred_username": self.signed_in_as, "tid": self.tenant_id}
        return {"access_token": "first-token", "id_token_claims": claims}

    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]:
        return self._signed_in(scopes)

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]:
        self.scopes = scopes
        return {"user_code": "ABCD", "message": "Go to https://microsoft.com/devicelogin and enter ABCD"}

    def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        return self._signed_in(self.scopes)

    def initiate_auth_code_flow(self, scopes: list[str], **options: Any) -> dict[str, Any]:
        self.scopes = scopes
        self.code_flow_options: dict[str, Any] = options
        return {"auth_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1", "state": "s"}

    def acquire_token_by_auth_code_flow(
        self, auth_code_flow: dict[str, Any], auth_response: dict[str, str]
    ) -> dict[str, Any]:
        self.auth_response: dict[str, str] = auth_response
        return self._signed_in(self.scopes)


OUTLOOK: Mailbox = preset("outlook", ADDRESS, "client-123", "", "commercial")


@pytest.fixture
def tokens(tmp_path: Path) -> MicrosoftTokens:
    FakeMsal.instances = []
    return MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), FakeMsal)


def accept(mailbox: Mailbox, credential: Credential) -> None:
    assert credential.is_token and credential.secret == "first-token"


def nothing_to_forget(mailbox: Mailbox) -> bool:
    raise AssertionError(f"nothing to forget: {mailbox.name} replaced no mailbox of another kind")


def keep_signed_in(tokens: MicrosoftTokens, mailbox: Mailbox = OUTLOOK) -> Mailbox:
    signed: SignIn = tokens.sign_in(mailbox, False, print)
    completed: Mailbox = signed.complete(mailbox)
    tokens.keep(completed, signed)
    return completed


def test_presets_pick_servers_and_directory_for_each_cloud() -> None:
    assert (OUTLOOK.imap_host, OUTLOOK.smtp_host, OUTLOOK.smtp_port, OUTLOOK.cloud) == (
        "outlook.office365.com",
        "smtp.office365.com",
        587,
        "commercial",
    )
    assert authority_of(OUTLOOK) == "https://login.microsoftonline.com/common"
    gcc: Mailbox = preset("g", "me@agency.us", "c", "tenant-id", "gcc-high")
    assert (gcc.imap_host, gcc.smtp_host, gcc.cloud) == ("outlook.office365.us", "smtp.office365.us", "gcc-high")
    assert authority_of(gcc) == "https://login.microsoftonline.us/tenant-id"
    assert authority_of(preset("g", "me@agency.us", "c", "", "gcc-high")).endswith("/organizations")
    assert scopes_for(cloud_of(gcc)) == [
        "https://outlook.office365.us/IMAP.AccessAsUser.All",
        "https://outlook.office365.us/SMTP.Send",
    ]
    with pytest.raises(ValueError):
        preset("x", "me@outlook.com", "c", "", "moon")


class Regional(FakeMsal):
    """A personal account on a regional domain."""

    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        super().__init__(client_id, authority, cache)
        self.signed_in_as = "sayem@hotmail.co.uk"


class Work(FakeMsal):
    """A Microsoft 365 account whose user name is not its mail address."""

    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        super().__init__(client_id, authority, cache)
        self.signed_in_as = "skhan@contoso.onmicrosoft.com"
        self.tenant_id = "contoso-tenant"


def test_the_account_kind_comes_from_microsoft_not_the_domain(tmp_path: Path) -> None:
    regional: Mailbox = preset("uk", "sayem@hotmail.co.uk", "c", "", "commercial")
    personal: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "a"), Regional)
    assert tokens_complete(personal, regional).smtp_host == PERSONAL_SMTP_HOST
    work: Mailbox = preset("w", "s.khan@contoso.com", "c", "", "commercial")
    completed: Mailbox = tokens_complete(MicrosoftTokens(TokenStore(tmp_path / "b"), Work), work)
    assert (completed.smtp_host, completed.account) == ("smtp.office365.com", "skhan@contoso.onmicrosoft.com")


def tokens_complete(tokens: MicrosoftTokens, mailbox: Mailbox) -> Mailbox:
    return tokens.sign_in(mailbox, False, print).complete(mailbox)


def test_a_user_name_unlike_the_address_is_kept_and_refreshed(tmp_path: Path) -> None:
    tokens: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "s"), Work)
    work: Mailbox = keep_signed_in(tokens, preset("w", "s.khan@contoso.com", "c", "", "commercial"))
    assert tokens.is_signed_in(work) and tokens.access_token(work) == "fresh-token"
    assert not tokens.is_signed_in(preset("w", "s.khan@contoso.com", "c", "", "commercial"))


@pytest.mark.parametrize("device_code", [False, True])
def test_sign_in_then_silent_tokens(tokens: MicrosoftTokens, device_code: bool) -> None:
    shown: list[str] = []
    signed: SignIn = tokens.sign_in(OUTLOOK, device_code, shown.append)
    assert not tokens.is_signed_in(OUTLOOK)
    tokens.keep(signed.complete(OUTLOOK), signed)
    assert tokens.is_signed_in(OUTLOOK)
    assert tokens.access_token(OUTLOOK) == "fresh-token"
    assert FakeMsal.instances[0].authority == "https://login.microsoftonline.com/common"
    assert ("ABCD" in shown[0]) is device_code


def test_a_sign_in_for_another_app_does_not_count(tokens: MicrosoftTokens) -> None:
    keep_signed_in(tokens)
    assert not tokens.is_signed_in(replace(OUTLOOK, client_id="another-app"))


def test_sign_in_traffic_uses_the_tls_floor_and_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    def record(adapter: HTTPAdapter, request: requests.PreparedRequest, *args: object) -> requests.Response:
        sent.append(args[1])
        return requests.Response()

    monkeypatch.setattr(HTTPAdapter, "send", record)
    session: requests.Session = https_session()
    adapter: object = session.get_adapter("https://login.microsoftonline.com")
    assert isinstance(adapter, HTTPAdapter)
    context: ssl.SSLContext = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    session.get("https://login.microsoftonline.com/common")
    # google-auth passes 120 s of its own; the project's timeout still applies.
    session.post("https://oauth2.googleapis.com/token", timeout=120)
    assert sent == [NETWORK_TIMEOUT_SECONDS, NETWORK_TIMEOUT_SECONDS]
    proxied: object = adapter.proxy_manager_for("http://proxy.example.com:3128")
    proxy_context: object = getattr(proxied, "connection_pool_kw", {}).get("ssl_context")
    assert isinstance(proxy_context, ssl.SSLContext)
    assert proxy_context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_refreshing_reuses_one_app_and_checking_builds_none(tokens: MicrosoftTokens) -> None:
    keep_signed_in(tokens)
    FakeMsal.instances = []
    assert tokens.is_signed_in(OUTLOOK)
    assert FakeMsal.instances == []
    tokens.access_token(OUTLOOK)
    tokens.access_token(OUTLOOK)
    assert len(FakeMsal.instances) == 1


class Expired(FakeMsal):
    def __init__(self, client_id: str, authority: str, cache: msal.SerializableTokenCache) -> None:
        super().__init__(client_id, authority, cache)
        self.silent = {"error": "invalid_grant", "error_description": "AADSTS70043: refresh token expired\nTrace"}


def test_an_expired_sign_in_names_the_whole_command_to_fix_it(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    gcc: Mailbox = keep_signed_in(tokens, preset("gov", "me@agency.us", "client-9", "", "gcc-high"))
    expired: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), Expired)
    with pytest.raises(SignInRequired) as raised:
        expired.access_token(gcc)
    message: str = str(raised.value)
    assert "add gov --auth microsoft --address me@agency.us --client-id client-9 --cloud gcc-high" in message
    assert "AADSTS70043: refresh token expired" in message and "Trace" not in message


def test_an_undecryptable_sign_in_asks_for_a_new_one(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    keep_signed_in(tokens)
    stored: Path = next((tmp_path / "sign-ins").glob("*.bin"))
    stored.write_bytes(b"garbage")
    assert not tokens.is_signed_in(OUTLOOK)
    with pytest.raises(SignInRequired, match="--client-id client-123"):
        tokens.access_token(OUTLOOK)


def test_the_stored_sign_in_is_encrypted_and_named_apart(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    keep_signed_in(tokens)
    stored: bytes = next((tmp_path / "sign-ins").glob("*.bin")).read_bytes()
    assert b"refresh" not in stored and b"first-token" not in stored and ADDRESS.encode() not in stored
    store: TokenStore = TokenStore(tmp_path / "names")
    store.write("microsoft", "a b", "one")
    store.write("microsoft", "a_b", "two")
    assert (store.read("microsoft", "a b"), store.read("microsoft", "a_b")) == ("one", "two")


def test_add_signs_in_checks_and_saves_without_a_password(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    settings: Path = tmp_path / "mailboxes.toml"
    message: str = add_microsoft_mailbox(
        "outlook", settings, tokens, ADDRESS, "client-123", show=print, login_check=accept, forget=nothing_to_forget
    )
    assert "No password stored" in message
    saved: Mailbox = load_mailboxes(settings)["outlook"]
    assert (saved.smtp_host, saved.account) == (PERSONAL_SMTP_HOST, "")
    book: MailboxBook = MailboxBook(settings, {}, token_sources={"microsoft": tokens})
    assert "signed in to microsoft" in describe_mailboxes(book, settings)
    remove_mailbox("outlook", book, settings)
    assert not tokens.is_signed_in(saved)


def test_a_failed_check_keeps_the_earlier_sign_in(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    def refuse(mailbox: Mailbox, credential: Credential) -> None:
        raise OSError("AUTHENTICATE failed")

    settings: Path = tmp_path / "m.toml"
    add_microsoft_mailbox(
        "outlook", settings, tokens, ADDRESS, "client-123", login_check=accept, forget=nothing_to_forget
    )
    before: bytes = next((tmp_path / "sign-ins").glob("*.bin")).read_bytes()
    with pytest.raises(OSError):
        add_microsoft_mailbox(
            "outlook", settings, tokens, ADDRESS, "client-123", login_check=refuse, forget=nothing_to_forget
        )
    assert next((tmp_path / "sign-ins").glob("*.bin")).read_bytes() == before
    assert tokens.is_signed_in(load_mailboxes(settings)["outlook"])
    with pytest.raises(OSError):
        add_microsoft_mailbox(
            "other", tmp_path / "n.toml", tokens, ADDRESS, "client-123", login_check=refuse, forget=nothing_to_forget
        )
    assert not (tmp_path / "n.toml").exists()


def test_switching_a_mailbox_to_microsoft_deletes_its_password(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    settings: Path = tmp_path / "m.toml"
    book: MailboxBook = MailboxBook(settings, {}, token_sources={"microsoft": tokens})
    save_mailbox(settings, Mailbox("outlook", ADDRESS, "imap.x", 993, "smtp.x", 465), book.forget)
    store_password("outlook", "old-password")
    add_microsoft_mailbox("outlook", settings, tokens, ADDRESS, "client-123", login_check=accept, forget=book.forget)
    assert not has_password("outlook")
    save_mailbox(settings, Mailbox("outlook", ADDRESS, "imap.x", 993, "smtp.x", 465), book.forget)
    assert not tokens.is_signed_in(OUTLOOK)


def test_the_project_app_is_the_default_except_in_gcc_high(tokens: MicrosoftTokens, tmp_path: Path) -> None:
    settings: Path = tmp_path / "m.toml"
    add_microsoft_mailbox(
        "outlook",
        settings,
        tokens,
        ADDRESS,
        "",
        login_check=lambda mailbox, credential: None,
        forget=nothing_to_forget,
    )
    saved: Mailbox = load_mailboxes(settings)["outlook"]
    assert saved.client_id == DEFAULT_CLIENT_ID
    assert "--client-id" not in str(SignInRequired(saved))
    with pytest.raises(ValueError, match="GCC High needs an app registered in GCC High"):
        add_microsoft_mailbox(
            "gov", tmp_path / "g.toml", tokens, "me@agency.us", "", cloud="gcc-high", forget=nothing_to_forget
        )


class NeedsAdmin(FakeMsal):
    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]:
        return {"error": "consent_required", "error_description": "AADSTS90094: Need admin approval.\nTrace ID: x"}


def test_admin_approval_says_what_to_ask_it_for(tmp_path: Path) -> None:
    tokens: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "s"), NeedsAdmin)
    with pytest.raises(RuntimeError) as raised:
        tokens.sign_in(OUTLOOK, False, print)
    message: str = str(raised.value)
    assert "AADSTS90094" in message and "Trace ID" not in message
    assert "admin consent to the application ID client-123" in message


class NoBrowserAnswer(FakeMsal):
    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]:
        assert options["timeout"] == 300
        # MSAL's own error, a RuntimeError; its message wrongly reads "timeout setting is None".
        raise BrowserInteractionTimeoutError("User did not complete the flow in time")


def test_a_browser_that_never_answers_gives_up(tmp_path: Path) -> None:
    tokens: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "s"), NoBrowserAnswer)
    with pytest.raises(RuntimeError, match="no answer from the browser within 5 minutes"):
        tokens.sign_in(OUTLOOK, False, print)


def test_a_pasted_address_finishes_the_sign_in(tokens: MicrosoftTokens) -> None:
    shown: list[str] = []
    asked: list[str] = []

    def paste(prompt: str) -> str:
        asked.append(prompt)
        return "http://localhost/?code=one-time&state=s&session_state=x\n"

    signed: SignIn = tokens.sign_in(OUTLOOK, False, shown.append, paste)
    app: FakeMsal = FakeMsal.instances[-1]
    assert signed.username == ADDRESS
    assert app.code_flow_options["redirect_uri"] == "http://localhost"
    assert app.auth_response == {"code": "one-time", "state": "s", "session_state": "x"}
    assert shown[0].startswith("Microsoft sign-in address.") and "authorize?x=1" in shown[0]
    assert "site can't be reached" in asked[0]


def test_a_pasted_address_without_a_code_is_refused(tokens: MicrosoftTokens) -> None:
    with pytest.raises(ValueError, match="not the address the browser ended on"):
        tokens.sign_in(OUTLOOK, False, print, lambda prompt: "https://login.microsoftonline.com/common")


class Recording(MicrosoftTokens):
    def sign_in(
        self,
        mailbox: Mailbox,
        device_code: bool,
        show: Callable[[str], None],
        paste: Callable[[str], str] | None = None,
        redirect: str = REDIRECT,
        open_address: Callable[[str], None] | None = None,
    ) -> SignIn:
        self.pasting: bool = paste is not None
        raise RuntimeError("stop after choosing the mode")


@pytest.mark.parametrize(
    ("browser", "paste_address", "device_code", "pasting"),
    [(True, False, False, False), (False, False, False, True), (True, True, False, True), (False, False, True, False)],
)
def test_the_sign_in_mode_follows_the_browser_and_the_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    browser: bool,
    paste_address: bool,
    device_code: bool,
    pasting: bool,
) -> None:
    monkeypatch.setattr(enrol, "browser_available", lambda: browser)
    tokens: Recording = Recording(TokenStore(tmp_path / "s"), FakeMsal)
    with pytest.raises(RuntimeError, match="stop after choosing the mode"):
        add_by_auth(
            "outlook",
            tmp_path / "m.toml",
            "microsoft",
            tokens,
            GoogleTokens(TokenStore(tmp_path / "g")),
            nothing_to_forget,
            address=ADDRESS,
            device_code=device_code,
            paste_address=paste_address,
        )
    assert tokens.pasting is pasting


def test_device_code_and_paste_address_together_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="choose one"):
        add_by_auth(
            "outlook",
            tmp_path / "m.toml",
            "microsoft",
            MicrosoftTokens(TokenStore(tmp_path / "s"), FakeMsal),
            GoogleTokens(TokenStore(tmp_path / "g")),
            nothing_to_forget,
            address=ADDRESS,
            device_code=True,
            paste_address=True,
        )
