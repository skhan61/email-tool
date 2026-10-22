"""Who the bot is, where its key lives, and the one error type.

NOTHING HERE IS A SECRET. The private key is the secret; everything else is
public metadata, and writing it down is the point: in the repository this
template came from, the App ID, the installation id and the bot's user id were
nowhere on disk, which is exactly why the whole procedure evaporated between
sessions.

WHERE THE VALUES COME FROM
--------------------------
`OWNER` and `REPO` are DERIVED from `git remote get-url origin`, never written
down. A template that ships them as constants ships the previous project's
values, and the failure mode is silent: the tooling authenticates fine and opens
the pull request against somebody else's repository. Deriving them makes that
unrepresentable.

The other four cannot be derived offline. They are resolved in this order, and
the FIRST hit wins:

    1. the environment       BOT_APP_ID, BOT_INSTALLATION_ID, ...
    2. `[tool.bot_pr]` in this repository's `pyproject.toml`
    3. `[bot_pr]` in ~/.config/github-apps/bot.toml

LAYER 3 IS THE ONE THAT MATTERS, and it is why layer 2 ships empty. ONE GitHub
App can serve every repository you own: you create it once, install it on the
account with "All repositories", and its App ID, installation id, login and user
id are then IDENTICAL in every repo. Writing those same four numbers into every
new `pyproject.toml` would be a hand-copied fact in N places, which is the thing
this repository exists to refuse. Put them in the machine-level file once, and a
repository cloned from this template needs no bot configuration at all.

Layer 2 remains for the case that earns it: a repository that deliberately wants
its OWN app, separate from the shared one. It overrides, and it is tracked, so
the exception is visible in the diff that introduced it.

An unconfigured value raises `BotError` naming all three layers rather than
defaulting to something plausible. `python -m tools.bot_pr discover` prints the
block, and says where to put it.

This module is the bottom of the package. `_github` and `_git` both
import it and it imports none of them, so there is no cycle to reason about.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from functools import cache
from pathlib import Path


class BotError(RuntimeError):
    """Something in the bot PR path is not set up, with what to fix named."""


API: str = "https://api.github.com"

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
PYPROJECT: Path = REPO_ROOT / "pyproject.toml"

USER_CONFIG_ENV: str = "BOT_CONFIG"
USER_CONFIG: Path = Path.home() / ".config/github-apps/bot.toml"
"""Machine-level identity for an app shared across every repository.

Beside the private key it belongs to, not in the repository: an app identity is
a property of the machine that can act as the bot, and the repositories it acts
on come and go.
"""

# Env overrides, so a second app can be used without editing a tracked file.
APP_ID_ENV: str = "BOT_APP_ID"
INSTALLATION_ID_ENV: str = "BOT_INSTALLATION_ID"
BOT_LOGIN_ENV: str = "BOT_LOGIN"
BOT_USER_ID_ENV: str = "BOT_USER_ID"
PRIVATE_KEY_ENV: str = "BOT_PRIVATE_KEY"

# `git@github.com:owner/repo.git` and `https://github.com/owner/repo.git` both.
_REMOTE_PATTERN: re.Pattern[str] = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")

_SETUP_HINT: str = (
    "ONE app can serve every repository you own: create it once, install it "
    "on the account with 'All repositories', then run "
    "`python -m tools.bot_pr discover` and put its output in "
    f"{USER_CONFIG} under [bot_pr]. Only a repository that deliberately wants "
    "its own app needs [tool.bot_pr] in its pyproject.toml. See README.md."
)


def _table(path: Path, keys: tuple[str, ...]) -> dict[str, object]:
    """One TOML table, addressed by `keys`, or an empty dict.

    Never raises on a malformed or absent file beyond what tomllib reports: a
    missing config is the ordinary state of a fresh clone, not an error.
    """
    if not path.is_file():
        return {}
    current: object = tomllib.loads(path.read_text())
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


@cache
def _repo_config() -> dict[str, object]:
    """`[tool.bot_pr]` from this repository's pyproject.toml."""
    return _table(PYPROJECT, ("tool", "bot_pr"))


@cache
def _user_config() -> dict[str, object]:
    """`[bot_pr]` from the machine-level file, the shared-app layer."""
    override: str = os.environ.get(USER_CONFIG_ENV, "").strip()
    return _table(Path(override) if override else USER_CONFIG, ("bot_pr",))


def _configured(key: str) -> str:
    """The value from the repository, else the machine. Empty when neither has it."""
    for source in (_repo_config(), _user_config()):
        raw: object = source.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def _setting(key: str, env_name: str) -> str:
    """One configured value: environment, then repository, then machine.

    Raises rather than defaulting. A plausible default here is the previous
    project's identity, and it fails by opening a pull request somewhere nobody
    is looking rather than by refusing.
    """
    from_env: str = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env
    value: str = _configured(key)
    if not value:
        raise BotError(
            f"`{key}` is not configured. Looked in ${env_name}, in "
            f"[tool.bot_pr] in {PYPROJECT.name}, and in [bot_pr] in "
            f"{USER_CONFIG}. It is NOT a secret.\n{_SETUP_HINT}"
        )
    return value


@cache
def _remote_url() -> str:
    """`origin`'s URL. Raises rather than guessing a repository."""
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BotError(
            "this checkout has no `origin` remote, so the owner and repository "
            "cannot be derived. Add one with `git remote add origin ...`."
        )
    return completed.stdout.strip()


@cache
def _owner_repo() -> tuple[str, str]:
    """(owner, repo), derived from the remote. Never written down anywhere."""
    url: str = _remote_url()
    match: re.Match[str] | None = _REMOTE_PATTERN.search(url)
    if match is None:
        raise BotError(
            f"`origin` is {url!r}, which is not a github.com URL, so the owner "
            f"and repository cannot be derived from it."
        )
    return match.group("owner"), match.group("repo")


def owner() -> str:
    """The repository owner, derived from `origin`."""
    return _owner_repo()[0]


def repo() -> str:
    """The repository name, derived from `origin`."""
    return _owner_repo()[1]


def slug() -> str:
    """`owner/repo`, the form GitHub's API and error messages both use."""
    return f"{owner()}/{repo()}"


def app_id() -> str:
    """The JWT issuer. Raises rather than minting a token nobody will accept."""
    return _setting("app_id", APP_ID_ENV)


def installation_id() -> str:
    """The installation the token is minted for."""
    return _setting("installation_id", INSTALLATION_ID_ENV)


def bot_login() -> str:
    """The bot's GitHub login, `<app-slug>[bot]`."""
    return _setting("bot_login", BOT_LOGIN_ENV)


def bot_user_id() -> str:
    """The bot's numeric user id, which its noreply address is built from."""
    return _setting("bot_user_id", BOT_USER_ID_ENV)


def private_key() -> Path:
    """Where the app's private key lives. THE ONLY SECRET in this package.

    Defaulted rather than required: the path is a local convention, and a wrong
    one fails immediately and visibly when the file is not there, unlike a wrong
    installation id, which authenticates cleanly against the wrong repository.

    The per-repository default is last, so a shared app names its key once in
    the machine-level file instead of once per clone.
    """
    from_env: str = os.environ.get(PRIVATE_KEY_ENV, "").strip()
    if from_env:
        return Path(from_env).expanduser()
    configured: str = _configured("private_key")
    if configured:
        return Path(configured).expanduser()
    return USER_CONFIG.parent / f"{repo()}-bot.pem"


def bot_identity() -> str:
    """The `Name <email>` git identity the bot's commits are re-authored to."""
    return f"{bot_login()} <{bot_email()}>"


def bot_email() -> str:
    """GitHub's noreply address for the bot account."""
    return f"{bot_user_id()}+{bot_login()}@users.noreply.github.com"
