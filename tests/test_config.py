"""`parse_config` takes hosts from arguments and credentials from the environment."""

import pytest
from config import MailboxConfig, MailboxNotConfigured, parse_config

ARGV: list[str] = [
    "--label",
    "work",
    "--imap-host",
    "imap.example.com",
    "--imap-port",
    "993",
    "--smtp-host",
    "smtp.example.com",
    "--smtp-port",
    "465",
]


def test_credentials_come_from_the_environment() -> None:
    config: MailboxConfig = parse_config(ARGV, {"MAILBOX_USER": "you@example.com", "MAILBOX_PASSWORD": "abcd efgh"})
    assert config.imap_user == "you@example.com"
    assert config.password == "abcdefgh"
    assert (config.imap_host, config.imap_port) == ("imap.example.com", 993)


@pytest.mark.parametrize(
    "environment",
    [{}, {"MAILBOX_USER": "you@example.com"}, {"MAILBOX_USER": "you@example.com", "MAILBOX_PASSWORD": "  "}],
)
def test_a_missing_credential_means_not_configured(environment: dict[str, str]) -> None:
    with pytest.raises(MailboxNotConfigured):
        parse_config(ARGV, environment)
