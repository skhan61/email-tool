"""What an agent may do in each mailbox (NIST SP 800-171 3.1.1, 3.1.2, 3.1.5).

Standard: two TOML policy files, the usual admin/user layering: the machine-wide
one in the system config folder (platformdirs `site_config_path`, e.g.
/etc/xdg/email-tool on Linux, writable only by an administrator) and the user's
own in the user config folder. The most restrictive combination applies, so a
user can tighten the administrator's policy but never loosen it.
Placement: policy.py in the src layout; server.py checks every call against it.

    [default]                      # every mailbox
    read_only = false
    allowed_recipient_domains = ["example.com"]

    [mailboxes.work]               # one mailbox, combined with [default]
    allowed_tools = ["list_emails", "get_email", "create_draft"]
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Final

from platformdirs import site_config_path, user_config_path
from pydantic import ConfigDict, ValidationError
from pydantic.dataclasses import dataclass

from email_tool_mcp.settings import APP_NAME, SettingsError

POLICY_FILE: Final[str] = "policy.toml"
# Tools that change a mailbox or send mail; `read_only` refuses these.
WRITING_TOOLS: Final[frozenset[str]] = frozenset({"send_email", "create_draft", "update_draft", "delete_email"})
# Tools whose `to`/`cc` the recipient allow-list governs. A draft can be sent from any mail client.
ADDRESSING_TOOLS: Final[frozenset[str]] = frozenset({"send_email", "create_draft", "update_draft"})


class PolicyRefusal(PermissionError):
    """Raised when policy forbids a call; the message names the rule."""


@dataclass(frozen=True, config=ConfigDict(extra="forbid", strict=True))
class Rules:
    """One policy table. None means "no limit from this table"."""

    read_only: bool = False
    allowed_tools: list[str] | None = None
    allowed_recipient_domains: list[str] | None = None


def narrower(first: list[str] | None, second: list[str] | None) -> list[str] | None:
    """The overlap of two allow-lists; None stands for "anything"."""
    if first is None:
        return second
    if second is None:
        return first
    return [item for item in first if item in second]


def combine(rules: Iterable[Rules]) -> Rules:
    """The most restrictive combination of `rules`."""
    combined: Rules = Rules()
    for rule in rules:
        combined = Rules(
            read_only=combined.read_only or rule.read_only,
            allowed_tools=narrower(combined.allowed_tools, rule.allowed_tools),
            allowed_recipient_domains=narrower(
                combined.allowed_recipient_domains,
                [domain.lower() for domain in rule.allowed_recipient_domains]
                if rule.allowed_recipient_domains is not None
                else None,
            ),
        )
    return combined


def policy_paths() -> tuple[Path, Path]:
    """The administrator's and the user's policy file locations on this OS."""
    return (
        site_config_path(APP_NAME, appauthor=False) / POLICY_FILE,
        user_config_path(APP_NAME, appauthor=False) / POLICY_FILE,
    )


def read_tables(path: Path) -> tuple[Rules, dict[str, Rules]]:
    """Return the [default] rules and the per-mailbox rules in `path`."""
    if not path.is_file():
        return Rules(), {}
    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        unknown: set[str] = set(document) - {"default", "mailboxes"}
        if unknown:
            raise SettingsError(f"{path}: unknown section(s) {sorted(unknown)}")
        default: Rules = Rules(**document.get("default", {}))
        mailboxes: dict[str, Rules] = {name: Rules(**table) for name, table in document.get("mailboxes", {}).items()}
    except (tomllib.TOMLDecodeError, ValidationError, TypeError) as error:
        raise SettingsError(f"{path} is malformed: {error}") from error
    return default, mailboxes


class Policy:
    """The combined administrator and user policy, read fresh for every check."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths: tuple[Path, ...] = tuple(paths)

    def rules_for(self, mailbox: str) -> Rules:
        """The effective rules for `mailbox`."""
        layers: list[Rules] = []
        for path in self._paths:
            default, mailboxes = read_tables(path)
            layers.append(default)
            if mailbox in mailboxes:
                layers.append(mailboxes[mailbox])
        return combine(layers)

    def check(self, mailbox: str, tool: str, arguments: Mapping[str, Any]) -> None:
        """Raise PolicyRefusal when `tool` with `arguments` is not allowed on `mailbox`."""
        rules: Rules = self.rules_for(mailbox)
        if rules.allowed_tools is not None and tool not in rules.allowed_tools and tool != "list_mailboxes":
            raise PolicyRefusal(f"policy: {tool} is not in allowed_tools for mailbox {mailbox!r}")
        if rules.read_only and tool in WRITING_TOOLS:
            raise PolicyRefusal(f"policy: mailbox {mailbox!r} is read_only, so {tool} is refused")
        if rules.allowed_recipient_domains is not None and tool in ADDRESSING_TOOLS:
            fields: list[str] = [str(arguments.get(key, "")) for key in ("to", "cc")]
            outside: list[str] = sorted(
                address
                for _, address in getaddresses(fields)
                if address and address.rpartition("@")[2].lower() not in rules.allowed_recipient_domains
            )
            if outside:
                raise PolicyRefusal(
                    f"policy: {', '.join(outside)} outside allowed_recipient_domains for mailbox {mailbox!r}"
                )
