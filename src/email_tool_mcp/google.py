"""Google sign-in for Gmail and Google Workspace mailboxes whose administrator turned off App Passwords.

Standard: Google's own libraries: google-auth-oauthlib's `InstalledAppFlow` (browser sign-in,
loopback redirect, the "Desktop app" OAuth client the user downloads from Google Cloud) and
google-auth's `Credentials` (silent refresh), with the `https://mail.google.com/` scope Google
documents for IMAP and SMTP over XOAUTH2. The credentials are kept encrypted in token_store.
Placement: google.py, beside microsoft.py; MailboxBook asks it for tokens, enrol.py for the first sign-in.
"""

from __future__ import annotations

import json
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import google.auth.jwt
import requests
from google.auth.credentials import TokenState
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError

from email_tool_mcp import credentials
from email_tool_mcp.settings import DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT, SETUP_COMMAND, Mailbox, SettingsError
from email_tool_mcp.tls import TlsAdapter, https_session
from email_tool_mcp.token_store import TokenStore

PROVIDER: Final[Literal["google"]] = "google"
# Full mail access (the only scope Gmail accepts for IMAP/SMTP), plus who signed in.
SCOPES: Final[list[str]] = ["https://mail.google.com/", "openid", "https://www.googleapis.com/auth/userinfo.email"]
IMAP_HOST: Final[str] = "imap.gmail.com"
SMTP_HOST: Final[str] = "smtp.gmail.com"
# How long the browser sign-in may take before the loopback listener gives up.
SIGN_IN_SECONDS: Final[int] = 300
# Where a pasted sign-in lands: nothing listens there, so the browser shows "site can't be
# reached" with the one-time code in its address bar, for the user to paste back.
PASTE_REDIRECT: Final[str] = "http://localhost/"
# The usual request options: a refresh token is returned only when the user is asked.
AUTHORIZATION_OPTIONS: Final[dict[str, str]] = {"prompt": "consent", "access_type": "offline"}


def add_command(mailbox: Mailbox) -> str:
    """The command that signs `mailbox` in again."""
    return (
        f"{SETUP_COMMAND} {mailbox.name} --auth {PROVIDER} --address {mailbox.address} "
        "--client-secrets <client_secret_....json from Google Cloud>"
    )


class SignInRequired(credentials.SignInRequired):
    """The Google sign-in is missing, expired or revoked."""

    def __init__(self, mailbox: Mailbox, detail: str = "") -> None:
        super().__init__(mailbox.name, "Google", add_command(mailbox), detail)


class Flow(Protocol):
    """The part of google_auth_oauthlib's InstalledAppFlow used here."""

    redirect_uri: str

    @property
    def credentials(self) -> Credentials: ...

    def run_local_server(self, **options: Any) -> Credentials: ...

    def authorization_url(self, **options: Any) -> tuple[str, str]: ...

    def fetch_token(self, **options: Any) -> dict[str, Any]: ...


FlowFactory = Callable[[Path], Flow]
Refresher = Callable[[Credentials], None]


def installed_app_flow(client_secrets: Path) -> Flow:
    """A real browser sign-in for the OAuth client in `client_secrets`, over the project's TLS."""
    flow: InstalledAppFlow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=SCOPES)
    session: requests.Session = flow.oauth2session
    session.mount("https://", TlsAdapter(max_retries=1))
    typed: Flow = flow
    return typed


def refresh(google_credentials: Credentials) -> None:
    """Refresh through the project's TLS context and timeout."""
    google_credentials.refresh(Request(session=https_session()))


def browser_available() -> bool:
    """True when Python can open a browser from here (a terminal without one prints the address)."""
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def preset(name: str, address: str) -> Mailbox:
    """A Google mailbox on Gmail's servers; `SignIn.complete` adds the OAuth client."""
    return Mailbox(
        name=name,
        address=address,
        imap_host=IMAP_HOST,
        imap_port=DEFAULT_IMAP_PORT,
        smtp_host=SMTP_HOST,
        smtp_port=DEFAULT_SMTP_PORT,
        auth=PROVIDER,
    )


def signed_in_email(google_credentials: Credentials) -> str:
    """The account that signed in, from the ID token.

    Not signature-checked: it came straight from Google's token endpoint over verified TLS,
    which OpenID Connect Core 3.1.3.7 accepts in place of the signature.
    """
    token: object = google_credentials.id_token
    if not isinstance(token, str):
        return ""
    claims: object = google.auth.jwt.decode(token, verify=False)
    return str(claims.get("email", "")) if isinstance(claims, dict) else ""


@dataclass(frozen=True)
class SignIn:
    """A finished sign-in, not yet kept: who signed in, a token to check the mailbox with, the credentials."""

    email: str
    client_id: str
    access_token: str = field(repr=False)
    credentials_json: str = field(repr=False)

    def complete(self, mailbox: Mailbox) -> Mailbox:
        """`mailbox` with the OAuth client that signed in."""
        completed: Mailbox = replace(mailbox, client_id=self.client_id)
        return completed


def _browser_sign_in(flow: Flow, mailbox: Mailbox, show: Callable[[str], None]) -> Credentials:
    """A browser on this computer, answering a listener on a localhost port."""
    opens: bool = browser_available()
    show(
        "A browser window opens for the Google sign-in; finish it there. If it opens in the wrong "
        "browser or profile, open the address below in the one signed in to that account."
        if opens
        else "No browser can be opened from here: open the address below in a browser on this computer."
    )
    try:
        signed: Credentials = flow.run_local_server(
            port=0,
            login_hint=mailbox.address,
            timeout_seconds=SIGN_IN_SECONDS,
            open_browser=opens,
            authorization_prompt_message="Google sign-in address:\n{url}\n",
            **AUTHORIZATION_OPTIONS,
        )
    except WSGITimeoutError as error:
        raise RuntimeError(
            f"no answer from the browser within {SIGN_IN_SECONDS // 60} minutes; nothing saved. If the browser "
            'is on another computer, or showed "site can\'t be reached", run again with --paste-address'
        ) from error
    return signed


def _pasted_sign_in(
    flow: Flow, mailbox: Mailbox, show: Callable[[str], None], paste: Callable[[str], str]
) -> Credentials:
    """A browser anywhere: the user pastes back the address it ends on."""
    flow.redirect_uri = PASTE_REDIRECT
    address: str = flow.authorization_url(login_hint=mailbox.address, **AUTHORIZATION_OPTIONS)[0]
    show(f"Open this address in a browser on any computer, sign in and allow access:\n{address}\n")
    answer: str = paste(
        f'The browser then shows "site can\'t be reached". Paste its whole address (it starts with {PASTE_REDIRECT}): '
    ).strip()
    if not answer.startswith(PASTE_REDIRECT) or "code=" not in answer:
        raise ValueError(
            f"that is not the address the browser ended on (it starts with {PASTE_REDIRECT}); nothing saved"
        )
    # oauthlib takes only https responses; the loopback answer is http by design (RFC 8252 7.3).
    flow.fetch_token(authorization_response=answer.replace("http://", "https://", 1))
    return flow.credentials


class GoogleTokens:
    """TokenSource for Google mailboxes; one encrypted credentials record per mailbox."""

    def __init__(
        self, store: TokenStore, flow_factory: FlowFactory = installed_app_flow, refresher: Refresher = refresh
    ) -> None:
        self._store: TokenStore = store
        self._flow_factory: FlowFactory = flow_factory
        self._refresher: Refresher = refresher

    def _read(self, mailbox: Mailbox) -> str | None:
        try:
            return self._store.read(PROVIDER, mailbox.name)
        except SettingsError as error:
            raise SignInRequired(mailbox, str(error)) from error

    def access_token(self, mailbox: Mailbox) -> str:
        """A valid access token, refreshed silently from the kept sign-in."""
        with self._store.lock(PROVIDER, mailbox.name):
            saved: str | None = self._read(mailbox)
            if not saved:
                raise SignInRequired(mailbox)
            kept: Credentials = Credentials.from_authorized_user_info(json.loads(saved), SCOPES)
            # STALE (about to expire) and INVALID both refresh; only FRESH is used as it is.
            if kept.token_state != TokenState.FRESH:
                try:
                    self._refresher(kept)
                except RefreshError as error:
                    raise SignInRequired(mailbox, str(error).split("\n")[0]) from error
                self._store.write(PROVIDER, mailbox.name, kept.to_json())
        token: str = str(kept.token)
        return token

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        """True when the kept sign-in has a refresh token for this mailbox's OAuth client; no network."""
        with self._store.lock(PROVIDER, mailbox.name):
            try:
                saved: str | None = self._read(mailbox)
            except SignInRequired:
                return False
        if not saved:
            return False
        info: object = json.loads(saved)
        return isinstance(info, dict) and bool(info.get("refresh_token")) and info.get("client_id") == mailbox.client_id

    def forget(self, mailbox: Mailbox) -> None:
        """Delete the kept sign-in."""
        with self._store.lock(PROVIDER, mailbox.name):
            self._store.delete(PROVIDER, mailbox.name)

    def sign_in(
        self,
        mailbox: Mailbox,
        client_secrets: Path,
        show: Callable[[str], None],
        paste: Callable[[str], str] | None = None,
    ) -> SignIn:
        """Sign in once in the browser; nothing is kept until `keep`.

        With `paste`, the browser may be on another computer: the user pastes back the
        address it ends on. Gmail logs in as the Google account itself, so an account
        other than `mailbox.address` is refused.
        """
        flow: Flow = self._flow_factory(client_secrets)
        signed: Credentials = (
            _pasted_sign_in(flow, mailbox, show, paste) if paste is not None else _browser_sign_in(flow, mailbox, show)
        )
        email: str = signed_in_email(signed)
        if email.lower() != mailbox.address.lower():
            raise RuntimeError(
                f"signed in as {email or 'an unknown account'}, not {mailbox.address}. Gmail logs in as the "
                f"Google account itself: use --address {email or '<that account>'}; nothing saved"
            )
        if not signed.refresh_token:
            raise RuntimeError("Google returned no refresh token, so the sign-in could not be kept; nothing saved")
        return SignIn(email, str(signed.client_id), str(signed.token), signed.to_json())

    def keep(self, mailbox: Mailbox, signed: SignIn) -> None:
        """Keep a checked sign-in for `mailbox`, replacing any earlier one."""
        with self._store.lock(PROVIDER, mailbox.name):
            self._store.write(PROVIDER, mailbox.name, signed.credentials_json)
