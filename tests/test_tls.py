"""TLS floor, FIPS enforcement and the `check` report.

Standard: pytest; FIPS state is patched, the connection report uses the offline fakes.
Placement: tests/test_tls.py, beside the modules it tests (pytest's tests/ layout).
"""

from __future__ import annotations

import ssl
from pathlib import Path

import pytest

from email_tool_mcp import policy as policy_module
from email_tool_mcp.diagnose import check_mailbox
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy, PolicyRefusal
from email_tool_mcp.tls import client_context, fips_enabled

TOOLS: frozenset[str] = frozenset({"list_emails"})


def test_the_floor_is_tls_1_2_and_verification_is_on() -> None:
    context: ssl.SSLContext = client_context()
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_fips_state_is_a_plain_bool() -> None:
    assert isinstance(fips_enabled(), bool)


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
            rules.check_call("work", "list_emails", False, TOOLS)
    else:
        rules.check_call("work", "list_emails", False, TOOLS)


def test_check_reports_both_connections_and_fips(book: MailboxBook) -> None:
    store_password("work", "pw")
    report: str = check_mailbox(book, "work")
    assert "IMAP imap.example.com:993  TLSv1.3" in report
    assert "SMTP smtp.example.com:465  TLSv1.3" in report
    assert "FIPS mode: " in report
