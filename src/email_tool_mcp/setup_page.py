"""A one-time setup page on this computer: add a mailbox without a terminal.

Standard: Starlette (routes, forms, file upload through python-multipart) served by uvicorn,
all installed with the MCP SDK; Microsoft and Google sign in through the native-app loopback
redirect (RFC 8252 7.3), here the page's own address.
Placement: setup_page.py; tools/setup.py starts it for the `add_mailbox` tool.

The page runs the same steps as `email-tool-mcp add` (enrol.py): the login is checked over
IMAP and SMTP before anything is saved, a password goes only into the keyring, and policy's
FIPS rule applies. A password is typed only into this page and never passes through the
assistant.

Security: bound to 127.0.0.1 and, when this computer has it, ::1 on the same random port, both
exclusively, so no other program can answer the `localhost` sign-in return. Every page path
carries a 256-bit token compared in constant time. The Host header must name this loopback
address, which stops DNS rebinding, and a form post must come from this page's own origin
(`Referrer-Policy: same-origin` keeps the browser sending it, and keeps the token out of the
Referer sent to Microsoft and Google). One sign-in at a time. A Google client file is deleted
as soon as Google's sign-in address exists. The page closes after one mailbox or when its time
runs out. Each mailbox it adds is audit-logged (name, address, kind, outcome; never a password),
and nothing else is logged: uvicorn's access log is off, since the return carries a one-time code.
"""

from __future__ import annotations

import hmac
import html
import queue
import re
import secrets
import shutil
import socket
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from email_tool_mcp.audit import AuditError, AuditLog
from email_tool_mcp.enrol import (
    KNOWN_HOSTS,
    Forget,
    LoginCheck,
    add_google_mailbox,
    add_mailbox,
    add_microsoft_mailbox,
    check_login,
)
from email_tool_mcp.google import GoogleTokens
from email_tool_mcp.microsoft import MicrosoftTokens
from email_tool_mcp.settings import DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT, Mailbox, load_mailboxes

LIFETIME_SECONDS: Final[float] = 600.0
# How long the page waits for Microsoft or Google to hand over their sign-in address.
_SIGN_IN_START_SECONDS: Final[float] = 60.0
_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
_KINDS: Final[tuple[str, ...]] = ("gmail", "microsoft", "google", "password")
_TOOL: Final[str] = "add_mailbox"
# Same-origin: the browser keeps sending Origin on this page's form posts, and sends no Referer
# (which would carry the token) to Microsoft or Google.
_HEADERS: Final[dict[str, str]] = {"Referrer-Policy": "same-origin", "Cache-Control": "no-store"}


@dataclass
class _SignIn:
    """A Microsoft or Google sign-in running in a worker thread, waiting for the browser to return."""

    # Where the provider sends the browser back: this page's root, as the sign-in registered it.
    redirect: str
    address: queue.Queue[str] = field(default_factory=queue.Queue)
    returned: queue.Queue[str] = field(default_factory=queue.Queue)
    outcome: queue.Queue[tuple[bool, str]] = field(default_factory=queue.Queue)


class SetupPage:
    """The setup page: started by the `add_mailbox` tool, closed after one mailbox or its lifetime."""

    def __init__(
        self,
        settings_file: Path,
        forget: Forget,
        microsoft: Callable[[], MicrosoftTokens],
        google: Callable[[], GoogleTokens],
        login_check: LoginCheck = check_login,
        lifetime: float = LIFETIME_SECONDS,
        audit: AuditLog | None = None,
    ) -> None:
        self._settings_file: Path = settings_file
        self._forget: Forget = forget
        self._microsoft: Callable[[], MicrosoftTokens] = microsoft
        self._google: Callable[[], GoogleTokens] = google
        self._login_check: LoginCheck = login_check
        self._lifetime: float = lifetime
        self._audit: AuditLog | None = audit
        self._lock: threading.Lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._timer: threading.Timer | None = None
        self._token: str = ""
        self._port: int = 0
        self._pending: _SignIn | None = None
        self._result: str = ""
        self.elicitation_id: str = ""

    @property
    def url(self) -> str:
        """The page's address, or "" when it is not running."""
        return f"http://127.0.0.1:{self._port}/s/{self._token}" if self._server is not None else ""

    def start(self) -> str:
        """Start the page (or keep the running one) and return its address."""
        with self._lock:
            if self._server is not None:
                return self.url
            self._token = secrets.token_urlsafe(32)
            self.elicitation_id = secrets.token_urlsafe(16)
            sockets: list[socket.socket] = _loopback_sockets()
            self._port = int(sockets[0].getsockname()[1])
            config: uvicorn.Config = uvicorn.Config(
                self._app(), log_level="warning", access_log=False, log_config=None, lifespan="off"
            )
            server: uvicorn.Server = uvicorn.Server(config)
            self._server = server
            threading.Thread(target=server.run, kwargs={"sockets": sockets}, daemon=True).start()
            self._timer = threading.Timer(self._lifetime, self.stop)
            self._timer.daemon = True
            self._timer.start()
            return self.url

    def take_result(self) -> str:
        """What the page added since it was last asked, once; "" when nothing."""
        with self._lock:
            result: str = self._result
            self._result = ""
            return result

    def _finish(self, result: str) -> None:
        with self._lock:
            self._result = result
        self.stop()

    def stop(self) -> None:
        """Close the page; its address and token stop working, and a waiting sign-in gives up."""
        with self._lock:
            if self._server is not None:
                self._server.should_exit = True
            if self._timer is not None:
                self._timer.cancel()
            pending: _SignIn | None = self._pending
            self._server = None
            self._timer = None
            self._token = ""
            self._pending = None
        if pending is not None:
            # Wakes the sign-in thread, which then fails, cleans up and ends.
            pending.returned.put("")

    # Audit ----------------------------------------------------------------------------------------

    def _audit_started(self, name: str, address: str, kind: str) -> str:
        """Record the attempt before anything is saved; AuditError refuses it (fail closed)."""
        if self._audit is None:
            return ""
        return self._audit.started(name, _TOOL, {"kind": kind, "address": address})

    def _audit_finished(self, call: str, name: str, outcome: str) -> None:
        if self._audit is not None and call:
            try:
                self._audit.finished(call, name, _TOOL, outcome)
            except AuditError:
                pass

    # Requests -------------------------------------------------------------------------------------

    def _app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/", self._returned, methods=["GET"]),
                Route("/s/{token}", self._choose, methods=["GET"]),
                Route("/s/{token}/add", self._add, methods=["POST"]),
            ]
        )

    def _shown(self, title: str, body: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(_page(title, body), status_code=status, headers=_HEADERS)

    def _again(self, problem: str, status: int = 400) -> HTMLResponse:
        return self._shown("Add a mailbox", _form(self._token, problem), status)

    def _allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self._port}", f"localhost:{self._port}", f"[::1]:{self._port}"}

    def _refusal(self, request: Request, posted: bool) -> Response | None:
        """A 403 or 404 when the request is not this page's own; None when it is."""
        if request.headers.get("host", "") not in self._allowed_hosts():
            return Response("Not this page.", status_code=403)
        if posted and request.headers.get("origin", "") not in {f"http://{host}" for host in self._allowed_hosts()}:
            return Response("Not from this page.", status_code=403)
        token: str = str(request.path_params.get("token", ""))
        if "token" in request.path_params and not (
            self._token and hmac.compare_digest(token.encode(), self._token.encode())
        ):
            return Response("This setup page has closed. Ask your assistant to add a mailbox again.", 404)
        return None

    async def _choose(self, request: Request) -> Response:
        refused: Response | None = self._refusal(request, posted=False)
        return refused or self._shown("Add a mailbox", _form(self._token, ""))

    async def _add(self, request: Request) -> Response:
        refused: Response | None = self._refusal(request, posted=True)
        if refused is not None:
            return refused
        form: FormData = await request.form()
        kind: str = str(form.get("kind", ""))
        address: str = str(form.get("address", "")).strip()
        known: dict[str, Mailbox] = load_mailboxes(self._settings_file) if self._settings_file.exists() else {}
        name: str = str(form.get("name", "")).strip() or _name_for(address, known)
        problem: str = _invalid(kind, name, address) or _clash(name, address, known)
        if problem:
            return self._again(problem)
        if kind in ("gmail", "password"):
            return await self._add_with_password(form, kind, name, address)
        upload: object = form.get("client_file")
        return await self._start_sign_in(kind, name, address, upload if isinstance(upload, UploadFile) else None)

    async def _add_with_password(self, form: FormData, kind: str, name: str, address: str) -> Response:
        domain: str = address.rpartition("@")[2].lower()
        known: tuple[str, str] = KNOWN_HOSTS.get(domain, ("", "")) if kind == "gmail" else ("", "")
        imap_host: str = str(form.get("imap_host", "")).strip() or known[0]
        smtp_host: str = str(form.get("smtp_host", "")).strip() or known[1]
        password: str = str(form.get("password", ""))

        def nothing_more(prompt: str) -> str:
            return ""

        def the_password(prompt: str) -> str:
            return password

        try:
            call: str = self._audit_started(name, address, kind)
        except AuditError as error:
            return self._again(f"Refused, nothing was done: {error}", 503)
        try:
            imap_port: int = int(str(form.get("imap_port", "")).strip() or DEFAULT_IMAP_PORT)
            smtp_port: int = int(str(form.get("smtp_port", "")).strip() or DEFAULT_SMTP_PORT)
            done: str = await run_in_threadpool(
                add_mailbox,
                name,
                self._settings_file,
                address,
                imap_host,
                imap_port,
                smtp_host,
                smtp_port,
                nothing_more,
                the_password,
                self._login_check,
                forget=self._forget,
            )
        except Exception as error:
            self._audit_finished(call, name, f"{type(error).__name__}: {_reason(error)}")
            return self._again(_reason(error))
        self._audit_finished(call, name, "ok")
        self._finish(done)
        return self._shown("Mailbox added", _done(done))

    async def _start_sign_in(self, kind: str, name: str, address: str, upload: UploadFile | None) -> Response:
        if kind == "google" and (upload is None or not upload.filename):
            return self._again("Choose your Google client file (client_secret_….json).")
        # Microsoft's app registers `http://localhost` and Google's loopback `http://localhost/`.
        redirect: str = f"http://localhost:{self._port}" + ("/" if kind == "google" else "")
        pending: _SignIn = _SignIn(redirect)
        with self._lock:
            if self._pending is not None:
                busy: bool = True
            else:
                busy = False
                self._pending = pending
        if busy:
            return self._again("A sign-in is already open in another tab. Finish it there, or close this page.", 409)
        try:
            call: str = self._audit_started(name, address, kind)
        except AuditError as error:
            with self._lock:
                self._pending = None
            return self._again(f"Refused, nothing was done: {error}", 503)
        client_folder: Path | None = None
        client_file: Path = Path()
        if upload is not None and kind == "google":
            client_folder = Path(tempfile.mkdtemp(prefix="email-tool-"))
            client_file = client_folder / "client.json"
            client_file.write_bytes(await upload.read())
            client_file.chmod(0o600)

        def forget_client_file() -> None:
            if client_folder is not None:
                shutil.rmtree(client_folder, ignore_errors=True)

        def open_address(sign_in_address: str) -> None:
            # Google has read the client file by now: it is not kept a moment longer.
            forget_client_file()
            pending.address.put(sign_in_address)

        def wait_for_browser(prompt: str) -> str:
            return pending.returned.get(timeout=self._lifetime)

        def no_terminal(text: str) -> None:
            return None

        def sign_in() -> None:
            try:
                if kind == "microsoft":
                    done: str = add_microsoft_mailbox(
                        name,
                        self._settings_file,
                        self._microsoft(),
                        address,
                        "",
                        show=no_terminal,
                        login_check=self._login_check,
                        forget=self._forget,
                        paste=wait_for_browser,
                        redirect=redirect,
                        open_address=open_address,
                    )
                else:
                    done = add_google_mailbox(
                        name,
                        self._settings_file,
                        self._google(),
                        address,
                        str(client_file),
                        show=no_terminal,
                        login_check=self._login_check,
                        forget=self._forget,
                        paste=wait_for_browser,
                        redirect=redirect,
                        open_address=open_address,
                    )
            except Exception as error:
                self._audit_finished(call, name, f"{type(error).__name__}: {_reason(error)}")
                pending.outcome.put((False, _reason(error)))
            else:
                self._audit_finished(call, name, "ok")
                # Recorded here, not by the page, so a page that stopped waiting still reports it.
                self._finish(done)
                pending.outcome.put((True, done))
            finally:
                forget_client_file()
                pending.address.put("")

        threading.Thread(target=sign_in, daemon=True).start()
        try:
            target: str = await run_in_threadpool(pending.address.get, True, _SIGN_IN_START_SECONDS)
        except queue.Empty:
            target = ""
        if not target:
            self.stop()
            failed: str = (
                pending.outcome.get_nowait()[1] if not pending.outcome.empty() else "the sign-in did not start"
            )
            return self._again(failed)
        return RedirectResponse(target, status_code=303, headers=_HEADERS)

    async def _returned(self, request: Request) -> Response:
        """Where Microsoft or Google send the browser back, with a one-time code or an error."""
        refused: Response | None = self._refusal(request, posted=False)
        if refused is not None:
            return refused
        query: str = request.url.query
        with self._lock:
            pending: _SignIn | None = self._pending if query else None
            self._pending = None
        if pending is None:
            return Response("No sign-in is waiting here.", status_code=404)
        said: dict[str, list[str]] = parse_qs(query)
        if "code" not in said:
            explained: str = (said.get("error_description") or said.get("error") or ["the sign-in was cancelled"])[0]
            pending.returned.put("")
            return self._again(f"The sign-in did not finish: {explained}")
        pending.returned.put(f"{pending.redirect}?{query}")
        try:
            succeeded: bool
            message: str
            succeeded, message = await run_in_threadpool(pending.outcome.get, True, self._lifetime)
        except queue.Empty:
            return self._shown(
                "Still checking",
                "<p>The login check is taking long. Go back to your assistant and ask whether the mailbox "
                "was added.</p>",
                202,
            )
        if not succeeded:
            return self._again(message)
        return self._shown("Mailbox added", _done(message))


def _listener(family: socket.AddressFamily, address: tuple[str, int]) -> socket.socket:
    """A listening socket no other program can share (no SO_REUSEADDR; exclusive on Windows)."""
    listener: socket.socket = socket.socket(family, socket.SOCK_STREAM)
    try:
        exclusive: int | None = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        if family == socket.AF_INET6:
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        listener.bind(address)
        listener.listen()
    except OSError:
        listener.close()
        raise
    return listener


def _has_ipv6_loopback() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        _listener(socket.AF_INET6, ("::1", 0)).close()
    except OSError:
        return False
    return True


def _loopback_sockets() -> list[socket.socket]:
    """127.0.0.1 at a free port, plus ::1 on the same port whenever this computer has ::1.

    Both, because browsers may resolve `localhost` to either; a port whose ::1 side is taken is
    never used, so no other program can receive a sign-in code meant for this page.
    """
    both: bool = _has_ipv6_loopback()
    _attempt: int
    for _attempt in range(20):
        first: socket.socket = _listener(socket.AF_INET, ("127.0.0.1", 0))
        if not both:
            return [first]
        try:
            second: socket.socket = _listener(socket.AF_INET6, ("::1", int(first.getsockname()[1])))
        except OSError:
            first.close()
            continue
        return [first, second]
    raise RuntimeError("no port is free on both 127.0.0.1 and ::1; nothing was started")


def _name_for(address: str, known: dict[str, Mailbox]) -> str:
    """The name of the mailbox already enrolled for `address`, or a new one from its provider."""
    mailbox: Mailbox
    for mailbox in known.values():
        if mailbox.address.lower() == address.lower():
            return mailbox.name
    return _free_name(address, set(known))


def _clash(name: str, address: str, known: dict[str, Mailbox]) -> str:
    """Why `name` cannot be used for `address`: it names another address's mailbox. "" when free,
    or when it is this address's own mailbox, which is then signed in again."""
    existing: Mailbox | None = known.get(name)
    if existing is None or existing.address.lower() == address.lower():
        return ""
    return f"You already have a mailbox called {name}, for {existing.address}. Choose another name."


def _free_name(address: str, taken: set[str]) -> str:
    """A name from the address's provider (gmail, outlook, example), numbered when already used."""
    provider: str = re.sub(r"[^A-Za-z0-9_-]", "", address.rpartition("@")[2].split(".")[0])[:30] or "mail"
    name: str = provider
    number: int = 2
    while name in taken:
        name = f"{provider}{number}"
        number += 1
    return name


def _invalid(kind: str, name: str, address: str) -> str:
    """Why the form cannot be used as sent; "" when it can."""
    if kind not in _KINDS:
        return "Choose what kind of mailbox it is."
    if not _NAME.match(name):
        return "A name may use only letters, numbers, - or _, such as work or personal."
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        return "Type the full email address, such as you@example.com."
    return ""


def _reason(error: Exception) -> str:
    """The error as one plain sentence; never a password (none is ever put into an error)."""
    return str(error) or type(error).__name__


def _done(message: str) -> str:
    return (
        f"<p class='ok'>{html.escape(message)}</p>"
        "<p>You can close this page and go back to your assistant. To add another mailbox, ask it again.</p>"
    )


def _form(token: str, problem: str) -> str:
    """The choice of mailbox kind and the fields each kind needs; one form, so it works without script."""
    shown: str = f"<p class='problem' role='alert'>{html.escape(problem)}</p>" if problem else ""
    action: str = f"/s/{html.escape(token)}/add"
    return f"""{shown}
<form method="post" action="{action}" enctype="multipart/form-data">
  <fieldset>
    <legend>What kind of mailbox is it?</legend>
    <label><input type="radio" name="kind" value="gmail" checked> Gmail (an address ending in @gmail.com)</label>
    <label><input type="radio" name="kind" value="microsoft"> Outlook.com, Hotmail or Microsoft 365</label>
    <label><input type="radio" name="kind" value="google"> Google Workspace at a company or school</label>
    <label><input type="radio" name="kind" value="password">
      Any other mailbox (your own domain or a hosting company)</label>
  </fieldset>
  <label>Email address <input name="address" type="email" autocomplete="email" required></label>
  <label>Password (Gmail and any other mailbox; Outlook and Google Workspace do not need one)
    <input name="password" type="password" autocomplete="off"></label>
  <p class="hint">For Gmail, use an
  <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">App Password</a>,
  not your Google password. The password is kept on this computer only, never sent to the assistant.</p>
  <details>
    <summary>Any other mailbox: server names</summary>
    <p>From your provider's help pages, for example mail.example.com.</p>
    <label>IMAP server <input name="imap_host"></label>
    <label>SMTP server <input name="smtp_host"></label>
  </details>
  <details>
    <summary>Google Workspace: your Google client file</summary>
    <p>The <code>client_secret_….json</code> file from Google Cloud
    (<a href="https://skhan61.github.io/email-tool/mailboxes/#google-workspace"
    target="_blank" rel="noopener">steps</a>).</p>
    <label>Client file <input name="client_file" type="file" accept=".json,application/json"></label>
  </details>
  <details>
    <summary>Name this mailbox (optional)</summary>
    <label>Name, such as work or personal
    <input name="name" pattern="[A-Za-z0-9][A-Za-z0-9_-]{{0,39}}"></label>
  </details>
  <p>Outlook, Microsoft 365 and Google Workspace open their own sign-in page next.</p>
  <button type="submit">Add mailbox</button>
</form>"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>email-tool: {html.escape(title)}</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; color: #1b1b1b; }}
h1 {{ font-size: 1.5rem; }} label {{ display: block; margin: .6rem 0; }}
input[type=email], input[name=name], input[type=password], input[name$=_host] {{
  display: block; width: 100%; padding: .4rem; }}
fieldset {{ border: 1px solid #ccc; padding: .5rem 1rem; }} details {{ margin: 1rem 0; }}
button {{ font-size: 1rem; padding: .5rem 1.2rem; }} .problem {{ color: #a40000; font-weight: 600; }}
.hint {{ margin-top: -.3rem; color: #444; font-size: .9rem; }}
.ok {{ color: #0a6b2d; font-weight: 600; }}
</style></head>
<body><h1>{html.escape(title)}</h1>
<p>This page runs on your computer only and closes after one mailbox, or after 10 minutes.</p>
{body}</body></html>"""
