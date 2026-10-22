"""TLS floor, FIPS enforcement and the `check` report.

Standard: pytest; FIPS state is patched, the connection report uses the offline fakes.
Placement: tests/test_tls.py, beside the modules it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from email_tool_mcp import policy as policy_module
from email_tool_mcp.audit import AuditLog
from email_tool_mcp.credentials import Credential
from email_tool_mcp.diagnose import check_mailbox
from email_tool_mcp.enrol import add_mailbox
from email_tool_mcp.imap_session import ImapSession
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy, PolicyRefusal
from email_tool_mcp.tls import client_context, describe_context, fips_enabled
from tests.conftest import WORK
from tests.fakes import FakeMailServer

TOOLS: frozenset[str] = frozenset({"list_emails"})


def test_the_floor_is_tls_1_2_and_verification_is_on() -> None:
    context: ssl.SSLContext = client_context()
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


@pytest.mark.parametrize(("fips", "refused"), [(False, True), (True, False)])
def test_require_fips_refuses_without_fips_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fips: bool, refused: bool
) -> None:
    monkeypatch.setattr(policy_module, "fips_enabled", lambda: fips)
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text("[default]\nrequire_fips = true\n", encoding="utf-8")
    rules: Policy = Policy([policy_file])
    if refused:
        with pytest.raises(PolicyRefusal, match="FIPS"):
            rules.check_call("work", "me@example.com", "list_emails", False, TOOLS)
    else:
        rules.check_call("work", "me@example.com", "list_emails", False, TOOLS)


def test_check_reports_both_connections_and_fips(book: MailboxBook, audit: AuditLog) -> None:
    store_password("work", "pw")
    report: str = check_mailbox(book, audit, "work")
    assert "IMAP imap.example.com:993  TLSv1.3" in report
    assert "SMTP smtp.example.com:465  TLSv1.3" in report
    assert "minimum accepted: TLS 1.2   certificate verification: on" in report
    assert "FIPS mode: " in report
    assert '"tool": "check"' in audit.path.read_text(encoding="utf-8")


def test_a_refused_login_is_reported_not_raised(book: MailboxBook, audit: AuditLog) -> None:
    report: str = check_mailbox(book, audit, "work")
    assert "IMAP imap.example.com:993  REFUSED: MissingPassword" in report


@pytest.mark.parametrize("fips", [False, True])
def test_require_fips_also_guards_add_and_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_file: Path,
    mail_server: FakeMailServer,
    audit: AuditLog,
    fips: bool,
) -> None:
    monkeypatch.setattr(policy_module, "fips_enabled", lambda: fips)
    store_password("work", "pw")
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text("[default]\nrequire_fips = true\n", encoding="utf-8")
    rules: Policy = Policy([policy_file])
    book: MailboxBook = MailboxBook(settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=rules)
    report: str = check_mailbox(book, audit, "work")
    assert ("REFUSED: PolicyRefusal" in report) is not fips
    if not fips:
        with pytest.raises(PolicyRefusal, match="FIPS"):
            add_mailbox(
                "new",
                tmp_path / "m.toml",
                address="a@x.com",
                imap_host="i",
                smtp_host="s",
                ask_secret=lambda _: "pw",
                login_check=lambda mailbox, password: None,
                policy=rules,
            )


class StubSocket:
    def __init__(self, cipher: tuple[str, str, int] | None) -> None:
        self._cipher: tuple[str, str, int] | None = cipher

    def version(self) -> str | None:
        return "TLSv1.3"

    def cipher(self) -> tuple[str, str, int] | None:
        return self._cipher


class StubClient:
    def __init__(self, sock: StubSocket) -> None:
        self._sock: StubSocket = sock

    def socket(self) -> StubSocket:
        return self._sock


@pytest.mark.parametrize(
    ("cipher", "shown"),
    [(("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256), "TLSv1.3 TLS_AES_256_GCM_SHA384"), (None, "TLSv1.3 ?")],
)
def test_the_real_imap_session_reports_its_socket(cipher: tuple[str, str, int] | None, shown: str) -> None:
    session: ImapSession = ImapSession(WORK, Credential(WORK.address, "pw", is_token=False))
    session._client = StubClient(StubSocket(cipher))
    assert session.tls_details() == shown


def test_describe_context_reads_the_real_settings() -> None:
    weak: ssl.SSLContext = ssl.create_default_context()
    weak.check_hostname = False
    weak.verify_mode = ssl.CERT_NONE
    weak.minimum_version = ssl.TLSVersion.TLSv1_3
    assert describe_context(weak) == "minimum accepted: TLS 1.3   certificate verification: OFF"


@pytest.mark.parametrize(
    ("module", "expected"), [(SimpleNamespace(get_fips_mode=lambda: 1), True), (SimpleNamespace(), False)]
)
def test_fips_enabled_reads_openssl_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, module: object, expected: bool
) -> None:
    monkeypatch.setitem(sys.modules, "_hashlib", module)
    assert fips_enabled() is expected
