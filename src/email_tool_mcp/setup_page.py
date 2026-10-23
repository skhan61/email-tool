"""A one-time setup page on this computer: add a mailbox without a terminal.

Standard: Starlette (routes, forms, file upload through python-multipart) served by uvicorn,
all installed with the MCP SDK; Microsoft and Google sign in through the native-app loopback
redirect (RFC 8252 7.3), here the page's own address.
Placement: setup_page.py; tools/setup.py starts it for the `add_mailbox` tool.

The page runs the same steps as `email-tool-mcp add` (enrol.py): the login is checked over
IMAP and SMTP before anything is saved, a password goes only into the keyring, and policy's
FIPS rule applies. A password is typed only into this page and never passes through the
assistant.

Security: bound to 127.0.0.1 (and ::1 when this computer has it) on a random port. Every
page path carries a 256-bit token compared in constant time. The Host header must name this
loopback address, which stops DNS rebinding, and a form post must come from this page's own
origin. The page closes after one mailbox is added or when its time runs out. Nothing is
logged: uvicorn's access log is off, since the sign-in return address carries a one-time code.
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
from email_tool_mcp.settings import DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT

LIFETIME_SECONDS: Final[float] = 600.0
# How long the page waits for Microsoft or Google to hand over their sign-in address.
_SIGN_IN_START_SECONDS: Final[float] = 60.0
# How long the page waits for the login check after the browser comes back.
_FINISH_SECONDS: Final[float] = 120.0
_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
_SIGN_IN_ADDRESS: Final[re.Pattern[str]] = re.compile(r"https://\S+")
_KINDS: Final[tuple[str, ...]] = ("gmail", "microsoft", "google", "password")


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
    ) -> None:
        self._settings_file: Path = settings_file
        self._forget: Forget = forget
        self._microsoft: Callable[[], MicrosoftTokens] = microsoft
        self._google: Callable[[], GoogleTokens] = google
        self._login_check: LoginCheck = login_check
        self._lifetime: float = lifetime
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
        """Close the page; its address and token stop working."""
        with self._lock:
            if self._server is not None:
                self._server.should_exit = True
            if self._timer is not None:
                self._timer.cancel()
            self._server = None
            self._timer = None
            self._token = ""
            self._pending = None

    # Requests -------------------------------------------------------------------------------------

    def _app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/", self._returned, methods=["GET"]),
                Route("/s/{token}", self._choose, methods=["GET"]),
                Route("/s/{token}/add", self._add, methods=["POST"]),
            ]
        )

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
        return refused or HTMLResponse(_page("Add a mailbox", _form(self._token, "")))

    async def _add(self, request: Request) -> Response:
        refused: Response | None = self._refusal(request, posted=True)
        if refused is not None:
            return refused
        form: FormData = await request.form()
        kind: str = str(form.get("kind", ""))
        name: str = str(form.get("name", "")).strip()
        address: str = str(form.get("address", "")).strip()
        problem: str = _invalid(kind, name, address)
        if problem:
            return HTMLResponse(_page("Add a mailbox", _form(self._token, problem)), status_code=400)
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
                lambda prompt: "",
                lambda prompt: password,
                self._login_check,
                forget=self._forget,
            )
        except Exception as error:
            return HTMLResponse(_page("Add a mailbox", _form(self._token, _reason(error))), status_code=400)
        self._finish(done)
        return HTMLResponse(_page("Mailbox added", _done(done)))

    async def _start_sign_in(self, kind: str, name: str, address: str, upload: UploadFile | None) -> Response:
        client_folder: Path | None = None
        client_file: Path = Path()
        if kind == "google":
            if upload is None or not upload.filename:
                return HTMLResponse(
                    _page(
                        "Add a mailbox", _form(self._token, "Choose your Google client file (client_secret_….json).")
                    ),
                    status_code=400,
                )
            client_folder = Path(tempfile.mkdtemp(prefix="email-tool-"))
            client_file = client_folder / "client.json"
            client_file.write_bytes(await upload.read())
            client_file.chmod(0o600)
        # Microsoft's app registers `http://localhost` and Google's loopback `http://localhost/`.
        redirect: str = f"http://localhost:{self._port}" + ("/" if kind == "google" else "")
        pending: _SignIn = _SignIn(redirect)
        self._pending = pending

        def show(text: str) -> None:
            found: re.Match[str] | None = _SIGN_IN_ADDRESS.search(text)
            if found is not None and pending.address.empty():
                pending.address.put(found.group(0))

        def wait_for_browser(prompt: str) -> str:
            return pending.returned.get(timeout=self._lifetime)

        def sign_in() -> None:
            try:
                if kind == "microsoft":
                    done: str = add_microsoft_mailbox(
                        name,
                        self._settings_file,
                        self._microsoft(),
                        address,
                        "",
                        show=show,
                        login_check=self._login_check,
                        forget=self._forget,
                        paste=wait_for_browser,
                        redirect=redirect,
                    )
                else:
                    done = add_google_mailbox(
                        name,
                        self._settings_file,
                        self._google(),
                        address,
                        str(client_file),
                        show=show,
                        login_check=self._login_check,
                        forget=self._forget,
                        paste=wait_for_browser,
                        redirect=redirect,
                    )
                pending.outcome.put((True, done))
            except Exception as error:
                pending.outcome.put((False, _reason(error)))
            finally:
                if client_folder is not None:
                    shutil.rmtree(client_folder, ignore_errors=True)
                if pending.address.empty():
                    pending.address.put("")

        threading.Thread(target=sign_in, daemon=True).start()
        try:
            target: str = await run_in_threadpool(pending.address.get, True, _SIGN_IN_START_SECONDS)
        except queue.Empty:
            target = ""
        if not target:
            failed: str = (
                pending.outcome.get_nowait()[1] if not pending.outcome.empty() else "the sign-in did not start"
            )
            return HTMLResponse(_page("Add a mailbox", _form(self._token, failed)), status_code=400)
        return RedirectResponse(target, status_code=303)

    async def _returned(self, request: Request) -> Response:
        """Where Microsoft or Google send the browser back, with a one-time code or an error."""
        refused: Response | None = self._refusal(request, posted=False)
        if refused is not None:
            return refused
        pending: _SignIn | None = self._pending
        query: str = request.url.query
        if pending is None or not query:
            return Response("No sign-in is waiting here.", status_code=404)
        self._pending = None
        said: dict[str, list[str]] = parse_qs(query)
        if "code" not in said:
            explained: str = (said.get("error_description") or said.get("error") or ["the sign-in was cancelled"])[0]
            pending.returned.put("")
            return HTMLResponse(_page("Add a mailbox", _form(self._token, f"The sign-in did not finish: {explained}")))
        pending.returned.put(f"{pending.redirect}?{query}")
        try:
            succeeded: bool
            message: str
            succeeded, message = await run_in_threadpool(pending.outcome.get, True, _FINISH_SECONDS)
        except queue.Empty:
            return HTMLResponse(_page("Add a mailbox", _form(self._token, "The login check took too long.")), 504)
        if not succeeded:
            return HTMLResponse(_page("Add a mailbox", _form(self._token, message)), status_code=400)
        self._finish(message)
        return HTMLResponse(_page("Mailbox added", _done(message)))


def _loopback_sockets() -> list[socket.socket]:
    """A listening socket on 127.0.0.1 at a free port, plus ::1 on the same port when available.

    Both, because browsers may resolve `localhost` to either loopback address.
    """
    first: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    first.bind(("127.0.0.1", 0))
    first.listen()
    sockets: list[socket.socket] = [first]
    if socket.has_ipv6:
        second: socket.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            second.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            second.bind(("::1", int(first.getsockname()[1])))
            second.listen()
            sockets.append(second)
        except OSError:
            second.close()
    return sockets


def _invalid(kind: str, name: str, address: str) -> str:
    """Why the form cannot be used as sent; "" when it can."""
    if kind not in _KINDS:
        return "Choose what kind of mailbox it is."
    if not _NAME.match(name):
        return "Give the mailbox a short name: letters, numbers, - or _, such as work or personal."
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
  <label>A short name for it
    <input name="name" value="work" pattern="[A-Za-z0-9][A-Za-z0-9_-]{{0,39}}" required></label>
  <details>
    <summary>Gmail or any other mailbox: password</summary>
    <p>Gmail needs an
    <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">App Password</a>,
    not your Google password. It goes only into this computer's keyring.</p>
    <label>Password <input name="password" type="password" autocomplete="off"></label>
    <p>Any other mailbox: your provider's server names, for example mail.example.com.</p>
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
  <p>Outlook, Microsoft 365 and Google Workspace open their own sign-in page next.</p>
  <button type="submit">Add mailbox</button>
</form>"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>email-tool: {html.escape(title)}</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; color: #1b1b1b; }}
h1 {{ font-size: 1.5rem; }} label {{ display: block; margin: .6rem 0; }}
input[type=email], input[name=name], input[type=password], input[name$=_host] {{
  display: block; width: 100%; padding: .4rem; }}
fieldset {{ border: 1px solid #ccc; padding: .5rem 1rem; }} details {{ margin: 1rem 0; }}
button {{ font-size: 1rem; padding: .5rem 1.2rem; }} .problem {{ color: #a40000; font-weight: 600; }}
.ok {{ color: #0a6b2d; font-weight: 600; }}
</style></head>
<body><h1>{html.escape(title)}</h1>
<p>This page runs on your computer only and closes after one mailbox, or after 10 minutes.</p>
{body}</body></html>"""
