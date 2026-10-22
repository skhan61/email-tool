"""The GitHub side, through PyGithub (toolpath#129): the token, whoami, discover, open_pr, ready.

PYGITHUB, NOT OUR OWN CLIENT. This was urllib calls and an RS256 JWT signed by an `openssl`
subprocess, about 390 lines re-implementing what the library ships: GitHub App auth
(`Auth.AppAuth`, `GithubIntegration`), installation tokens, pull requests, reviews, check runs and
re-running a workflow's failed jobs. What is left here is our own logic: which repository, which
gate, and what to tell the operator when GitHub says no.

NO TOKEN IS EVER PRINTED OR WRITTEN
-----------------------------------
The installation token lives in memory for the life of the process. It is returned to callers and
passed to git through the environment; it is never logged, never formatted into an error message,
and never written to a file. `tests/test_bot_pr.py` asserts that rather than this paragraph
promising it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import requests
from github import Auth, Github, GithubException, GithubIntegration
from github.AuthenticatedUser import AuthenticatedUser
from github.Installation import Installation
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from github.Repository import Repository

from tools.bot_pr._identity import (
    USER_CONFIG,
    BotError,
    app_id,
    bot_login,
    installation_id,
    owner,
    private_key,
    repo,
    slug,
)

log: logging.Logger = logging.getLogger(__name__)


GATE_CHECK: str = "code review posted"
"""The gate a review satisfies. Must match the job's `name:` in `.github/workflows/gates.yml`."""

REVIEW_MARKER: str = "## Code review"
"""How a review that gate counts must start. Must match the string in `gates.yml`."""


def _said(error: GithubException) -> str:
    """GitHub's own reason, never the request: a request can carry a token."""
    data: object = error.data
    message: object = data.get("message") if isinstance(data, dict) else None
    return f"HTTP {error.status}: {message or str(data)[:200]}"


def _app() -> GithubIntegration:
    """The App, signed in with its private key. THE KEY IS THE ONLY SECRET."""
    key: Path = private_key()
    if not key.is_file():
        raise BotError(
            f"no app private key at {key}. It is deliberately not in the "
            "secret store (see CONTRIBUTING.md): it is a machine identity, and a store "
            "three machines can decrypt would let any of them act as the bot."
        )
    return GithubIntegration(auth=Auth.AppAuth(app_id(), key.read_text()))


def installation_token() -> str:
    """A 1-hour installation token for this repository's installation. Never printed."""
    return _reached(_installation_token)


def _installation_token() -> str:
    identifier: str = installation_id()
    if not identifier.strip().isdigit():
        raise BotError(
            f"installation_id {identifier!r} is not a number. Read the real one with `python -m tools.bot_pr discover`."
        )
    try:
        return _app().get_access_token(int(identifier)).token
    except GithubException as error:
        raise BotError(
            f"could not mint an installation token ({_said(error)}). Check App ID "
            f"{app_id()} and that installation {identifier} still exists."
        ) from None


def _reached(call: Callable[[], str]) -> str:
    """`call`, with GitHub out of reach said as a `BotError`, not a traceback (toolpath#128 review: the
    urllib client said "could not reach"; PyGithub raises `requests`' own errors).
    """
    try:
        return call()
    except requests.RequestException as error:
        raise BotError(f"could not reach GitHub ({type(error).__name__}): check the network") from None


def _as_bot() -> Github:
    return Github(auth=Auth.Token(installation_token()))


def _repository(github: Github) -> Repository:
    try:
        return github.get_repo(slug())
    except GithubException as error:
        if error.status == 404:
            raise BotError(
                f"the token was minted, but the app cannot see {slug()}. Install it "
                f"on this repository, or set the installation to 'All repositories': "
                f"https://github.com/settings/apps/{bot_login().removesuffix('[bot]')}"
                f"/installations"
            ) from None
        raise BotError(f"reading {slug()} failed ({_said(error)})") from None


def whoami() -> str:
    return _reached(_whoami)


def _whoami() -> str:
    """Prove the key, App ID AND access to THIS repository work. Reveals no token.

    ONE REPOSITORY ASKED ABOUT DIRECTLY, never the installation's list searched: that list is
    paginated, and an App installed on all of an account's repositories gave a false "cannot
    reach" on the first page.
    """
    _repository(_as_bot())
    login: str = bot_login()
    log.info("token minted for %s; it can reach %s", login, slug())
    return login


def discover() -> str:
    return _reached(_discover)


def _discover() -> str:
    """Print the `[tool.bot_pr]` block for this repository. Configures nothing.

    Every value is READ FROM THE API, so the only thing anyone types is the App ID, which is the
    one field GitHub puts behind sudo mode and refuses to a token. It prints, and never writes:
    what goes in a tracked file is a decision.
    """
    app: GithubIntegration = _app()
    try:
        app_slug: str = app.get_app().slug
        installed: Installation = app.get_repo_installation(owner(), repo())
        token: str = app.get_access_token(installed.id).token
        login: str = f"{app_slug}[bot]"
        user: NamedUser | AuthenticatedUser = Github(auth=Auth.Token(token)).get_user(login)
        user_id: int = user.id
    except GithubException as error:
        raise BotError(
            f"could not read the App's identity for {slug()} ({_said(error)}). App ID "
            f"{app_id()} and the private key must belong to the same app, installed on "
            f"{slug()}."
        ) from None
    log.info("discovered the identity for %s/%s", owner(), repo())
    # RETURNED, not printed: `fire` writes a verb's return value to stdout.
    return (
        f"# One app serves every repository. Put this in {USER_CONFIG}:\n"
        "[bot_pr]\n"
        f'app_id = "{app_id()}"\n'
        f'installation_id = "{installed.id}"\n'
        f'bot_login = "{login}"\n'
        f'bot_user_id = "{user_id}"\n'
        "\n"
        "# Only for a repository that deliberately wants its OWN app, in its\n"
        "# pyproject.toml, where it overrides the file above:\n"
        "# [tool.bot_pr]  (same four keys)\n"
        "#\n"
        "# owner and repo are never written down: both are derived from\n"
        "# `git remote get-url origin`.\n"
    )


def open_pr(branch: str, title: str, body_file: str, base: str = "main") -> str:
    """Open the pull request as the bot. Returns its URL."""
    # `fire` turns a numeric-looking flag (a title of 2026) into a number; GitHub needs text.
    return _reached(lambda: _open_pr(str(branch), str(title), str(body_file), str(base)))


def _open_pr(branch: str, title: str, body_file: str, base: str) -> str:
    body: str = Path(body_file).read_text()
    try:
        # A DRAFT FIRST (toolpath#131): the gates skip a draft, and run once, for real, when `ready` marks
        # it ready after the review is posted. Opened ready, the review gate always failed first.
        made: PullRequest = _repository(_as_bot()).create_pull(
            base=base, head=branch, title=title, body=body, draft=True
        )
    except GithubException as error:
        raise BotError(f"could not open the PR ({_said(error)})") from None
    log.info("opened %s as %s", made.html_url, bot_login())
    return made.html_url


def ready(pr: int) -> str:
    """Mark the draft PR ready for review once its code review is posted (toolpath#131)."""
    return _reached(lambda: _ready(pr))


def _ready(pr: int) -> str:
    """The PR out of draft, so the gates run on it once, with the review already there; then auto-merge.

    WHY A DRAFT. The review can only be posted after the PR exists, and a PR opened ready ran
    `code review posted` before it. A draft skips both gates (`gates.yml`), and `ready_for_review`
    runs them on the PR as it is.

    IT REFUSES WHEN THERE IS NO REVIEW, rather than letting the gate fail.

    A PR ALREADY READY goes back to draft and out again, the one event that re-runs the gates. That
    also turns auto-merge off, which is why auto-merge is switched on here, last: the owner's approval
    then merges it once CI is green.
    """
    redrafted: bool = False
    try:
        pull: PullRequest = _repository(_as_bot()).get_pull(pr)
        if not any((one.body or "").lstrip().startswith(REVIEW_MARKER) for one in pull.get_reviews()):
            raise BotError(
                f"PR #{pr} has no review starting {REVIEW_MARKER!r}: post the /code-review "
                "findings on it first, as a review."
            )
        if not pull.draft:
            pull.convert_to_draft()
            redrafted = True
        pull.mark_ready_for_review()
        redrafted = False
        pull.enable_automerge(merge_method="SQUASH")
    except GithubException as error:
        left: str = f": it was put back to draft and is one now, so run `ready --pr={pr}` again" if redrafted else ""
        raise BotError(f"could not mark PR #{pr} ready ({_said(error)}){left}") from None
    log.info("PR #%s marked ready for review, auto-merge on", pr)
    return f"PR #{pr} is ready for review: the gates run now, and it merges once approved and green"
