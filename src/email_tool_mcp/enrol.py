"""Add, remove and list mailboxes on this machine from a terminal.

Standard: getpass for hidden password entry; credentials stored with `keyring` (passwords.py).
Placement: enrol.py, the module `__main__.py` dispatches the add/remove/list commands to.

`add` proves the login works over both IMAP and SMTP before it saves anything,
so a typo never leaves a half-configured mailbox behind.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable
from pathlib import Path
from typing import Final

from email_tool_mcp.credentials import Credential, smtp_login
from email_tool_mcp.google import GoogleTokens
from email_tool_mcp.google import SignIn as GoogleSignIn
from email_tool_mcp.google import preset as google_preset
from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.mailbox_book import MailboxBook, open_smtp
from email_tool_mcp.microsoft import DEFAULT_CLIENT_ID, MicrosoftTokens, SignIn
from email_tool_mcp.microsoft import preset as microsoft_preset
from email_tool_mcp.passwords import normalize_password, store_password
from email_tool_mcp.policy import Policy, policy_paths
from email_tool_mcp.settings import (
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    SETUP_COMMAND,
    Mailbox,
    load_mailboxes,
    save_mailboxes,
)

Ask = Callable[[str], str]
LoginCheck = Callable[[Mailbox, Credential], None]
# Deletes a mailbox's password or sign-in; False when nothing could be deleted.
Forget = Callable[[Mailbox], bool]

KNOWN_HOSTS: Final[dict[str, tuple[str, str]]] = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
}
_GMAIL_NOTE: Final[str] = "Gmail needs an App Password (Google Account > Security > App passwords), not your password."


def check_login(mailbox: Mailbox, credential: Credential) -> None:
    """Log in over IMAP and SMTP with a password or a token; raise if either refuses."""
    with ImapSession(mailbox, credential):
        pass
    with open_smtp(mailbox) as smtp:
        smtp_login(smtp, credential)


def save_mailbox(settings_file: Path, mailbox: Mailbox, forget: Forget) -> str:
    """Save `mailbox`; when it replaces one that logged in another way, delete that old login.

    The new mailbox is saved and working either way, so a failed clean-up is reported
    (returned as a note), not raised.
    """
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    previous: Mailbox | None = mailboxes.get(mailbox.name)
    mailboxes[mailbox.name] = mailbox
    save_mailboxes(settings_file, mailboxes)
    if previous is None or previous.auth == mailbox.auth:
        return ""
    try:
        if forget(previous):
            return f" Its old {previous.auth} login was deleted."
    except Exception as error:
        return f" Its old {previous.auth} login could not be deleted ({type(error).__name__}); remove it by hand."
    return f" Its old {previous.auth} login was left in place (not supported by this version)."


def ask_with_default(ask: Ask, prompt: str, default: str) -> str:
    """Ask `prompt`, returning `default` when the answer is blank."""
    shown: str = f"{prompt} [{default}]: " if default else f"{prompt}: "
    return ask(shown).strip() or default


def add_mailbox(
    name: str,
    settings_file: Path,
    address: str = "",
    imap_host: str = "",
    imap_port: int = DEFAULT_IMAP_PORT,
    smtp_host: str = "",
    smtp_port: int = DEFAULT_SMTP_PORT,
    ask: Ask = input,
    ask_secret: Ask = getpass.getpass,
    login_check: LoginCheck = check_login,
    policy: Policy | None = None,
    *,
    forget: Forget,
) -> str:
    """Ask for anything missing, check the login, then save the mailbox and its password."""
    address = address or ask_with_default(ask, "Email address", "")
    domain: str = address.rpartition("@")[2].lower()
    known: tuple[str, str] = KNOWN_HOSTS.get(domain, ("", ""))
    imap_host = imap_host or ask_with_default(ask, "IMAP server", known[0])
    smtp_host = smtp_host or ask_with_default(ask, "SMTP server", known[1])
    if not (address and imap_host and smtp_host):
        raise ValueError("an address, an IMAP server and an SMTP server are all required")
    mailbox: Mailbox = Mailbox(name, address, imap_host, imap_port, smtp_host, smtp_port)

    note: str = f" ({_GMAIL_NOTE})" if known[0] == "imap.gmail.com" else ""
    password: str = normalize_password(ask_secret(f"Password for {address}{note}: "))
    if not password:
        raise ValueError("no password entered")
    (policy if policy is not None else Policy(policy_paths())).check_fips(name, address, keeps_sign_in=False)
    login_check(mailbox, Credential(address, password, is_token=False))

    # Password first: a keyring that refuses it must not leave a mailbox saved without one.
    store_password(name, password)
    cleanup: str = save_mailbox(settings_file, mailbox, forget)
    return (
        f"Mailbox {name!r} ({address}) added. Login checked over IMAP and SMTP; password is in the OS keyring.{cleanup}"
    )


def add_microsoft_mailbox(
    name: str,
    settings_file: Path,
    tokens: MicrosoftTokens,
    address: str,
    client_id: str,
    tenant: str = "",
    cloud: str = "commercial",
    device_code: bool = False,
    show: Callable[[str], None] = print,
    login_check: LoginCheck = check_login,
    policy: Policy | None = None,
    *,
    forget: Forget,
) -> str:
    """Sign in with Microsoft, check IMAP and SMTP with the token, then keep the sign-in and save.

    No password is stored: the encrypted sign-in refreshes itself. Nothing is kept
    until the check passes, so a failed attempt leaves an earlier sign-in as it was.
    """
    if not address:
        raise ValueError("give the mailbox address with --address")
    if not client_id and cloud != "commercial":
        raise ValueError(
            "GCC High needs an app registered in GCC High: give its Application (client) ID with "
            "--client-id (Microsoft Entra > App registrations > your app > Overview)"
        )
    client_id = client_id or DEFAULT_CLIENT_ID
    provisional: Mailbox = microsoft_preset(name, address, client_id, tenant, cloud)
    (policy if policy is not None else Policy(policy_paths())).check_fips(name, address, keeps_sign_in=True)
    signed: SignIn = tokens.sign_in(provisional, device_code, show)
    mailbox: Mailbox = signed.complete(provisional)
    # The real login decides: a Microsoft 365 user name may differ from the address it opens.
    show(f"Signed in as {signed.username}; checking IMAP and SMTP for {address}.")
    login_check(mailbox, Credential(address, signed.access_token, is_token=True))
    tokens.keep(mailbox, signed)
    note: str = save_mailbox(settings_file, mailbox, forget)
    return (
        f"Mailbox {name!r} ({address}) added. Signed in with Microsoft; IMAP and SMTP checked. "
        f"No password stored.{note}"
    )


def add_google_mailbox(
    name: str,
    settings_file: Path,
    tokens: GoogleTokens,
    address: str,
    client_secrets: str,
    show: Callable[[str], None] = print,
    login_check: LoginCheck = check_login,
    policy: Policy | None = None,
    *,
    forget: Forget,
    paste: Ask | None = None,
) -> str:
    """Sign in with Google, check IMAP and SMTP with the token, then keep the sign-in and save.

    For Google Workspace accounts whose administrator turned off App Passwords. Nothing
    is kept until the check passes.
    """
    if not address:
        raise ValueError("give the Google account's address with --address")
    secrets: Path = Path(client_secrets).expanduser()
    if not client_secrets or not secrets.is_file():
        raise ValueError(
            "give the OAuth client file with --client-secrets (Google Cloud > Google Auth Platform > "
            "Clients > your Desktop client > Download JSON); see the README's Google section"
        )
    provisional: Mailbox = google_preset(name, address)
    (policy if policy is not None else Policy(policy_paths())).check_fips(name, address, keeps_sign_in=True)
    signed: GoogleSignIn = tokens.sign_in(provisional, secrets, show, paste)
    mailbox: Mailbox = signed.complete(provisional)
    login_check(mailbox, Credential(address, signed.access_token, is_token=True))
    tokens.keep(mailbox, signed)
    cleanup: str = save_mailbox(settings_file, mailbox, forget)
    return (
        f"Mailbox {name!r} ({address}) added. Signed in with Google; IMAP and SMTP checked. "
        f"No password stored.{cleanup}"
    )


def add_by_auth(
    name: str,
    settings_file: Path,
    auth: str,
    microsoft: MicrosoftTokens,
    google: GoogleTokens,
    forget: Forget,
    address: str = "",
    imap_host: str = "",
    imap_port: int = DEFAULT_IMAP_PORT,
    smtp_host: str = "",
    smtp_port: int = DEFAULT_SMTP_PORT,
    client_id: str = "",
    tenant: str = "",
    cloud: str = "commercial",
    device_code: bool = False,
    client_secrets: str = "",
    paste_address: bool = False,
) -> str:
    """The `add` command: refuse options that do not apply to `auth`, then add the mailbox."""
    servers: bool = bool(imap_host or smtp_host) or (imap_port, smtp_port) != (DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT)
    microsoft_options: bool = bool(client_id or tenant or device_code) or cloud != "commercial"
    if auth in ("microsoft", "google") and servers:
        raise ValueError(f"--auth {auth} sets the servers itself; drop --imap-*/--smtp-*")
    if auth != "microsoft" and microsoft_options:
        raise ValueError("--client-id, --tenant, --cloud and --device-code need --auth microsoft")
    if auth != "google" and (client_secrets or paste_address):
        raise ValueError("--client-secrets and --paste-address need --auth google")
    if auth == "microsoft":
        return add_microsoft_mailbox(
            name, settings_file, microsoft, address, client_id, tenant, cloud, device_code, forget=forget
        )
    if auth == "google":
        return add_google_mailbox(
            name, settings_file, google, address, client_secrets, forget=forget, paste=input if paste_address else None
        )
    if auth != "password":
        raise ValueError(f"--auth must be password, microsoft or google, not {auth!r}")
    return add_mailbox(name, settings_file, address, imap_host, imap_port, smtp_host, smtp_port, forget=forget)


def remove_mailbox(name: str, book: MailboxBook, settings_file: Path) -> str:
    """Forget the mailbox called `name` and delete its password or stored sign-in."""
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    removed: Mailbox | None = mailboxes.pop(name, None)
    if removed is None:
        raise ValueError(f"no mailbox called {name!r}")
    deleted: bool = book.forget(removed)
    save_mailboxes(settings_file, mailboxes)
    what: str = (
        "password deleted from the OS keyring" if removed.auth == "password" else f"{removed.auth} sign-in deleted"
    )
    if not deleted:
        what = f"its {removed.auth} sign-in left in place (not supported by this version)"
    return f"Mailbox {name!r} removed, {what}."


def describe_mailboxes(book: MailboxBook, settings_file: Path) -> str:
    """Return one line per mailbox: name, address, servers, how it logs in."""
    mailboxes: dict[str, Mailbox] = load_mailboxes(settings_file)
    if not mailboxes:
        return f"No mailboxes yet ({settings_file}). Add one with `{SETUP_COMMAND} <name>`."
    lines: list[str] = [f"Settings: {settings_file}"]
    for name, mailbox in sorted(mailboxes.items()):
        problem: str = book.login_problem(mailbox)
        ready: str = "password in keyring" if mailbox.auth == "password" else f"signed in to {mailbox.auth}"
        state: str = problem.upper() if problem else ready
        lines.append(
            f"{name}: {mailbox.address}  imap {mailbox.imap_host}:{mailbox.imap_port}  "
            f"smtp {mailbox.smtp_host}:{mailbox.smtp_port}  ({state})"
        )
    return "\n".join(lines)
