"""Mailbox settings round-trip through TOML; one mailbox can come from the environment.

Standard: pytest with tmp_path; no real config folder is touched.
Placement: tests/test_settings.py, beside the module it tests (pytest's tests/ layout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from email_tool_mcp.settings import Mailbox, SettingsError, environment_mailbox, load_mailboxes, save_mailboxes
from tests.conftest import HOME, WORK


def test_settings_round_trip(tmp_path: Path) -> None:
    path: Path = tmp_path / "nested" / "mailboxes.toml"
    save_mailboxes(path, {"work": WORK, "home": HOME})
    assert load_mailboxes(path) == {"work": WORK, "home": HOME}


def test_settings_file_holds_no_password(settings_file: Path) -> None:
    assert "password" not in settings_file.read_text(encoding="utf-8").lower()


def test_missing_file_means_no_mailboxes(tmp_path: Path) -> None:
    assert load_mailboxes(tmp_path / "absent.toml") == {}


def test_environment_mailbox_uses_default_ports() -> None:
    found: Mailbox | None = environment_mailbox(
        {"EMAIL_TOOL_ADDRESS": "me@example.com", "EMAIL_TOOL_IMAP_HOST": "imap.x", "EMAIL_TOOL_SMTP_HOST": "smtp.x"}
    )
    assert found == Mailbox("default", "me@example.com", "imap.x", 993, "smtp.x", 465)


def test_environment_mailbox_absent_without_address() -> None:
    assert environment_mailbox({"EMAIL_TOOL_IMAP_HOST": "imap.x"}) is None


def test_environment_mailbox_needs_both_hosts() -> None:
    with pytest.raises(SettingsError, match="EMAIL_TOOL_SMTP_HOST"):
        environment_mailbox({"EMAIL_TOOL_ADDRESS": "me@example.com", "EMAIL_TOOL_IMAP_HOST": "imap.x"})


@pytest.mark.parametrize(
    "table",
    [
        'address = "a@x.com"\nimap_host = "i"\nimap_port = 993\nsmtp_host = "s"',
        'address = "a@x.com"\nimap_host = "i"\nimap_port = "993"\nsmtp_host = "s"\nsmtp_port = 465',
        'address = "a@x.com"\nimap_host = "i"\nimap_port = 993\nsmtp_host = "s"\nsmtp_port = 465\nstarttls = true',
    ],
    ids=["missing key", "port as text", "unknown key"],
)
def test_malformed_settings_name_the_file(tmp_path: Path, table: str) -> None:
    path: Path = tmp_path / "mailboxes.toml"
    path.write_text(f"[mailboxes.work]\n{table}\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="mailboxes.toml is malformed"):
        load_mailboxes(path)
