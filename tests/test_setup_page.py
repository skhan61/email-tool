"""The setup page, run for real on a loopback port and driven over HTTP as a browser would.

Standard: the real uvicorn server from SetupPage.start(), reached with http.client; the
Microsoft sign-in through the module's own FakeMsal (tests/test_microsoft.py).
Placement: tests/test_setup_page.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import http.client
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest
from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp_types import CallToolResult, ElicitRequestParams, ElicitResult, TextContent

from email_tool_mcp import setup_page as setup_page_module
from email_tool_mcp.audit import AuditLog
from email_tool_mcp.credentials import Credential
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.microsoft import DEFAULT_CLIENT_ID, MicrosoftTokens
from email_tool_mcp.passwords import read_password
from email_tool_mcp.server import build_server
from email_tool_mcp.settings import Mailbox, load_mailboxes
from email_tool_mcp.setup_page import SetupPage
from email_tool_mcp.token_store import TokenStore
from tests.test_google import ADDRESS as SCHOOL_ADDRESS
from tests.test_google import FakeFlow, tokens_with
from tests.test_microsoft import ADDRESS, FakeMsal

APP_PASSWORD: str = "abcd efgh ijkl mnop"


class Checks:
    """Stands in for the IMAP and SMTP login check and remembers what it was given."""

    def __init__(self) -> None:
        self.seen: list[tuple[Mailbox, Credential]] = []
        self.refuse: bool = False

    def __call__(self, mailbox: Mailbox, credential: Credential) -> None:
        self.seen.append((mailbox, credential))
        if self.refuse:
            raise RuntimeError("the server refused the login")


@pytest.fixture
def checks() -> Checks:
    return Checks()


@pytest.fixture
def page(tmp_path: Path, checks: Checks, audit: AuditLog) -> Iterator[SetupPage]:
    FakeMsal.instances = []
    microsoft: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), FakeMsal)
    opened: SetupPage = SetupPage(
        tmp_path / "mailboxes.toml",
        lambda mailbox: True,
        lambda: microsoft,
        lambda: pytest.fail(),
        audit=audit,
        login_check=checks,
    )
    yield opened
    opened.stop()


def request(
    page: SetupPage, method: str, path: str, form: dict[str, str] | None = None, host: str = "", origin: str = "same"
) -> http.client.HTTPResponse:
    """One request to the running page; `origin="same"` sends the page's own origin, "" sends none."""
    port: int = int(urlsplit(page.url).port or 0)
    connection: http.client.HTTPConnection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers: dict[str, str] = {"Host": host or f"127.0.0.1:{port}"}
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{port}" if origin == "same" else origin
    body: str | None = None
    if form is not None:
        body = urlencode(form)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    connection.request(method, path, body=body, headers=headers)
    return connection.getresponse()


def add_path(page: SetupPage) -> str:
    return urlsplit(page.url).path + "/add"


GMAIL: dict[str, str] = {"kind": "gmail", "name": "personal", "address": "me@gmail.com", "password": APP_PASSWORD}


def test_a_gmail_mailbox_is_added_from_the_page_and_the_page_closes(
    page: SetupPage, checks: Checks, tmp_path: Path
) -> None:
    page.start()
    answered: http.client.HTTPResponse = request(page, "POST", add_path(page), GMAIL)
    assert answered.status == 200, answered.read()
    assert "Mailbox &#x27;personal&#x27; (me@gmail.com) added" in answered.read().decode()
    saved: Mailbox = load_mailboxes(tmp_path / "mailboxes.toml")["personal"]
    assert (saved.imap_host, saved.smtp_host) == ("imap.gmail.com", "smtp.gmail.com")
    assert read_password("personal") == "abcdefghijklmnop"
    assert checks.seen[0][1].secret == "abcdefghijklmnop"
    assert page.url == ""


def test_a_refused_login_saves_nothing_and_the_page_stays_open(page: SetupPage, checks: Checks, tmp_path: Path) -> None:
    checks.refuse = True
    page.start()
    answered: http.client.HTTPResponse = request(page, "POST", add_path(page), GMAIL)
    assert answered.status == 400
    shown: str = answered.read().decode()
    assert "the server refused the login" in shown
    assert APP_PASSWORD not in shown
    assert not (tmp_path / "mailboxes.toml").exists()
    assert page.url != ""


@pytest.mark.parametrize(
    ("host", "origin", "token", "status"),
    [
        ("", "same", "wrong-token", 404),
        ("attacker.example:80", "same", "", 403),
        ("", "", "", 403),
        ("", "http://attacker.example", "", 403),
    ],
)
def test_a_request_from_anywhere_but_this_page_is_refused(
    page: SetupPage, tmp_path: Path, host: str, origin: str, token: str, status: int
) -> None:
    page.start()
    path: str = f"/s/{token}/add" if token else add_path(page)
    answered: http.client.HTTPResponse = request(page, "POST", path, GMAIL, host=host, origin=origin)
    assert answered.status == status
    assert not (tmp_path / "mailboxes.toml").exists()


def test_the_page_closes_when_its_time_runs_out(tmp_path: Path, checks: Checks, audit: AuditLog) -> None:
    short: SetupPage = SetupPage(
        tmp_path / "mailboxes.toml",
        lambda mailbox: True,
        lambda: pytest.fail(),
        lambda: pytest.fail(),
        audit=audit,
        login_check=checks,
        lifetime=0.3,
    )
    port: int = int(urlsplit(short.start()).port or 0)
    time.sleep(1.0)
    assert short.url == ""
    connection: http.client.HTTPConnection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    with pytest.raises(OSError):
        connection.request("GET", "/")
        connection.getresponse()


def test_a_microsoft_sign_in_returns_to_the_page_and_finishes_there(
    page: SetupPage, checks: Checks, tmp_path: Path
) -> None:
    page.start()
    port: int = int(urlsplit(page.url).port or 0)
    form: dict[str, str] = {"kind": "microsoft", "name": "outlook", "address": ADDRESS}
    started: http.client.HTTPResponse = request(page, "POST", add_path(page), form)
    assert started.status == 303
    assert started.headers["Location"].startswith("https://login.microsoftonline.com/")
    assert FakeMsal.instances[-1].code_flow_options["redirect_uri"] == f"http://localhost:{port}"
    back: http.client.HTTPResponse = request(page, "GET", "/?code=one-time&state=s", host=f"localhost:{port}")
    assert back.status == 200, back.read()
    assert "added. Signed in with Microsoft" in back.read().decode()
    assert FakeMsal.instances[-1].auth_response == {"code": "one-time", "state": "s"}
    assert load_mailboxes(tmp_path / "mailboxes.toml")["outlook"].auth == "microsoft"
    assert checks.seen[0][1].is_token


def test_a_university_directory_and_app_from_it_reach_microsoft_and_are_kept(page: SetupPage, tmp_path: Path) -> None:
    """Without a terminal: the directory (tenant) and the organization's own app ID IT gave the user."""
    page.start()
    port: int = int(urlsplit(page.url).port or 0)
    app: str = "12345678-abcd-1234-abcd-1234567890ab"
    form: dict[str, str] = {
        "kind": "microsoft",
        "name": "uni",
        "address": ADDRESS,
        "tenant": "school.edu",
        "client_id": app,
    }
    started: http.client.HTTPResponse = request(page, "POST", add_path(page), form)
    assert started.status == 303
    assert FakeMsal.instances[-1].client_id == app
    assert FakeMsal.instances[-1].authority == "https://login.microsoftonline.com/school.edu"
    back: http.client.HTTPResponse = request(page, "GET", "/?code=one-time&state=s", host=f"localhost:{port}")
    assert back.status == 200, back.read()
    kept: Mailbox = load_mailboxes(tmp_path / "mailboxes.toml")["uni"]
    assert (kept.tenant, kept.client_id) == ("school.edu", app)


@pytest.mark.parametrize(
    ("tenant", "pasted_app", "app", "authority"),
    [
        ("11111111-2222-3333-4444-555555555555", "", "", "11111111-2222-3333-4444-555555555555"),
        (
            "organizations",
            "{12345678-abcd-1234-abcd-1234567890ab}",
            "12345678-abcd-1234-abcd-1234567890ab",
            "organizations",
        ),
    ],
    ids=["directory ID alone", "Microsoft's own name and an app ID pasted in braces"],
)
def test_either_value_alone_and_as_pasted_reaches_microsoft(
    page: SetupPage, tenant: str, pasted_app: str, app: str, authority: str
) -> None:
    page.start()
    form: dict[str, str] = {
        "kind": "microsoft",
        "name": "uni",
        "address": ADDRESS,
        "tenant": tenant,
        "client_id": pasted_app,
    }
    assert request(page, "POST", add_path(page), form).status == 303
    assert FakeMsal.instances[-1].client_id == (app or DEFAULT_CLIENT_ID)
    assert FakeMsal.instances[-1].authority == f"https://login.microsoftonline.com/{authority}"


def test_a_cancelled_sign_in_saves_nothing(page: SetupPage, tmp_path: Path) -> None:
    page.start()
    port: int = int(urlsplit(page.url).port or 0)
    request(page, "POST", add_path(page), {"kind": "microsoft", "name": "outlook", "address": ADDRESS})
    back: http.client.HTTPResponse = request(
        page, "GET", "/?error=access_denied&error_description=The+user+declined", host=f"localhost:{port}"
    )
    assert "The sign-in did not finish: The user declined" in back.read().decode()
    assert not (tmp_path / "mailboxes.toml").exists()


@pytest.mark.parametrize(
    ("form", "said"),
    [
        ({"kind": "fax", "name": "w", "address": "a@b.c"}, "Choose what kind"),
        ({"kind": "gmail", "name": "../etc", "address": "a@gmail.com"}, "only letters, numbers"),
        ({"kind": "gmail", "name": "w", "address": "no-at-sign"}, "full email address"),
        ({"kind": "google", "name": "w", "address": "a@school.edu"}, "client file"),
        ({"kind": "microsoft", "name": "w", "address": "a@school.edu", "client_id": "not-an-id"}, "App (client) ID"),
        ({"kind": "microsoft", "name": "w", "address": "a@school.edu", "tenant": "x/../evil"}, "Directory (tenant) ID"),
    ],
)
def test_an_incomplete_form_is_explained_and_saves_nothing(
    page: SetupPage, tmp_path: Path, form: dict[str, str], said: str
) -> None:
    page.start()
    answered: http.client.HTTPResponse = request(page, "POST", add_path(page), form)
    assert answered.status == 400
    assert said in answered.read().decode()
    assert not (tmp_path / "mailboxes.toml").exists()


async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    """An app that can open web pages: having an elicitation callback declares URL-mode support."""
    return ElicitResult(action="accept")


def text_of(result: CallToolResult) -> str:
    assert not result.is_error
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.mark.anyio
async def test_without_page_support_the_assistant_gets_the_link(
    book: MailboxBook, audit: AuditLog, page: SetupPage
) -> None:
    async with Client(build_server(book, audit, page)) as client:
        said: str = text_of(await client.call_tool("add_mailbox", {}))
    assert page.url and page.url in said
    assert "Never ask for a password" in said
    assert '"tool": "add_mailbox"' in audit.path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_an_app_that_opens_pages_gets_the_page_and_the_token_never_reaches_the_assistant(
    book: MailboxBook, audit: AuditLog, page: SetupPage
) -> None:
    async with Client(build_server(book, audit, page), elicitation_callback=answer) as client:
        with pytest.raises(UrlElicitationRequiredError) as raised:
            await client.call_tool("add_mailbox", {})
        assert [opened.url for opened in raised.value.elicitations] == [page.url]
        assert request(page, "POST", add_path(page), GMAIL).status == 200
        reported: str = text_of(await client.call_tool("add_mailbox", {}))
        assert "Mailbox 'personal' (me@gmail.com) added" in reported
        with pytest.raises(UrlElicitationRequiredError):
            await client.call_tool("add_mailbox", {})


def test_names_reuse_the_addresss_mailbox_and_never_take_another_addresss(page: SetupPage, tmp_path: Path) -> None:
    unnamed: dict[str, str] = {key: value for key, value in GMAIL.items() if key != "name"}
    page.start()
    assert request(page, "POST", add_path(page), unnamed).status == 200
    assert set(load_mailboxes(tmp_path / "mailboxes.toml")) == {"gmail"}
    page.start()
    renewed: dict[str, str] = {**unnamed, "password": "qrst uvwx yzab cdef"}
    assert request(page, "POST", add_path(page), renewed).status == 200, "the same address signs in again"
    assert set(load_mailboxes(tmp_path / "mailboxes.toml")) == {"gmail"}
    assert read_password("gmail") == "qrstuvwxyzabcdef"
    page.start()
    other: dict[str, str] = {**unnamed, "address": "someone.else@gmail.com"}
    refused: http.client.HTTPResponse = request(page, "POST", add_path(page), {**other, "name": "gmail"})
    assert refused.status == 400
    assert "You already have a mailbox called gmail, for me@gmail.com" in refused.read().decode()
    assert request(page, "POST", add_path(page), other).status == 200
    assert set(load_mailboxes(tmp_path / "mailboxes.toml")) == {"gmail", "gmail2"}


@pytest.fixture
def audited(tmp_path: Path, checks: Checks, audit: AuditLog) -> Iterator[SetupPage]:
    FakeMsal.instances = []
    microsoft: MicrosoftTokens = MicrosoftTokens(TokenStore(tmp_path / "sign-ins"), FakeMsal)
    opened: SetupPage = SetupPage(
        tmp_path / "mailboxes.toml",
        lambda mailbox: True,
        lambda: microsoft,
        lambda: tokens_with(tmp_path, FakeFlow(SCHOOL_ADDRESS)),
        audit=audit,
        login_check=checks,
    )
    yield opened
    opened.stop()


def test_pages_keep_the_origin_and_never_leak_the_token_as_a_referer(page: SetupPage) -> None:
    page.start()
    shown: http.client.HTTPResponse = request(page, "GET", urlsplit(page.url).path)
    assert shown.headers["Referrer-Policy"] == "same-origin"
    assert "no-referrer" not in shown.read().decode()


def test_a_second_sign_in_while_one_waits_is_refused(page: SetupPage) -> None:
    page.start()
    form: dict[str, str] = {"kind": "microsoft", "name": "outlook", "address": ADDRESS}
    assert request(page, "POST", add_path(page), form).status == 303
    second: http.client.HTTPResponse = request(page, "POST", add_path(page), form)
    assert second.status == 409
    assert "already open in another tab" in second.read().decode()


def post_file(page: SetupPage, fields: dict[str, str], name: str, content: bytes) -> http.client.HTTPResponse:
    """A multipart form post with one file, as the browser sends the Google client file."""
    port: int = int(urlsplit(page.url).port or 0)
    boundary: str = "----setup-page-test"
    parts: list[bytes] = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="client_file"; filename="{name}"\r\n'
        "Content-Type: application/json\r\n\r\n".encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    connection: http.client.HTTPConnection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(
        "POST",
        add_path(page),
        body=b"".join(parts),
        headers={
            "Host": f"127.0.0.1:{port}",
            "Origin": f"http://127.0.0.1:{port}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    return connection.getresponse()


def test_the_google_client_file_is_gone_once_google_has_the_sign_in(
    audited: SetupPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads: Path = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(uploads))
    audited.start()
    fields: dict[str, str] = {"kind": "google", "name": "school", "address": SCHOOL_ADDRESS}
    started: http.client.HTTPResponse = post_file(audited, fields, "client_secret_1.json", b'{"installed": {}}')
    assert started.status == 303
    assert started.headers["Location"].startswith("https://accounts.google.com/")
    assert list(uploads.iterdir()) == []


def test_closing_the_page_ends_a_waiting_sign_in(audited: SetupPage, audit: AuditLog) -> None:
    audited.start()
    form: dict[str, str] = {"kind": "microsoft", "name": "outlook", "address": ADDRESS}
    assert request(audited, "POST", add_path(audited), form).status == 303
    audited.stop()
    deadline: float = time.monotonic() + 5
    while '"phase": "finished"' not in audit.path.read_text(encoding="utf-8") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert '"phase": "finished"' in audit.path.read_text(encoding="utf-8")
    assert all(thread.name != "sign_in" for thread in threading.enumerate())


def test_each_mailbox_added_on_the_page_is_audited_without_its_password(audited: SetupPage, audit: AuditLog) -> None:
    audited.start()
    assert request(audited, "POST", add_path(audited), GMAIL).status == 200
    logged: str = audit.path.read_text(encoding="utf-8")
    assert '"kind": "gmail"' in logged and '"address": "me@gmail.com"' in logged and '"outcome": "ok"' in logged
    assert APP_PASSWORD not in logged and APP_PASSWORD.replace(" ", "") not in logged


@pytest.mark.anyio
async def test_the_servers_own_setup_page_audits_each_add_and_listing_clears_the_report(
    book: MailboxBook, audit: AuditLog, checks: Checks, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found live (#87): the server built its page without the audit log, so page adds went unrecorded."""
    monkeypatch.setattr(setup_page_module, "check_login", checks)
    async with Client(build_server(book, audit)) as client:
        said: str = text_of(await client.call_tool("add_mailbox", {}))
        link: str = said.split(": ", 1)[1].split()[0]
        port: int = int(urlsplit(link).port or 0)
        connection: http.client.HTTPConnection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            urlsplit(link).path + "/add",
            body=urlencode(GMAIL),
            headers={
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert connection.getresponse().status == 200
        logged: str = audit.path.read_text(encoding="utf-8")
        assert '"kind": "gmail"' in logged and '"address": "me@gmail.com"' in logged
        await client.call_tool("list_mailboxes", {})
        again: str = text_of(await client.call_tool("add_mailbox", {}))
    assert again.startswith("Show the user this link"), "after list_mailboxes, no stale 'Mailbox added' report"
