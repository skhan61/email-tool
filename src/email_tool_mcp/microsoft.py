"""Microsoft sign-in for Outlook.com, Microsoft 365 and GCC High mailboxes.

Standard: MSAL for Python (Microsoft's own library): a public client with browser
sign-in on `http://localhost` (or device code), silent refresh from its token cache,
and the delegated scopes Microsoft documents for IMAP and SMTP
(`IMAP.AccessAsUser.All`, `SMTP.Send`). The cache is kept encrypted in token_store.
Placement: microsoft.py; MailboxBook asks it for tokens, enrol.py for the first sign-in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import msal

from email_tool_mcp.settings import SETUP_COMMAND, Mailbox
from email_tool_mcp.token_store import TokenStore

PROVIDER: Final[Literal["microsoft"]] = "microsoft"
# Mail domains that are personal Microsoft accounts (Outlook.com).
PERSONAL_DOMAINS: Final[frozenset[str]] = frozenset({"outlook.com", "hotmail.com", "live.com", "msn.com"})


@dataclass(frozen=True)
class Cloud:
    """Where one Microsoft cloud signs in and serves mail."""

    login_host: str
    resource: str
    imap_host: str
    smtp_host: str


COMMERCIAL: Final[Cloud] = Cloud(
    "login.microsoftonline.com", "outlook.office.com", "outlook.office365.com", "smtp.office365.com"
)
GCC_HIGH: Final[Cloud] = Cloud(
    "login.microsoftonline.us", "outlook.office365.us", "outlook.office365.us", "smtp.office365.us"
)
CLOUDS: Final[dict[str, Cloud]] = {"commercial": COMMERCIAL, "gcc-high": GCC_HIGH}
PERSONAL_SMTP_HOST: Final[str] = "smtp-mail.outlook.com"
SMTP_STARTTLS_PORT: Final[int] = 587


class SignInRequired(PermissionError):
    """The stored sign-in is missing, expired or revoked; the user must sign in again."""

    def __init__(self, mailbox: Mailbox, detail: str = "") -> None:
        reason: str = f" ({detail})" if detail else ""
        super().__init__(
            f"{mailbox.name} needs a new Microsoft sign-in{reason}. "
            f"Run `{SETUP_COMMAND} {mailbox.name} --auth microsoft` in a terminal."
        )


class MsalApp(Protocol):
    """The part of msal.PublicClientApplication used here."""

    def get_accounts(self, username: str | None = None) -> list[dict[str, Any]]: ...

    def acquire_token_silent(self, scopes: list[str], account: dict[str, Any]) -> dict[str, Any] | None: ...

    def acquire_token_interactive(self, scopes: list[str], **options: Any) -> dict[str, Any]: ...

    def initiate_device_flow(self, scopes: list[str]) -> dict[str, Any]: ...

    def acquire_token_by_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]: ...


AppFactory = Callable[[str, str, msal.SerializableTokenCache], MsalApp]


def msal_app(client_id: str, authority: str, cache: msal.SerializableTokenCache) -> MsalApp:
    """A real MSAL public client application."""
    app: MsalApp = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)
    return app


def cloud_of(mailbox: Mailbox) -> Cloud:
    """The cloud a mailbox's servers belong to (GCC High hosts end in `.us`)."""
    return GCC_HIGH if mailbox.imap_host.endswith(".us") else COMMERCIAL


def scopes_for(cloud: Cloud) -> list[str]:
    """The delegated IMAP and SMTP scopes in one cloud (offline_access is added by MSAL)."""
    return [f"https://{cloud.resource}/IMAP.AccessAsUser.All", f"https://{cloud.resource}/SMTP.Send"]


def preset(name: str, address: str, client_id: str, tenant: str, cloud: str) -> Mailbox:
    """A Microsoft mailbox with the right servers and directory for its address and cloud."""
    if cloud not in CLOUDS:
        raise ValueError(f"cloud must be one of {sorted(CLOUDS)}, not {cloud!r}")
    chosen: Cloud = CLOUDS[cloud]
    personal: bool = address.rpartition("@")[2].lower() in PERSONAL_DOMAINS
    if personal and cloud != "commercial":
        raise ValueError("Outlook.com accounts exist only in the commercial cloud")
    return Mailbox(
        name=name,
        address=address,
        imap_host=chosen.imap_host,
        imap_port=993,
        smtp_host=PERSONAL_SMTP_HOST if personal else chosen.smtp_host,
        smtp_port=SMTP_STARTTLS_PORT,
        auth=PROVIDER,
        client_id=client_id,
        tenant=tenant or ("consumers" if personal else "organizations"),
    )


class MicrosoftTokens:
    """TokenSource for Microsoft mailboxes; one encrypted MSAL cache per mailbox."""

    def __init__(self, store: TokenStore, app_factory: AppFactory = msal_app) -> None:
        self._store: TokenStore = store
        self._app_factory: AppFactory = app_factory

    def _open(self, mailbox: Mailbox) -> tuple[MsalApp, msal.SerializableTokenCache]:
        if not mailbox.client_id:
            raise SignInRequired(mailbox, "no app client ID is set for this mailbox")
        cache: msal.SerializableTokenCache = msal.SerializableTokenCache()
        saved: str | None = self._store.read(PROVIDER, mailbox.name)
        if saved:
            cache.deserialize(saved)
        authority: str = f"https://{cloud_of(mailbox).login_host}/{mailbox.tenant or 'common'}"
        return self._app_factory(mailbox.client_id, authority, cache), cache

    def _save(self, mailbox: Mailbox, cache: msal.SerializableTokenCache) -> None:
        if cache.has_state_changed:
            self._store.write(PROVIDER, mailbox.name, cache.serialize())

    def access_token(self, mailbox: Mailbox) -> str:
        """A valid access token, refreshed silently from the cached sign-in."""
        app, cache = self._open(mailbox)
        accounts: list[dict[str, Any]] = app.get_accounts(username=mailbox.address)
        if not accounts:
            raise SignInRequired(mailbox)
        result: dict[str, Any] | None = app.acquire_token_silent(scopes_for(cloud_of(mailbox)), account=accounts[0])
        self._save(mailbox, cache)
        if not result or "access_token" not in result:
            raise SignInRequired(mailbox, str((result or {}).get("error_description", "")).split("\n")[0])
        token: str = result["access_token"]
        return token

    def is_signed_in(self, mailbox: Mailbox) -> bool:
        """True when a cached sign-in for this address exists (no network)."""
        if not self._store.exists(PROVIDER, mailbox.name):
            return False
        app: MsalApp = self._open(mailbox)[0]
        return bool(app.get_accounts(username=mailbox.address))

    def forget(self, mailbox: Mailbox) -> None:
        """Delete the cached sign-in."""
        self._store.delete(PROVIDER, mailbox.name)

    def sign_in(self, mailbox: Mailbox, device_code: bool, show: Callable[[str], None]) -> None:
        """Sign in once in the browser (or with a device code) and keep the result.

        The account that signs in must be `mailbox.address`; any other account is refused
        and nothing is stored.
        """
        app, cache = self._open(mailbox)
        scopes: list[str] = scopes_for(cloud_of(mailbox))
        result: dict[str, Any]
        if device_code:
            flow: dict[str, Any] = app.initiate_device_flow(scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Microsoft refused the device sign-in: {flow.get('error_description', flow)}")
            show(str(flow["message"]))
            result = app.acquire_token_by_device_flow(flow)
        else:
            show("A browser window opens for the Microsoft sign-in; finish it there.")
            result = app.acquire_token_interactive(scopes, login_hint=mailbox.address, prompt="select_account")
        if "access_token" not in result:
            raise RuntimeError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))}")
        claims: dict[str, Any] = result.get("id_token_claims", {})
        signed_in: str = str(claims.get("preferred_username") or claims.get("email") or "")
        if signed_in.lower() != mailbox.address.lower():
            raise RuntimeError(
                f"signed in as {signed_in or 'an unknown account'}, not {mailbox.address}; nothing saved"
            )
        self._save(mailbox, cache)
