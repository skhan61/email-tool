"""Microsoft sign-in for Outlook.com, Microsoft 365 and GCC High mailboxes.

Standard: MSAL for Python (Microsoft's own library): a public client with browser
sign-in on `http://localhost` (or device code), silent refresh from its token cache,
and the delegated scopes Microsoft documents for IMAP and SMTP
(`IMAP.AccessAsUser.All`, `SMTP.Send`). The cache is kept encrypted in token_store.
Placement: microsoft.py; MailboxBook asks it for tokens, enrol.py for the first sign-in.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal, Protocol
from urllib.parse import parse_qsl, urlsplit

import msal

from email_tool_mcp import credentials
from email_tool_mcp.browser import pasted_address
from email_tool_mcp.settings import (
    DEFAULT_IMAP_PORT,
    SETUP_COMMAND,
    SIGN_IN_SECONDS,
    SUBMISSION_PORT,
    CloudName,
    Mailbox,
    SettingsError,
)
from email_tool_mcp.tls import https_session
from email_tool_mcp.token_store import TokenStore

PROVIDER: Final[Literal["microsoft"]] = "microsoft"
# The directory every personal Microsoft account (Outlook.com, Hotmail, Live) signs in to,
# whatever its mail domain; Microsoft returns it as the `tid` claim.
PERSONAL_TENANT_ID: Final[str] = "9188040d-6c67-4c5b-b112-36a304b66dad"


@dataclass(frozen=True)
class Cloud:
    """Where one Microsoft cloud signs in and serves mail."""

    login_host: str
    resource: str
    imap_host: str
    smtp_host: str
    # Directory used when none is pinned: "common" takes work and personal accounts alike.
    default_tenant: str


CLOUDS: Final[dict[CloudName, Cloud]] = {
    "commercial": Cloud(
        "login.microsoftonline.com", "outlook.office.com", "outlook.office365.com", "smtp.office365.com", "common"
    ),
    "gcc-high": Cloud(
        "login.microsoftonline.us", "outlook.office365.us", "outlook.office365.us", "smtp.office365.us", "organizations"
    ),
}
PERSONAL_SMTP_HOST: Final[str] = "smtp-mail.outlook.com"
# The redirect registered on the app ("Public client/native"); a pasted sign-in ends there.
REDIRECT: Final[str] = "http://localhost"
# The project's own app registration (commercial cloud, work and personal accounts). An app ID
# is public, not a secret; an organisation that wants its own app passes --client-id.
DEFAULT_CLIENT_ID: Final[str] = "82731d7a-ac7f-4a5e-88d3-acce522f85ce"


def add_command(mailbox: Mailbox) -> str:
    """The full command that signs `mailbox` in again with the settings it has now."""
    parts: list[str] = [
        SETUP_COMMAND,
        mailbox.name,
        f"--auth {PROVIDER}",
        f"--address {mailbox.address}",
    ]
    if mailbox.client_id != DEFAULT_CLIENT_ID:
        parts.append(f"--client-id {mailbox.client_id or '<app id>'}")
    if mailbox.cloud != "commercial":
        parts.append(f"--cloud {mailbox.cloud}")
    if mailbox.tenant:
        parts.append(f"--tenant {mailbox.tenant}")
    return " ".join(parts)


class SignInRequired(credentials.SignInRequired):
    """The Microsoft sign-in is missing, expired or revoked."""

    def __init__(self, mailbox: Mailbox, detail: str = "") -> None:
        super().__init__(mailbox.name, "Microsoft", add_command(mailbox), detail)


class MsalApp(Protocol):
    """The part of msal.PublicClientApplication used here."""

    def get_accounts(self, username: str | None = None) -> list[dict[str, Any]]: ...

    def acquire_token_silent(self, scopes: list[str], account: dict[str, Any]) -> dict[str, Any] | None: ...

    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]: ...

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]: ...

    def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]: ...

    def initiate_auth_code_flow(self, scopes: list[str], **options: Any) -> dict[str, Any]: ...

    def acquire_token_by_auth_code_flow(
        self, auth_code_flow: dict[str, Any], auth_response: dict[str, str]
    ) -> dict[str, Any]: ...


AppFactory = Callable[[str, str, msal.SerializableTokenCache], MsalApp]


def msal_app(client_id: str, authority: str, cache: msal.SerializableTokenCache) -> MsalApp:
    """A real MSAL public client application (it fetches the directory's metadata once)."""
    app: MsalApp = msal.PublicClientApplication(
        client_id, authority=authority, token_cache=cache, http_client=https_session()
    )
    return app


def cloud_named(name: str) -> CloudName:
    """`name` as a known cloud, or ValueError."""
    known: CloudName
    for known in CLOUDS:
        if known == name:
            return known
    raise ValueError(f"cloud must be one of {sorted(CLOUDS)}, not {name!r}")


def cloud_of(mailbox: Mailbox) -> Cloud:
    """The cloud a mailbox signs in to."""
    return CLOUDS[mailbox.cloud]


def authority_of(mailbox: Mailbox) -> str:
    """The sign-in URL: the mailbox's cloud and its pinned directory, or the cloud's default."""
    cloud: Cloud = cloud_of(mailbox)
    return f"https://{cloud.login_host}/{mailbox.tenant or cloud.default_tenant}"


def scopes_for(cloud: Cloud) -> list[str]:
    """The delegated IMAP and SMTP scopes in one cloud (offline_access is added by MSAL)."""
    return [f"https://{cloud.resource}/IMAP.AccessAsUser.All", f"https://{cloud.resource}/SMTP.Send"]


# Microsoft's own directory names: any work or school account, any account, personal accounts.
_TENANT_ALIASES: Final[frozenset[str]] = frozenset({"organizations", "common", "consumers"})
_GUID: Final[re.Pattern[str]] = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DOMAIN: Final[re.Pattern[str]] = re.compile(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{1,59})"
)


def pasted_id(value: str) -> str:
    """An ID as people paste it, without spaces, quotes or the braces PowerShell prints around a GUID."""
    return value.strip().strip("{}\"'").strip()


def check_directory(tenant: str, client_id: str) -> None:
    """Refuse a directory or app ID of the wrong shape: both go into Microsoft's sign-in address."""
    if client_id and not _GUID.fullmatch(client_id):
        raise ValueError(
            "The App (client) ID looks like 12345678-abcd-1234-abcd-1234567890ab. Check it with your IT department."
        )
    if tenant and not (tenant in _TENANT_ALIASES or _GUID.fullmatch(tenant) or _DOMAIN.fullmatch(tenant)):
        raise ValueError(
            "The Directory (tenant) ID is an ID like the App ID, a domain such as your-school.edu, or organizations."
        )


def preset(name: str, address: str, client_id: str, tenant: str, cloud: str) -> Mailbox:
    """A Microsoft mailbox with its cloud's servers; `SignIn.complete` adjusts it once the account is known."""
    chosen: CloudName = cloud_named(cloud)
    return Mailbox(
        name=name,
        address=address,
        imap_host=CLOUDS[chosen].imap_host,
        imap_port=DEFAULT_IMAP_PORT,
        smtp_host=CLOUDS[chosen].smtp_host,
        smtp_port=SUBMISSION_PORT,
        auth=PROVIDER,
        client_id=client_id,
        tenant=tenant,
        cloud=chosen,
    )


@dataclass(frozen=True)
class SignIn:
    """A finished sign-in, not yet kept: who signed in, a token to check the mailbox with, the new cache."""

    username: str
    personal: bool
    access_token: str = field(repr=False)
    cache: str = field(repr=False)

    def complete(self, mailbox: Mailbox) -> Mailbox:
        """`mailbox` with the SMTP server and sign-in name this account needs."""
        account: str = "" if self.username.lower() == mailbox.address.lower() else self.username
        smtp_host: str = PERSONAL_SMTP_HOST if self.personal else mailbox.smtp_host
        completed: Mailbox = replace(mailbox, account=account, smtp_host=smtp_host)
        return completed


def _username(mailbox: Mailbox) -> str:
    return mailbox.account or mailbox.address


# Microsoft's codes for "this organisation lets only its administrators approve apps"
# (AADSTS65001 consent not granted, 90094/90095 admin consent required) and for an app
# the organisation has not assigned to the user (50105).
ADMIN_APPROVAL_CODES: Final[tuple[str, ...]] = ("AADSTS65001", "AADSTS90094", "AADSTS90095", "AADSTS50105")


def _needs_admin(said: str, mailbox: Mailbox) -> str:
    """What to ask IT for, when Microsoft says the organisation must approve the app."""
    if not any(code in said for code in ADMIN_APPROVAL_CODES):
        return ""
    return (
        f". Your organisation must approve email-tool first: ask IT to grant admin consent to the "
        f"application ID {mailbox.client_id} (IMAP.AccessAsUser.All and SMTP.Send), or to register "
        "the organisation's own app and give you its ID for --client-id"
    )


class MicrosoftTokens:
    """TokenSource for Microsoft mailboxes; one encrypted MSAL cache per mailbox."""

    def __init__(self, store: TokenStore, app_factory: AppFactory = msal_app) -> None:
        self._store: TokenStore = store
        self._app_factory: AppFactory = app_factory
        # One MSAL app per mailbox and authority, built once: building one costs a metadata fetch.
        self._apps: dict[tuple[str, str, str], tuple[MsalApp, msal.SerializableTokenCache]] = {}

    def _read(self, mailbox: Mailbox) -> str | None:
        try:
            return self._store.read(PROVIDER, mailbox.name)
        except SettingsError as error:
            raise SignInRequired(mailbox, str(error)) from error

    def _app(self, mailbox: Mailbox, saved: str) -> tuple[MsalApp, msal.SerializableTokenCache]:
        key: tuple[str, str, str] = (mailbox.name, mailbox.client_id, authority_of(mailbox))
        if key not in self._apps:
            fresh: msal.SerializableTokenCache = msal.SerializableTokenCache()
            self._apps[key] = (self._app_factory(mailbox.client_id, key[2], fresh), fresh)
        app: MsalApp = self._apps[key][0]
        cache: msal.SerializableTokenCache = self._apps[key][1]
        # The latest from disk: another process may have refreshed it since.
        cache.deserialize(saved)
        return app, cache

    def _drop_apps(self, mailbox: Mailbox) -> None:
        stale: list[tuple[str, str, str]] = [key for key in self._apps if key[0] == mailbox.name]
        key: tuple[str, str, str]
        for key in stale:
            del self._apps[key]

    def access_token(self, mailbox: Mailbox) -> str:
        """A valid access token, refreshed silently from the kept sign-in."""
        if not mailbox.client_id:
            raise SignInRequired(mailbox, "no app client ID is set for this mailbox")
        with self._store.lock(PROVIDER, mailbox.name):
            saved: str | None = self._read(mailbox)
            if not saved:
                raise SignInRequired(mailbox)
            app: MsalApp
            cache: msal.SerializableTokenCache
            app, cache = self._app(mailbox, saved)
            accounts: list[dict[str, Any]] = app.get_accounts(username=_username(mailbox))
            if not accounts:
                raise SignInRequired(mailbox)
            result: dict[str, Any] | None = app.acquire_token_silent(scopes_for(cloud_of(mailbox)), account=accounts[0])
            if cache.has_state_changed:
                self._store.write(PROVIDER, mailbox.name, cache.serialize())
        if not result or "access_token" not in result:
            raise SignInRequired(mailbox, str((result or {}).get("error_description", "")).split("\n")[0])
        token: str = result["access_token"]
        return token

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        """True when the kept sign-in holds this account and a refresh token for this app.

        Reads the cache only, no network, so a refresh token Microsoft has revoked
        still counts until the next refresh is refused.
        """
        if not mailbox.client_id:
            return False
        with self._store.lock(PROVIDER, mailbox.name):
            try:
                saved: str | None = self._read(mailbox)
            except SignInRequired:
                return False
        if not saved:
            return False
        cache: msal.SerializableTokenCache = msal.SerializableTokenCache()
        cache.deserialize(saved)
        wanted: str = _username(mailbox).lower()
        homes: set[str] = {
            str(account.get("home_account_id"))
            for account in cache.search(msal.TokenCache.CredentialType.ACCOUNT)
            if str(account.get("username", "")).lower() == wanted
        }
        refresh_tokens: list[dict[str, Any]] = list(
            cache.search(msal.TokenCache.CredentialType.REFRESH_TOKEN, query={"client_id": mailbox.client_id})
        )
        return any(str(token.get("home_account_id")) in homes for token in refresh_tokens)

    def forget(self, mailbox: Mailbox) -> None:
        """Delete the kept sign-in."""
        with self._store.lock(PROVIDER, mailbox.name):
            self._store.delete(PROVIDER, mailbox.name)
            self._drop_apps(mailbox)

    def sign_in(
        self,
        mailbox: Mailbox,
        device_code: bool,
        show: Callable[[str], None],
        paste: Callable[[str], str] | None = None,
        redirect: str = REDIRECT,
        open_address: Callable[[str], None] | None = None,
    ) -> SignIn:
        """Sign in once in the browser, with a device code, or by pasting back the browser's address.

        `redirect` is where a pasted sign-in ends: `http://localhost`, or the setup page's own
        loopback address (Microsoft ignores the port of a localhost redirect, RFC 8252 7.3).

        Nothing is kept until `keep`. The sign-in goes into a new cache, so a sign-in kept
        earlier is untouched if this one, or the check after it, fails.
        """
        cache: msal.SerializableTokenCache = msal.SerializableTokenCache()
        app: MsalApp = self._app_factory(mailbox.client_id, authority_of(mailbox), cache)
        scopes: list[str] = scopes_for(cloud_of(mailbox))
        result: dict[str, Any]
        if device_code:
            flow: dict[str, Any] = app.initiate_device_flow(scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Microsoft refused the device sign-in: {flow.get('error_description', flow)}")
            show(str(flow["message"]))
            result = app.acquire_token_by_device_flow(flow)
        elif paste is not None:
            with warnings.catch_warnings():
                # MSAL recommends form_post, which hides the code from the address bar; pasting
                # needs it in the query, protected by PKCE as RFC 8252 prescribes for native apps.
                warnings.filterwarnings("ignore", message="response_mode='form_post' is recommended")
                code_flow: dict[str, Any] = app.initiate_auth_code_flow(
                    scopes, redirect_uri=redirect, login_hint=mailbox.address, prompt="select_account"
                )
            answer: str = pasted_address("Microsoft", str(code_flow["auth_uri"]), redirect, show, paste, open_address)
            pairs: list[tuple[str, str]] = parse_qsl(urlsplit(answer).query)
            result = app.acquire_token_by_auth_code_flow(code_flow, dict(pairs))
        else:
            show("A browser window opens for the Microsoft sign-in; finish it there.")
            try:
                result = app.acquire_token_interactive(
                    scopes, login_hint=mailbox.address, prompt="select_account", timeout=SIGN_IN_SECONDS
                )
            except RuntimeError as error:
                raise RuntimeError(
                    f"no answer from the browser within {SIGN_IN_SECONDS // 60} minutes; nothing saved. "
                    'If the browser is on another computer, or showed "site can\'t be reached", '
                    "run again with --paste-address"
                ) from error
        if "access_token" not in result:
            said: str = str(result.get("error_description", result.get("error"))).split("\n")[0]
            raise RuntimeError(f"Microsoft sign-in failed: {said}{_needs_admin(said, mailbox)}")
        claims: dict[str, Any] = result.get("id_token_claims", {})
        username: str = str(claims.get("preferred_username") or "")
        if not username:
            raise RuntimeError("Microsoft did not say which account signed in; nothing saved")
        return SignIn(username, claims.get("tid") == PERSONAL_TENANT_ID, str(result["access_token"]), cache.serialize())

    def keep(self, mailbox: Mailbox, signed: SignIn) -> None:
        """Keep a checked sign-in for `mailbox`, replacing any earlier one."""
        with self._store.lock(PROVIDER, mailbox.name):
            self._store.write(PROVIDER, mailbox.name, signed.cache)
            self._drop_apps(mailbox)
