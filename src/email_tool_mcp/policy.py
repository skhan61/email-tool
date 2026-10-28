"""What an agent may do in each mailbox (NIST SP 800-171 3.1.1, 3.1.2, 3.1.5).

Standard: two TOML policy files in the usual admin/user layering: a machine-wide
file only administrators can write, and the user's own in the user config folder
(platformdirs). The most restrictive combination applies, so a user can tighten
the administrator's policy but never loosen it.
Placement: policy.py in the src layout. The server checks each call (`check_call`);
MailboxBook.approve checks every message it sends or saves as a draft
(`check_message`): its recipients, using the same parsed list SMTP receives, and
for CUI-marked mail the CUI recipient domains (3.1.3).

    [default]                      # every mailbox
    read_only = false
    require_fips = true            # refuse every call unless OpenSSL runs in FIPS mode
    allowed_recipient_domains = ["example.com"]

    require_approval = true        # send/delete/replace-draft ask the human first

    allow_environment_mailbox = false   # ignore mailboxes set in an app's environment

    [mailboxes."you@example.com"]  # by address (binding) or by name; combined with [default]
    allowed_tools = ["list_emails", "get_email", "create_draft"]
    cui_recipient_domains = ["example.com"]   # CUI-marked mail only to these

Limit: this stops the agent and accidental loosening. A user who controls their
own machine can run different code; enforce the install itself (managed
deployment) where that matters.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

from platformdirs import site_config_path, user_config_path
from pydantic import ConfigDict, ValidationError
from pydantic.dataclasses import dataclass

from email_tool_mcp.settings import APP_NAME, SettingsError
from email_tool_mcp.tls import fips_enabled, sign_in_storage_fips_enabled

POLICY_FILE: Final[str] = "policy.toml"
# THE ADMINISTRATOR'S FOLDER IS FIXED ON EVERY OS (#122): whoever launches the server must not
# choose the administrator's file. platformdirs' folders follow $XDG_CONFIG_DIRS (Linux, macOS,
# the BSDs), $WIN_PD_OVERRIDE_COMMON_APPDATA (Windows) and, on macOS, a Homebrew Python to a folder
# its user can write (an opt-linked one already in 4.12, a Cellar one too from 4.13).
LINUX_ADMIN_DIRECTORY: Final[Path] = Path("/etc") / APP_NAME
"""Linux and every other POSIX system but macOS."""
MACOS_ADMIN_DIRECTORY: Final[Path] = Path("/Library/Application Support") / APP_NAME
WINDOWS_ADMIN_DIRECTORY: Final[Path] = Path("C:/ProgramData") / APP_NAME


class PolicyRefusal(PermissionError):
    """Raised when policy forbids a call; the message names the rule."""


@dataclass(frozen=True, config=ConfigDict(extra="forbid", strict=True))
class Rules:
    """One policy table. None means "no limit from this table"."""

    read_only: bool = False
    allow_environment_mailbox: bool = True
    require_approval: bool = False
    require_fips: bool = False
    allowed_tools: list[str] | None = None
    allowed_recipient_domains: list[str] | None = None
    cui_recipient_domains: list[str] | None = None


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
        domains: list[str] | None = (
            [domain.lower() for domain in rule.allowed_recipient_domains]
            if rule.allowed_recipient_domains is not None
            else None
        )
        cui_domains: list[str] | None = (
            [domain.lower() for domain in rule.cui_recipient_domains]
            if rule.cui_recipient_domains is not None
            else None
        )
        combined = Rules(
            read_only=combined.read_only or rule.read_only,
            allow_environment_mailbox=combined.allow_environment_mailbox and rule.allow_environment_mailbox,
            require_approval=combined.require_approval or rule.require_approval,
            require_fips=combined.require_fips or rule.require_fips,
            allowed_tools=narrower(combined.allowed_tools, rule.allowed_tools),
            allowed_recipient_domains=narrower(combined.allowed_recipient_domains, domains),
            cui_recipient_domains=narrower(combined.cui_recipient_domains, cui_domains),
        )
    return combined


def policy_paths() -> tuple[Path, Path]:
    """The administrator's and the user's policy file locations on this OS."""
    admin_directory: Path
    if sys.platform == "win32":
        admin_directory = WINDOWS_ADMIN_DIRECTORY
    elif sys.platform == "darwin":
        admin_directory = MACOS_ADMIN_DIRECTORY
    else:
        admin_directory = LINUX_ADMIN_DIRECTORY
    return admin_directory / POLICY_FILE, user_config_path(APP_NAME, appauthor=False) / POLICY_FILE


def stray_admin_policy() -> Path | None:
    """An administrator's policy left where releases before #122 read it on macOS and Windows
    (platformdirs' folder), while the fixed file is absent; None when there is none. Linux always
    read /etc/email-tool.
    """
    if sys.platform.startswith("linux"):
        return None
    admin: Path = policy_paths()[0]
    old: Path = site_config_path(APP_NAME, appauthor=False) / POLICY_FILE
    return old if old != admin and old.is_file() and not admin.is_file() else None


def parse_tables(path: Path, text: str) -> tuple[Rules, dict[str, Rules]]:
    """Return the [default] rules and the per-mailbox rules in `text`."""
    try:
        document: dict[str, Any] = tomllib.loads(text)
        unknown: set[str] = set(document) - {"default", "mailboxes"}
        if unknown:
            raise SettingsError(f"{path}: unknown section(s) {sorted(unknown)}")
        default: Any = document.get("default", {})
        mailboxes: Any = document.get("mailboxes", {})
        if not isinstance(default, dict) or not isinstance(mailboxes, dict):
            raise SettingsError(f"{path}: [default] and [mailboxes.<name>] must be tables")
        if not all(isinstance(table, dict) for table in mailboxes.values()):
            raise SettingsError(f"{path}: every [mailboxes.<name>] must be a table")
        return Rules(**default), {name: Rules(**table) for name, table in mailboxes.items()}
    except (tomllib.TOMLDecodeError, ValidationError, TypeError) as error:
        raise SettingsError(f"{path} is malformed: {error}") from error


def outside_domains(recipients: list[str], allowed: list[str] | None) -> list[str]:
    """The recipients whose domain is not in `allowed`; none when there is no list."""
    if allowed is None:
        return []
    return sorted(address for address in recipients if address.rpartition("@")[2].lower() not in allowed)


class Policy:
    """The combined administrator and user policy; a file edit takes effect on the next call."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths: tuple[Path, ...] = tuple(paths)
        self._cache: dict[Path, tuple[int, tuple[Rules, dict[str, Rules]]]] = {}

    def _tables(self, path: Path) -> tuple[Rules, dict[str, Rules]]:
        try:
            modified: int = path.stat().st_mtime_ns
            cached: tuple[int, tuple[Rules, dict[str, Rules]]] | None = self._cache.get(path)
            if cached is not None and cached[0] == modified:
                return cached[1]
            tables: tuple[Rules, dict[str, Rules]] = parse_tables(path, path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # A POLICY LEFT AT THE OLD PLACE IS NOT "NO POLICY" (#122): that would drop every
            # restriction an administrator set, without a word. Refused until it is moved.
            stray: Path | None = stray_admin_policy() if path == policy_paths()[0] else None
            if stray is not None:
                raise SettingsError(
                    f"an administrator's policy is at {stray}, where email-tool no longer looks; move it to {path}"
                ) from None
            return Rules(), {}
        except OSError as error:
            # An existing policy that cannot be read is refused, never treated as "no policy".
            raise SettingsError(f"cannot read policy {path}: {error}") from error
        self._cache[path] = (modified, tables)
        return tables

    def rules_for(self, mailbox: str, address: str) -> Rules:
        """The effective rules for the mailbox called `mailbox` with `address`.

        A `[mailboxes.<key>]` table applies when its key is the mailbox's name or its
        address, both compared case-insensitively; an administrator who keys by address
        cannot be escaped by enrolling the same account under another name.
        """
        keys: set[str] = {mailbox.lower(), address.lower()} - {""}
        layers: list[Rules] = []
        for path in self._paths:
            default, mailboxes = self._tables(path)
            layers.append(default)
            layers.extend(rules for key, rules in mailboxes.items() if key.lower() in keys)
        return combine(layers)

    def check_fips(self, mailbox: str, address: str, *, keeps_sign_in: bool) -> None:
        """Raise PolicyRefusal before any connection when `require_fips` is set and OpenSSL is not in FIPS mode.

        `keeps_sign_in` (`Mailbox.keeps_sign_in`, always given): the mailbox logs in with a kept
        sign-in, whose encryption must be FIPS too, before it is even read.
        """
        if not self.rules_for(mailbox, address).require_fips:
            return
        if not fips_enabled():
            raise PolicyRefusal("policy: require_fips is set but Python's OpenSSL is not in FIPS mode")
        if keeps_sign_in and not sign_in_storage_fips_enabled():
            raise PolicyRefusal(
                "policy: require_fips is set but the `cryptography` package that encrypts the kept "
                "sign-in is not on a FIPS provider; use a password mailbox"
            )

    def check_call(
        self,
        mailbox: str,
        address: str,
        tool: str,
        changes_mail: bool,
        known_tools: frozenset[str],
        *,
        keeps_sign_in: bool,
    ) -> None:
        """Raise PolicyRefusal when `tool` may not run on `mailbox`; SettingsError for an unknown tool name."""
        rules: Rules = self.rules_for(mailbox, address)
        self.check_fips(mailbox, address, keeps_sign_in=keeps_sign_in)
        if rules.allowed_tools is not None:
            unknown: set[str] = set(rules.allowed_tools) - known_tools
            if unknown:
                raise SettingsError(f"policy allowed_tools names unknown tool(s) {sorted(unknown)}")
            if tool not in rules.allowed_tools and tool != "list_mailboxes":
                raise PolicyRefusal(f"policy: {tool} is not in allowed_tools for mailbox {mailbox!r}")
        if rules.read_only and changes_mail:
            raise PolicyRefusal(f"policy: mailbox {mailbox!r} is read_only, so {tool} is refused")

    def check_message(
        self,
        mailbox: str,
        address: str,
        recipients: list[str],
        addressed: bool,
        find_markings: Callable[[], list[str]],
    ) -> None:
        """Check a message's real recipients (3.1.1) and, if it is CUI-marked, its CUI recipients (3.1.3).

        `recipients` must be the list the message is really delivered to; `addressed` is True
        when To/Cc held text. `find_markings` runs only when a CUI rule applies.
        """
        rules: Rules = self.rules_for(mailbox, address)
        if addressed and not recipients and rules.allowed_recipient_domains is not None:
            raise PolicyRefusal("policy: the recipients could not be read, so the message is refused")
        outside: list[str] = outside_domains(recipients, rules.allowed_recipient_domains)
        if outside:
            raise PolicyRefusal(f"policy: {', '.join(outside)} outside allowed_recipient_domains for {mailbox!r}")
        if rules.cui_recipient_domains is None:
            return
        found: list[str] = find_markings()
        if not found:
            return
        if addressed and not recipients:
            raise PolicyRefusal("policy: a CUI-marked message whose recipients could not be read is refused")
        cui_outside: list[str] = outside_domains(recipients, rules.cui_recipient_domains)
        if cui_outside:
            raise PolicyRefusal(
                f"policy: the message carries CUI markings ({'; '.join(found)}) and "
                f"{', '.join(cui_outside)} are outside cui_recipient_domains"
            )


def show_rules(policy: Policy, settings_file: Path, mailbox: str, address: str) -> str:
    """The effective rules for a mailbox, saying when address-keyed rules could not be included."""
    from email_tool_mcp.settings import load_mailboxes

    known_address: str = address or getattr(load_mailboxes(settings_file).get(mailbox), "address", "")
    rules: Rules = policy.rules_for(mailbox, known_address)
    if known_address:
        return f"{mailbox} ({known_address}): {rules}"
    return (
        f"{mailbox}: {rules}\nNote: no address known for {mailbox!r}, so rules keyed by address are not "
        "shown. Pass --address you@example.com (e.g. for a mailbox an app sets in its environment)."
    )
