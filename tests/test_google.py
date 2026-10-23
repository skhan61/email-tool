"""Google sign-in: browser flow, wrong-account refusal, silent refresh, encrypted storage, add.

Standard: pytest; a fake browser flow returns google-auth's real `Credentials`, and the real
encrypted TokenStore keeps them, so storage and refresh decisions are the library's own.
Placement: tests/test_google.py, beside google.py and the add flow in enrol.py.
"""

from __future__ import annotations

import base64
import json
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import WSGITimeoutError

from email_tool_mcp.browser import browser_available
from email_tool_mcp.credentials import Credential
from email_tool_mcp.enrol import add_google_mailbox
from email_tool_mcp.google import GoogleTokens, SignIn, SignInRequired, preset
from email_tool_mcp.settings import Mailbox, load_mailboxes
from email_tool_mcp.token_store import TokenStore

ADDRESS: str = "student@g.example.edu"
RIT: Mailbox = preset("rit", ADDRESS)


def unsigned_id_token(email: str) -> str:
    def part(value: dict[str, str]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part({'email': email})}.c2ln"


class FakeFlow:
    """Stands in for the browser: returns what Google's token endpoint would."""

    def __init__(self, email: str = ADDRESS, refresh_token: str | None = "refresh") -> None:
        self.email: str = email
        self.refresh_token: str | None = refresh_token
        self.options: dict[str, Any] = {}
        self.redirect_uri: str = ""
        self.fetched: str = ""

    def _issued(self) -> Credentials:
        return Credentials(
            token="first-token",
            refresh_token=self.refresh_token,
            id_token=unsigned_id_token(self.email),
            token_uri="https://oauth2.googleapis.com/token",
            client_id="client-1.apps.googleusercontent.com",
            client_secret="not-really-secret",
            # Naive UTC, as google-auth keeps it; a real sign-in always carries one.
            expiry=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )

    @property
    def credentials(self) -> Credentials:
        return self._issued()

    def run_local_server(self, **options: Any) -> Credentials:
        self.options = options
        return self._issued()

    def authorization_url(self, **options: Any) -> tuple[str, str]:
        self.options = options
        return f"https://accounts.google.com/o/oauth2/auth?redirect_uri={self.redirect_uri}", "state"

    def fetch_token(self, **options: Any) -> dict[str, Any]:
        self.fetched = str(options["authorization_response"])
        return {}


def tokens_with(tmp_path: Path, flow: FakeFlow, refreshed: list[Credentials] | None = None) -> GoogleTokens:
    def refresher(kept: Credentials) -> None:
        if refreshed is None:
            raise RefreshError("invalid_grant: Token has been expired or revoked.\nmore")
        kept.token = "fresh-token"
        refreshed.append(kept)

    return GoogleTokens(TokenStore(tmp_path / "sign-ins"), lambda secrets: flow, refresher)


def accept(mailbox: Mailbox, credential: Credential) -> None:
    assert credential.is_token and credential.secret == "first-token"


def nothing_to_forget(mailbox: Mailbox) -> bool:
    raise AssertionError(f"nothing to forget: {mailbox.name} replaced no mailbox of another kind")


def client_file(tmp_path: Path) -> Path:
    path: Path = tmp_path / "client_secret.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_sign_in_asks_for_consent_and_keeps_nothing_yet(tmp_path: Path) -> None:
    flow: FakeFlow = FakeFlow()
    tokens: GoogleTokens = tokens_with(tmp_path, flow)
    signed: SignIn = tokens.sign_in(RIT, client_file(tmp_path), print)
    assert (signed.email, signed.client_id) == (ADDRESS, "client-1.apps.googleusercontent.com")
    assert flow.options["login_hint"] == ADDRESS and flow.options["prompt"] == "consent"
    assert not tokens.is_signed_in(signed.complete(RIT))


def test_another_google_account_is_refused(tmp_path: Path) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow(email="student@example.edu"))
    with pytest.raises(RuntimeError, match="use --address student@example.edu"):
        tokens.sign_in(RIT, client_file(tmp_path), print)


def test_a_sign_in_without_a_refresh_token_is_refused(tmp_path: Path) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow(refresh_token=None))
    with pytest.raises(RuntimeError, match="no refresh token"):
        tokens.sign_in(RIT, client_file(tmp_path), print)


def test_a_kept_sign_in_refreshes_silently_and_is_encrypted(tmp_path: Path) -> None:
    refreshed: list[Credentials] = []
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow(), refreshed)
    signed: SignIn = tokens.sign_in(RIT, client_file(tmp_path), print)
    mailbox: Mailbox = signed.complete(RIT)
    tokens.keep(mailbox, signed)
    assert tokens.is_signed_in(mailbox)
    assert tokens.access_token(mailbox) == "first-token" and refreshed == []

    stored: Path = next((tmp_path / "sign-ins").glob("google-*.bin"))
    assert b"refresh" not in stored.read_bytes() and ADDRESS.encode() not in stored.read_bytes()
    info: dict[str, Any] = json.loads(signed.credentials_json)
    info.pop("token")
    tokens.keep(mailbox, SignIn(ADDRESS, signed.client_id, "", json.dumps(info)))
    assert tokens.access_token(mailbox) == "fresh-token" and len(refreshed) == 1


def test_a_revoked_sign_in_names_the_command_to_fix_it(tmp_path: Path) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow(), refreshed=None)
    signed: SignIn = tokens.sign_in(RIT, client_file(tmp_path), print)
    mailbox: Mailbox = signed.complete(RIT)
    info: dict[str, Any] = json.loads(signed.credentials_json)
    info.pop("token")
    tokens.keep(mailbox, SignIn(ADDRESS, signed.client_id, "", json.dumps(info)))
    with pytest.raises(SignInRequired) as raised:
        tokens.access_token(mailbox)
    message: str = str(raised.value)
    assert f"add rit --auth google --address {ADDRESS} --client-secrets" in message
    assert "Token has been expired or revoked" in message and "more" not in message


def test_a_sign_in_for_another_client_does_not_count(tmp_path: Path) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow())
    signed: SignIn = tokens.sign_in(RIT, client_file(tmp_path), print)
    tokens.keep(signed.complete(RIT), signed)
    assert not tokens.is_signed_in(RIT)


def test_add_signs_in_checks_and_saves(tmp_path: Path) -> None:
    settings: Path = tmp_path / "m.toml"
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow())
    message: str = add_google_mailbox(
        "rit", settings, tokens, ADDRESS, str(client_file(tmp_path)), login_check=accept, forget=nothing_to_forget
    )
    assert "Signed in with Google" in message
    saved: Mailbox = load_mailboxes(settings)["rit"]
    assert (saved.auth, saved.imap_host, saved.smtp_host) == ("google", "imap.gmail.com", "smtp.gmail.com")
    assert tokens.is_signed_in(saved)


def test_a_failed_check_keeps_nothing(tmp_path: Path) -> None:
    def refuse(mailbox: Mailbox, credential: Credential) -> None:
        raise OSError("AUTHENTICATE failed")

    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow())
    with pytest.raises(OSError):
        add_google_mailbox(
            "rit",
            tmp_path / "m.toml",
            tokens,
            ADDRESS,
            str(client_file(tmp_path)),
            login_check=refuse,
            forget=nothing_to_forget,
        )
    assert not (tmp_path / "m.toml").exists()
    assert not list((tmp_path / "sign-ins").glob("google-*.bin"))


def test_add_needs_the_client_file(tmp_path: Path) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow())
    with pytest.raises(ValueError, match="--client-secrets"):
        add_google_mailbox(
            "rit", tmp_path / "m.toml", tokens, ADDRESS, str(tmp_path / "missing.json"), forget=nothing_to_forget
        )


def test_without_a_browser_the_address_is_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def none() -> object:
        raise webbrowser.Error("could not locate runnable browser")

    monkeypatch.setattr(webbrowser, "get", none)
    flow: FakeFlow = FakeFlow()
    shown: list[str] = []
    tokens_with(tmp_path, flow).sign_in(RIT, client_file(tmp_path), shown.append)
    assert flow.options["open_browser"] is False and "{url}" in flow.options["authorization_prompt_message"]
    assert "No browser can be opened" in shown[0]


def test_a_browser_elsewhere_pastes_back_the_address(tmp_path: Path) -> None:
    flow: FakeFlow = FakeFlow()
    asked: list[str] = []

    def paste(prompt: str) -> str:
        asked.append(prompt)
        return "http://localhost/?state=state&code=one-time&scope=x\n"

    signed: SignIn = tokens_with(tmp_path, flow).sign_in(RIT, client_file(tmp_path), print, paste)
    assert signed.email == ADDRESS
    assert flow.redirect_uri == "http://localhost/" and flow.options["prompt"] == "consent"
    assert flow.fetched == "https://localhost/?state=state&code=one-time&scope=x"
    assert "site can't be reached" in asked[0]


def test_a_pasted_address_that_is_not_the_answer_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not the address the browser ended on"):
        tokens_with(tmp_path, FakeFlow()).sign_in(
            RIT, client_file(tmp_path), print, lambda prompt: "https://accounts.google.com/o/oauth2/auth?x"
        )


def test_no_answer_in_time_names_the_paste_option(tmp_path: Path) -> None:
    class Silent(FakeFlow):
        def run_local_server(self, **options: Any) -> Credentials:
            raise WSGITimeoutError("Timed out waiting for response from authorization server")

    with pytest.raises(RuntimeError, match="--paste-address"):
        tokens_with(tmp_path, Silent()).sign_in(RIT, client_file(tmp_path), print)


def test_unticking_mail_access_says_so(tmp_path: Path) -> None:
    class Partial(FakeFlow):
        def run_local_server(self, **options: Any) -> Credentials:
            raise Warning('Scope has changed from "https://mail.google.com/ openid" to "openid".')

        def fetch_token(self, **options: Any) -> dict[str, Any]:
            raise Warning('Scope has changed from "https://mail.google.com/ openid" to "openid".')

    tokens: GoogleTokens = tokens_with(tmp_path, Partial())
    with pytest.raises(RuntimeError, match="leave every box ticked"):
        tokens.sign_in(RIT, client_file(tmp_path), print)
    with pytest.raises(RuntimeError, match="leave every box ticked"):
        tokens.sign_in(RIT, client_file(tmp_path), print, lambda prompt: "http://localhost/?code=c&state=s")


@pytest.mark.parametrize(
    ("browser", "expected"),
    [(webbrowser.GenericBrowser("w3m"), False), (webbrowser.BackgroundBrowser("xdg-open"), True)],
)
def test_a_console_browser_does_not_count(
    monkeypatch: pytest.MonkeyPatch, browser: webbrowser.BaseBrowser, expected: bool
) -> None:
    monkeypatch.setattr(webbrowser, "get", lambda: browser)
    assert browser_available() is expected


@pytest.mark.parametrize(
    ("record", "reason"),
    [("not json", "incomplete"), ('{"refresh_token": "r"}', "incomplete"), (None, "another OAuth client")],
)
def test_a_damaged_or_foreign_sign_in_asks_for_a_new_one(tmp_path: Path, record: str | None, reason: str) -> None:
    tokens: GoogleTokens = tokens_with(tmp_path, FakeFlow())
    signed: SignIn = tokens.sign_in(RIT, client_file(tmp_path), print)
    mailbox: Mailbox = signed.complete(RIT)
    kept: str = record if record is not None else signed.credentials_json
    tokens.keep(mailbox, SignIn(ADDRESS, signed.client_id, "", kept))
    asked: Mailbox = mailbox if record is not None else RIT
    with pytest.raises(SignInRequired, match=reason):
        tokens.access_token(asked)
