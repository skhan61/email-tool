"""Contract tests for the bot-PR path.

`tools/bot_pr` signs in as a GitHub App through PyGithub (toolpath#129), takes a
one-hour installation token, rewrites a branch's authorship with
`filter-branch` and force-pushes it. All of that shipped with no tests, and two
defects reached `main` because of it: the token sat in `git push`'s argv (and
so could be persisted to `~/.git-credentials`), and the merge base was taken
against a possibly stale `origin/main`, which re-authors commits that are
already on `main`. Both are fixed; these tests are what stops them coming back.

NOTHING HERE NEEDS THE REAL APP KEY AND NOTHING HERE REACHES GITHUB.
The `_offline` fixture below is autouse: it repoints the private key at a path
inside `tmp_path` and makes any HTTP request fail the test. A test that talks to
GitHub uses the `github` fixture, which stands in for PyGithub's classes; a test
that forgets cannot silently use the office PC's real credentials.

PyGithub's own signing and HTTP are the library's to test; these test ours.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests
from github import GithubException

from tools.bot_pr import _git, _github, _identity
from tools.bot_pr._identity import BotError

TOKEN: str = "ghs_fake_installation_token_do_not_persist_me"

# Captured BEFORE any test can monkeypatch it. `tools.bot_pr._git.subprocess` is
# the one shared module object, so patching `run` there patches it for this file
# too -- and an assertion about a file git did not write, because git never ran,
# passes for the wrong reason.
_REAL_RUN: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run


# ── offline guards ────────────────────────────────────────────────────────────


def _refuse_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("a bot_pr test tried to reach the network")


# The identity every test authenticates as. Fixed here rather than read from
# pyproject.toml or from the git remote: the tests must pass in a checkout with
# no remote, no app configured, and no key, which is exactly the state a fresh
# clone of this template is in.
TEST_OWNER: str = "test-owner"
TEST_REPO: str = "test-repo"
TEST_APP_ID: str = "4771321"
TEST_INSTALLATION_ID: str = "157742711"
TEST_BOT_LOGIN: str = "test-repo-bot[bot]"
TEST_BOT_USER_ID: str = "322831886"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No real app key, no network, and a fixed identity for every test.

    Set through the ENVIRONMENT rather than by patching module attributes,
    because that is the documented override path: if these variables stopped
    being honoured, every test here would fail, which is the point.

    `_owner_repo` is patched directly because it shells out to git, and the
    owner and repository are deliberately DERIVED rather than configurable.
    """
    monkeypatch.setattr(urllib.request, "urlopen", _refuse_network)
    monkeypatch.setattr(requests.Session, "request", _refuse_network)
    # THE MACHINE-LEVEL CONFIG IS SEALED OFF, pointed at a path that does not
    # exist. Without this the suite reads whatever `~/.config/github-apps/
    # bot.toml` happens to hold, so a developer who has configured the shared
    # App gets different results from one who has not, and a test asserting
    # that an unset value RAISES passes on a fresh clone and fails on a
    # working machine. Found the moment the real file was created.
    monkeypatch.setenv(_identity.USER_CONFIG_ENV, str(tmp_path / "no-bot.toml"))
    monkeypatch.setattr(_identity, "PYPROJECT", tmp_path / "no-pyproject.toml")
    _identity._repo_config.cache_clear()
    _identity._user_config.cache_clear()
    monkeypatch.setenv(_identity.PRIVATE_KEY_ENV, str(tmp_path / "absent.pem"))
    monkeypatch.setenv(_identity.APP_ID_ENV, TEST_APP_ID)
    monkeypatch.setenv(_identity.INSTALLATION_ID_ENV, TEST_INSTALLATION_ID)
    monkeypatch.setenv(_identity.BOT_LOGIN_ENV, TEST_BOT_LOGIN)
    monkeypatch.setenv(_identity.BOT_USER_ID_ENV, TEST_BOT_USER_ID)
    monkeypatch.setattr(_identity, "_owner_repo", lambda: (TEST_OWNER, TEST_REPO))


# ── helpers ───────────────────────────────────────────────────────────────────


@dataclass
class _Call:
    """One recorded `subprocess.run`."""

    argv: list[str]
    env: dict[str, str] | None
    cwd: Path | None


def _subcommand(argv: list[str]) -> str:
    """The git subcommand in `argv`, stepping over `-c key=value` pairs."""
    index: int = 1
    while index < len(argv):
        if argv[index] == "-c":
            index += 2
            continue
        if argv[index].startswith("-"):
            index += 1
            continue
        return argv[index]
    return ""


@dataclass
class _RecordingRun:
    """Stand-in for `subprocess.run` that records argv and env, and succeeds."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    stdout_by_subcommand: dict[str, str] = field(default_factory=dict)
    calls: list[_Call] = field(default_factory=list)

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env: object = kwargs.get("env")
        cwd: object = kwargs.get("cwd")
        self.calls.append(
            _Call(
                argv=list(argv),
                env=dict(env) if isinstance(env, dict) else None,
                cwd=Path(cwd) if isinstance(cwd, (str, Path)) else None,
            )
        )
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=self.returncode,
            stdout=self.stdout_by_subcommand.get(_subcommand(argv), self.stdout),
            stderr=self.stderr,
        )


class _CapturedLog(logging.Handler):
    """Collects formatted records straight off a logger.

    Straight off the two loggers, so the assertion "the token was not logged"
    never depends on how the root logger is configured.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def logged() -> Iterator[_CapturedLog]:
    """Capture everything both bot_pr loggers emit during a test.

    The level is restored, not just the handler. `setLevel` on a logger is
    process-global and survives the test that set it, so leaving these two at
    DEBUG would change what every later test in the session sees -- the same
    order-dependent leak `tests/test_secrets.py` grew a fixture for.
    """
    handler: _CapturedLog = _CapturedLog()
    loggers: list[logging.Logger] = [_git.log, _github.log]
    levels: list[int] = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    yield handler
    for logger, level in zip(loggers, levels, strict=True):
        logger.removeHandler(handler)
        logger.setLevel(level)


@dataclass
class _Token:
    token: str


@dataclass
class _Pull:
    html_url: str = ""
    head_sha: str = "abc1234def"
    reviews: list[str] = field(default_factory=list)
    draft: bool = True
    marked_ready: int = 0
    drafted: int = 0
    automerge: str = ""

    def enable_automerge(self, merge_method: str) -> None:
        self.automerge = merge_method

    def mark_ready_for_review(self) -> None:
        self.marked_ready += 1
        self.draft = False

    def convert_to_draft(self) -> None:
        self.drafted += 1
        self.draft = True

    @property
    def head(self) -> _Pull:
        return self

    @property
    def sha(self) -> str:
        return self.head_sha

    def get_reviews(self) -> list[_Review]:
        return [_Review(body) for body in self.reviews]


@dataclass
class _Review:
    body: str


@dataclass
class _Repo:
    """What `_github` asks of a PyGithub `Repository`, recorded."""

    refuse: GithubException | None = None
    url: str = "https://api.github.com/repos/test-owner/test-repo"
    pull: _Pull = field(default_factory=_Pull)
    created: list[dict[str, str | bool]] = field(default_factory=list)

    def create_pull(self, base: str, head: str, title: str, body: str, draft: bool = False) -> _Pull:
        if self.refuse is not None:
            raise self.refuse
        self.created.append({"base": base, "head": head, "title": title, "body": body, "draft": draft})
        return self.pull

    def get_pull(self, number: int) -> _Pull:
        return self.pull


@dataclass
class _GitHubStandIn:
    """`GithubIntegration` and `Github`, as `_github` uses them, with nothing on the network."""

    token: str = TOKEN
    token_refused: GithubException | None = None
    repo_refused: GithubException | None = None
    repo: _Repo = field(default_factory=_Repo)
    asked_for: list[str] = field(default_factory=list)
    tokens_used: list[str] = field(default_factory=list)
    unreachable: bool = False

    def integration(self, auth: object) -> _GitHubStandIn:
        return self

    def get_access_token(self, installation: int) -> _Token:
        if self.token_refused is not None:
            raise self.token_refused
        return _Token(self.token)

    def github(self, auth: object) -> _GitHubStandIn:
        self.tokens_used.append(str(getattr(auth, "token", "")))
        return self

    def get_repo(self, name: str) -> _Repo:
        if self.unreachable:
            raise requests.ConnectionError("name resolution failed")
        self.asked_for.append(name)
        if self.repo_refused is not None:
            raise self.repo_refused
        return self.repo


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _GitHubStandIn:
    """PyGithub replaced, and a key file present, so `_github`'s own logic runs."""
    key: Path = tmp_path / "app.pem"
    key.write_text("not read: the stand-in never signs\n")
    monkeypatch.setenv(_identity.PRIVATE_KEY_ENV, str(key))
    stand_in: _GitHubStandIn = _GitHubStandIn()
    monkeypatch.setattr(_github, "GithubIntegration", stand_in.integration)
    monkeypatch.setattr(_github, "Github", stand_in.github)
    return stand_in


def _refused(status: int, message: str) -> GithubException:
    return GithubException(status, {"message": message}, None)


# ── the token ─────────────────────────────────────────────────────────────────


def test_no_private_key_names_the_path_and_why_it_is_not_in_the_store(
    tmp_path: Path,
) -> None:
    with pytest.raises(BotError) as raised:
        _github.installation_token()
    message: str = str(raised.value)
    assert str(tmp_path / "absent.pem") in message
    assert "secret store" in message


def test_installation_token_returns_the_token_and_never_logs_it(github: _GitHubStandIn, logged: _CapturedLog) -> None:
    assert _github.installation_token() == TOKEN
    assert all(TOKEN not in message for message in logged.messages)


def test_a_refused_token_says_githubs_status_and_which_installation(
    github: _GitHubStandIn,
) -> None:
    github.token_refused = _refused(401, "A JSON web token could not be decoded")
    with pytest.raises(BotError) as raised:
        _github.installation_token()
    message: str = str(raised.value)
    assert "HTTP 401" in message and "could not be decoded" in message
    assert _identity.installation_id() in message
    assert TOKEN not in message


def test_no_app_id_names_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty override, not an absent one: the default is a real App ID, so the
    # only way to have no issuer is to blank it deliberately.
    monkeypatch.setenv(_identity.APP_ID_ENV, "   ")
    with pytest.raises(BotError) as raised:
        _identity.app_id()
    message: str = str(raised.value)
    assert _identity.APP_ID_ENV in message
    assert "NOT a secret" in message


class TestOneAppServesEveryRepository:
    """The resolution order: environment, then repository, then machine.

    WHY THE MACHINE LAYER EXISTS. One GitHub App installed on an account with
    "All repositories" serves every repository that account owns, and its four
    identifiers are then IDENTICAL in each one. Writing them into every new
    `pyproject.toml` is a hand-copied fact in N places, and the Nth copy is the
    one that goes stale. These tests are what stops the machine layer being
    quietly removed as redundant.
    """

    @staticmethod
    def _clear_caches() -> None:
        """Both config readers are `@cache`d, so a test changing files must reset."""
        _identity._repo_config.cache_clear()
        _identity._user_config.cache_clear()

    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
        """No repo table, no machine file, and nothing from the real machine."""
        for env in (
            _identity.APP_ID_ENV,
            _identity.INSTALLATION_ID_ENV,
            _identity.BOT_LOGIN_ENV,
            _identity.BOT_USER_ID_ENV,
        ):
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setattr(_identity, "PYPROJECT", tmp_path / "pyproject.toml")
        monkeypatch.setenv(_identity.USER_CONFIG_ENV, str(tmp_path / "bot.toml"))
        self._clear_caches()
        yield
        self._clear_caches()

    def test_the_machine_file_alone_configures_a_fresh_clone(self, tmp_path: Path) -> None:
        """A repository cloned from the template needs NO bot configuration."""
        (tmp_path / "bot.toml").write_text(
            '[bot_pr]\napp_id = "111"\ninstallation_id = "222"\nbot_login = "shared[bot]"\nbot_user_id = "333"\n'
        )
        self._clear_caches()
        assert _identity.app_id() == "111"
        assert _identity.installation_id() == "222"
        assert _identity.bot_login() == "shared[bot]"
        assert _identity.bot_user_id() == "333"

    def test_a_repository_can_override_with_its_own_app(self, tmp_path: Path) -> None:
        """The exception that earns a tracked file: this repo wants its own app.

        It overrides, and because it is tracked, the exception is visible in the
        diff that introduced it rather than in somebody's shell history.
        """
        (tmp_path / "bot.toml").write_text('[bot_pr]\napp_id = "111"\n')
        (tmp_path / "pyproject.toml").write_text('[tool.bot_pr]\napp_id = "999"\n')
        self._clear_caches()
        assert _identity.app_id() == "999"

    def test_the_environment_beats_both(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`BOT_APP_ID=... python -m tools.bot_pr discover` is the setup path.

        It has to work before either file exists, and it has to win once they do,
        or discovering a SECOND app means editing the config you are replacing.
        """
        (tmp_path / "bot.toml").write_text('[bot_pr]\napp_id = "111"\n')
        (tmp_path / "pyproject.toml").write_text('[tool.bot_pr]\napp_id = "999"\n')
        self._clear_caches()
        monkeypatch.setenv(_identity.APP_ID_ENV, "777")
        assert _identity.app_id() == "777"

    def test_an_empty_repo_table_falls_through_rather_than_winning(self, tmp_path: Path) -> None:
        """THE TEMPLATE SHIPS THAT TABLE EMPTY, which is the whole point.

        `app_id = ""` in a cloned pyproject.toml must not shadow a configured
        machine file, or every adopted repository would refuse until somebody
        deleted four blank lines they never wrote.
        """
        (tmp_path / "bot.toml").write_text('[bot_pr]\napp_id = "111"\n')
        (tmp_path / "pyproject.toml").write_text('[tool.bot_pr]\napp_id = ""\ninstallation_id = ""\n')
        self._clear_caches()
        assert _identity.app_id() == "111"

    def test_a_missing_value_names_all_three_places_it_looked(self) -> None:
        """The error is the documentation for anyone who has not read any."""
        with pytest.raises(BotError) as raised:
            _identity.installation_id()
        message: str = str(raised.value)
        assert _identity.INSTALLATION_ID_ENV in message
        assert "pyproject.toml" in message
        assert "bot.toml" in message

    def test_the_private_key_defaults_beside_the_machine_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key belongs to the app, so it lives with the app's identity."""
        monkeypatch.delenv(_identity.PRIVATE_KEY_ENV, raising=False)
        monkeypatch.setattr(_identity, "USER_CONFIG", tmp_path / "bot.toml")
        self._clear_caches()
        assert _identity.private_key().parent == tmp_path

    def test_owner_and_repo_are_in_neither_file(self, tmp_path: Path) -> None:
        """Derived, never configured, so no layer can point at another repo."""
        (tmp_path / "bot.toml").write_text('[bot_pr]\nowner = "wrong"\nrepo = "wrong"\n')
        self._clear_caches()
        assert _identity.owner() == TEST_OWNER
        assert _identity.repo() == TEST_REPO


def test_an_unconfigured_app_id_refuses_and_names_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is NO default App ID, and that is the point.

    A template that shipped a working App ID would ship the previous project's
    identity, and the failure would be silent: the JWT mints, the token comes
    back, and the pull request opens somewhere nobody looked. Unset, it refuses
    and says where to set it.
    """
    monkeypatch.delenv(_identity.APP_ID_ENV, raising=False)
    monkeypatch.setattr(_identity, "_repo_config", dict)
    monkeypatch.setattr(_identity, "_user_config", dict)
    with pytest.raises(BotError) as raised:
        _identity.app_id()
    message: str = str(raised.value)
    assert _identity.APP_ID_ENV in message
    assert "pyproject.toml" in message
    assert "NOT a secret" in message


# ── whoami, open_pr, ready ───────────────────────────────────────────────


def test_whoami_reports_githubs_status_when_the_read_fails(
    github: _GitHubStandIn,
) -> None:
    """Anything that is not a 404 is reported with its status, not guessed."""
    github.repo_refused = _refused(403, "Resource not accessible")
    with pytest.raises(BotError) as raised:
        _github.whoami()
    assert "HTTP 403" in str(raised.value)


def test_whoami_fails_when_the_app_cannot_reach_this_repository(
    github: _GitHubStandIn,
) -> None:
    """A 404 on the repository is the app not being installed on it."""
    github.repo_refused = _refused(404, "Not Found")
    with pytest.raises(BotError) as raised:
        _github.whoami()
    message: str = str(raised.value)
    assert _identity.slug() in message
    assert "All repositories" in message


def test_whoami_asks_about_one_repository_and_never_lists_them(github: _GitHubStandIn, logged: _CapturedLog) -> None:
    """THE REGRESSION TEST FOR A FALSE NEGATIVE THAT REACHED A REAL ACCOUNT: the installation's
    repository list paginates at 30, and searching its first page reported "cannot reach" for a
    repository the app could reach. Asked about directly, there is nothing to paginate.
    """
    assert _github.whoami() == _identity.bot_login()
    assert github.asked_for == [_identity.slug()]
    assert github.tokens_used == [TOKEN], "the installation token reads it"
    assert logged.messages, "whoami must say something on success"
    assert all(TOKEN not in message for message in logged.messages)


def test_open_pr_sends_the_body_file_and_returns_the_url(
    github: _GitHubStandIn, tmp_path: Path, logged: _CapturedLog
) -> None:
    body_file: Path = tmp_path / "body.md"
    body_file.write_text("## What\n\nrefactor, with tests\n")
    url: str = f"https://github.com/{_identity.slug()}/pull/342"
    github.repo.pull.html_url = url
    assert _github.open_pr("refactor/341", "title", str(body_file)) == url
    assert github.repo.created == [
        {
            "base": "main",
            "head": "refactor/341",
            "title": "title",
            "body": "## What\n\nrefactor, with tests\n",
            "draft": True,
        }
    ]
    assert all(TOKEN not in message for message in logged.messages)


def test_open_pr_reports_the_status_when_github_refuses(github: _GitHubStandIn, tmp_path: Path) -> None:
    body_file: Path = tmp_path / "body.md"
    body_file.write_text("body")
    github.repo.refuse = _refused(422, "No commits between main and branch")
    with pytest.raises(BotError) as raised:
        _github.open_pr("refactor/341", "title", str(body_file))
    assert "HTTP 422" in str(raised.value)
    assert "No commits between" in str(raised.value)


def test_ready_refuses_when_no_review_is_posted(github: _GitHubStandIn) -> None:
    """A comment is not a review: the gate would fail (toolpath PR #127, 2026-10-07)."""
    github.repo.pull.reviews = ["looks good"]
    with pytest.raises(BotError) as raised:
        _github.ready(130)
    assert _github.REVIEW_MARKER in str(raised.value)
    assert github.repo.pull.marked_ready == 0 and github.repo.pull.draft


def test_ready_marks_a_reviewed_draft_ready_once(github: _GitHubStandIn) -> None:
    """toolpath#131: the PR opens a draft and goes ready after its review, so the gates run once, for
    real, with nothing to re-run.
    """
    github.repo.pull.reviews = ["## Code review\n\nfindings"]
    assert "ready for review" in _github.ready(130)
    assert github.repo.pull.marked_ready == 1 and not github.repo.pull.draft
    assert github.repo.pull.drafted == 0, "a draft goes ready with no detour"
    assert github.repo.pull.automerge == "SQUASH", "the owner's approval merges it once CI is green"


def test_ready_needs_a_review_that_starts_with_the_heading(github: _GitHubStandIn) -> None:
    github.repo.pull.reviews = ["Code review pending, not done yet"]
    with pytest.raises(BotError):
        _github.ready(130)
    assert github.repo.pull.marked_ready == 0


def test_ready_that_cannot_redraft_does_not_claim_a_draft(
    github: _GitHubStandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    github.repo.pull.reviews = ["## Code review\n\nfindings"]
    github.repo.pull.draft = False

    def refused() -> None:
        raise GithubException(502, {"message": "Bad Gateway"}, None)

    monkeypatch.setattr(github.repo.pull, "convert_to_draft", refused)
    with pytest.raises(BotError) as raised:
        _github.ready(130)
    assert "put back to draft" not in str(raised.value)


def test_ready_on_a_ready_pr_runs_its_gates_again(github: _GitHubStandIn) -> None:
    """toolpath#130 review: a PR opened ready failed its gates before the review and nothing re-runs them,
    so `ready` takes it back to draft and out, which is the one event that runs main's gates.
    """
    github.repo.pull.reviews = ["## Code review\n\nfindings"]
    github.repo.pull.draft = False
    assert "the gates run now" in _github.ready(130)
    assert github.repo.pull.drafted == 1 and github.repo.pull.marked_ready == 1
    assert not github.repo.pull.draft


def test_ready_that_fails_after_redrafting_says_the_pr_is_a_draft(
    github: _GitHubStandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """toolpath#130 second review: a failure between the two steps left a draft with no word of it."""
    github.repo.pull.reviews = ["## Code review\n\nfindings"]
    github.repo.pull.draft = False

    def refused() -> None:
        raise GithubException(502, {"message": "Bad Gateway"}, None)

    monkeypatch.setattr(github.repo.pull, "mark_ready_for_review", refused)
    with pytest.raises(BotError, match="put back to draft.*ready --pr=130"):
        _github.ready(130)


def test_github_out_of_reach_is_said_not_a_traceback(github: _GitHubStandIn) -> None:
    github.unreachable = True
    with pytest.raises(BotError, match="could not reach GitHub"):
        _github.whoami()


def test_an_installation_id_that_is_not_a_number_names_the_fix(
    github: _GitHubStandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_identity.INSTALLATION_ID_ENV, "abc")
    with pytest.raises(BotError, match="not a number.*discover"):
        _github.installation_token()


# ── the filter-branch range, against a real git repository ────────────────────


@dataclass(frozen=True)
class _Fixture:
    """A clone whose `origin/main` is deliberately stale."""

    clone: Path
    branch: str
    already_on_main: list[str]
    branch_only: str


def _git_in(repo: Path, *args: str) -> str:
    result: subprocess.CompletedProcess[str] = _REAL_RUN(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n")
    _git_in(repo, "add", name)
    _git_in(repo, "commit", "-m", f"commit {name}")
    return _git_in(repo, "rev-parse", "HEAD")


@pytest.fixture
def stale_origin(tmp_path: Path) -> _Fixture:
    """Build the exact situation that re-authored other people's commits.

    `origin/main` in this clone points at c1 while origin really is at c3, and
    the feature branch was cut from c3. A merge base taken against the STALE
    ref is c1, so `c1..branch` sweeps up c2 and c3 -- commits that are already
    on `main` -- and filter-branch rewrites their SHAs.
    """
    origin: Path = tmp_path / "origin.git"
    clone: Path = tmp_path / "clone"
    _REAL_RUN(["git", "init", "--quiet", "--bare", "-b", "main", str(origin)], check=True)
    _REAL_RUN(
        ["git", "clone", "--quiet", str(origin), str(clone)],
        check=True,
        capture_output=True,
    )
    _git_in(clone, "config", "user.name", "A Human")
    _git_in(clone, "config", "user.email", "owner@example.com")
    _git_in(clone, "config", "commit.gpgsign", "false")
    # A machine with `core.hooksPath` set globally (pre-commit installs one) would
    # otherwise run this repository's hooks against the fixture's commits.
    _git_in(clone, "config", "core.hooksPath", str(clone / ".git/no-hooks"))

    first: str = _commit(clone, "c1")
    _git_in(clone, "push", "--quiet", "origin", "main")
    second: str = _commit(clone, "c2")
    third: str = _commit(clone, "c3")
    _git_in(clone, "push", "--quiet", "origin", "main")

    # The staleness. A clone that fetched before c2 and c3 landed looks exactly
    # like this: local main is current, the remote-tracking ref is not.
    _git_in(clone, "update-ref", "refs/remotes/origin/main", first)

    branch: str = "refactor/341-fixture"
    _git_in(clone, "checkout", "--quiet", "-b", branch)
    fourth: str = _commit(clone, "c4")
    return _Fixture(
        clone=clone,
        branch=branch,
        already_on_main=[second, third],
        branch_only=fourth,
    )


def _commits_in(repo: Path, rev_range: str) -> list[str]:
    listed: str = _git_in(repo, "rev-list", rev_range)
    return listed.split("\n") if listed else []


def test_a_stale_origin_main_really_would_sweep_up_main_commits(
    stale_origin: _Fixture,
) -> None:
    """The control. Without the fetch, the naive range is wrong -- prove it."""
    naive_base: str = _git_in(stale_origin.clone, "merge-base", "origin/main", stale_origin.branch)
    swept: list[str] = _commits_in(stale_origin.clone, f"{naive_base}..{stale_origin.branch}")
    assert set(stale_origin.already_on_main) <= set(swept)


def test_reauthor_range_fetches_first_and_excludes_commits_already_on_main(
    stale_origin: _Fixture,
) -> None:
    rewrite: str = _git.reauthor_range(stale_origin.branch, cwd=stale_origin.clone)
    assert rewrite.endswith(f"..{stale_origin.branch}")
    assert _commits_in(stale_origin.clone, rewrite) == [stale_origin.branch_only]
    # The fetch is what makes that true, and it must be inside the function.
    assert _git_in(stale_origin.clone, "rev-parse", "origin/main") == stale_origin.already_on_main[-1]


def test_reauthor_commits_rewrites_only_the_branch_commit(
    stale_origin: _Fixture,
) -> None:
    _git.reauthor_commits(stale_origin.branch, cwd=stale_origin.clone)

    # Every commit that was already on main keeps its SHA, so the branch still
    # descends from origin/main and the PR diff shows only its own work.
    for sha in stale_origin.already_on_main:
        assert (
            _REAL_RUN(
                ["git", "merge-base", "--is-ancestor", sha, stale_origin.branch],
                cwd=stale_origin.clone,
                check=False,
            ).returncode
            == 0
        )
    authors: list[str] = _git_in(
        stale_origin.clone,
        "log",
        "--format=%an|%ae",
        f"{stale_origin.already_on_main[-1]}..{stale_origin.branch}",
    ).split("\n")
    assert authors == [f"{_identity.bot_login()}|{_identity.bot_email()}"]
    assert _git_in(stale_origin.clone, "log", "-1", "--format=%an", "origin/main") == "A Human"


def test_reauthor_commits_is_a_no_op_when_the_branch_adds_nothing(
    stale_origin: _Fixture,
) -> None:
    """filter-branch exits 2 on an empty range, which is not a failure here.

    Re-pushing a branch that `main` has caught up with is ordinary. Without the
    guard, git says "Found nothing to rewrite", `run_git` raises, and the push
    never happens for a branch that was perfectly pushable.
    """
    _git_in(stale_origin.clone, "checkout", "--quiet", "-b", "caught-up", "main")
    before: str = _git_in(stale_origin.clone, "rev-parse", "caught-up")
    _git.reauthor_commits("caught-up", cwd=stale_origin.clone)
    assert _git_in(stale_origin.clone, "rev-parse", "caught-up") == before


def test_reauthor_range_reports_gitx_own_error(stale_origin: _Fixture) -> None:
    with pytest.raises(BotError) as raised:
        _git.reauthor_range("no-such-branch", cwd=stale_origin.clone)
    assert "no-such-branch" in str(raised.value)


def test_lease_flag_pins_to_the_fetched_ref_or_falls_back(
    stale_origin: _Fixture,
) -> None:
    # No remote-tracking ref for the branch yet: it has never been pushed.
    assert _git.lease_flag(stale_origin.branch, cwd=stale_origin.clone) == ("--force-with-lease")
    _git_in(
        stale_origin.clone,
        "update-ref",
        f"refs/remotes/origin/{stale_origin.branch}",
        stale_origin.branch_only,
    )
    assert _git.lease_flag(stale_origin.branch, cwd=stale_origin.clone) == (
        f"--force-with-lease={stale_origin.branch}:{stale_origin.branch_only}"
    )


# ── the token reaches the environment and nowhere else ────────────────────────


def _push_with_recorder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    branch: str = "refactor/341",
    reauthor: bool = False,
) -> _RecordingRun:
    # `rev-list` must answer with something: an empty answer means "this branch
    # adds no commits", and `reauthor_commits` then skips filter-branch.
    recorder: _RecordingRun = _RecordingRun(
        stdout_by_subcommand={"rev-list": "1111111111111111111111111111111111111111"}
    )
    monkeypatch.setattr(_git, "installation_token", lambda: TOKEN)
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.chdir(tmp_path)
    # THE DEFAULT PATH unless a test asks for the rewrite, as production does since #51.
    assert _git.push(branch, reauthor=reauthor) == branch
    return recorder


def test_the_token_never_reaches_argv_a_file_or_a_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, logged: _CapturedLog
) -> None:
    recorder: _RecordingRun = _push_with_recorder(monkeypatch, tmp_path)

    for call in recorder.calls:
        assert all(TOKEN not in argument for argument in call.argv), call.argv
    assert all(TOKEN not in message for message in logged.messages)
    assert not any(TOKEN in path.read_text(errors="replace") for path in tmp_path.rglob("*") if path.is_file())

    carriers: list[_Call] = [call for call in recorder.calls if call.env is not None and TOKEN in call.env.values()]
    assert len(carriers) == 1
    assert carriers[0].env is not None
    assert carriers[0].env["GH_BOT_TOKEN"] == TOKEN
    assert "push" in carriers[0].argv


def test_the_push_clears_inherited_credential_helpers_before_adding_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder: _RecordingRun = _push_with_recorder(monkeypatch, tmp_path)
    argv: list[str] = next(call.argv for call in recorder.calls if "push" in call.argv)
    helpers: list[str] = [
        argv[index + 1]
        for index, item in enumerate(argv)
        if item == "-c" and argv[index + 1].startswith("credential.helper=")
    ]
    assert len(helpers) == 2
    # The empty one FIRST. It resets the helper list, so nothing inherited from
    # ~/.gitconfig can persist the token; the inline one then reads it from the
    # environment. Reversed, the store would still be in the chain.
    assert helpers[0] == "credential.helper="
    assert "$GH_BOT_TOKEN" in helpers[1]
    assert TOKEN not in helpers[1]
    # And no https://user:token@ URL, which is where the token used to live.
    assert f"https://github.com/{_identity.slug()}.git" in argv


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_real_credential_chain_writes_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run git's own credential machinery with the argv `push_branch` builds.

    `credential approve` is what git calls after a successful HTTPS auth, and
    it is what wrote the one-hour token to ~/.git-credentials on any machine
    configured with `credential.helper=store`. The control at the end of this
    test does write that file, so the assertion above it is not vacuous.
    """
    recorder: _RecordingRun = _push_with_recorder(monkeypatch, tmp_path)
    argv: list[str] = next(call.argv for call in recorder.calls if "push" in call.argv)
    config: list[str] = [
        item for index, entry in enumerate(argv) for item in ([entry, argv[index + 1]] if entry == "-c" else [])
    ]

    home: Path = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[credential]\n\thelper = store\n")
    handshake: str = f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={TOKEN}\n"
    environment: dict[str, str] = {
        **os.environ,
        "HOME": str(home),
        # Explicit, so a runner that already exports GIT_CONFIG_GLOBAL cannot
        # quietly hide the `helper = store` this test needs to be meaningful.
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        # And no system file: macOS's adds the keychain helper, which waits for a password on CI.
        "GIT_CONFIG_NOSYSTEM": "1",
        "GH_BOT_TOKEN": TOKEN,
    }
    _REAL_RUN(
        ["git", *config, "credential", "approve"],
        input=handshake,
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    assert not (home / ".git-credentials").exists()

    _REAL_RUN(
        ["git", "credential", "approve"],
        input=handshake,
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    assert TOKEN in (home / ".git-credentials").read_text()


def test_a_rejected_push_raises_with_the_token_scrubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rejected: _RecordingRun = _RecordingRun(
        returncode=1,
        stderr=(
            f"remote: Permission denied\nfatal: could not read from "
            f"https://x-access-token:{TOKEN}@github.com/{_identity.slug()}.git"
        ),
    )
    monkeypatch.setattr(subprocess, "run", rejected)
    with pytest.raises(BotError) as raised:
        _git.push_branch("refactor/341", TOKEN, cwd=tmp_path)
    message: str = str(raised.value)
    assert TOKEN not in message
    assert "<token>" in message
    assert "Permission denied" in message


def test_push_without_reauthor_does_not_rewrite_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder: _RecordingRun = _RecordingRun()
    monkeypatch.setattr(_git, "installation_token", lambda: TOKEN)
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.chdir(tmp_path)
    _git.push("refactor/341", reauthor=False)
    assert not any("filter-branch" in call.argv for call in recorder.calls)


def test_push_rewrites_history_before_it_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder: _RecordingRun = _push_with_recorder(monkeypatch, tmp_path, reauthor=True)
    order: list[str] = [
        "filter-branch" if "filter-branch" in call.argv else "push"
        for call in recorder.calls
        if "filter-branch" in call.argv or "push" in call.argv
    ]
    assert order == ["filter-branch", "push"]


def test_run_git_carries_gits_own_stderr_not_just_a_return_code(
    tmp_path: Path,
) -> None:
    with pytest.raises(BotError) as raised:
        _git.run_git(["rev-parse", "--verify", "nope"], "could not resolve", cwd=None)
    message: str = str(raised.value)
    assert "could not resolve" in message
    assert "non-zero exit status" not in message


# ── the CLI surface every agent already types ─────────────────────────────────


def test_the_package_re_exports_the_three_verbs() -> None:
    import tools.bot_pr as bot_pr

    assert bot_pr.whoami is _github.whoami
    assert bot_pr.open_pr is _github.open_pr
    assert bot_pr.push is _git.push


def test_the_cli_signatures_are_unchanged() -> None:
    """CLAUDE.md documents these flags and agents type them. They cannot drift."""
    import inspect

    import tools.bot_pr as bot_pr

    assert list(inspect.signature(bot_pr.whoami).parameters) == []
    push_parameters: dict[str, inspect.Parameter] = dict(inspect.signature(bot_pr.push).parameters)
    assert list(push_parameters) == ["branch", "reauthor", "base"]
    # OFF BY DEFAULT (#51): the PR author, not the commit author, blocks self-approval.
    assert push_parameters["reauthor"].default is False
    open_pr_parameters: dict[str, inspect.Parameter] = dict(inspect.signature(bot_pr.open_pr).parameters)
    assert list(open_pr_parameters) == ["branch", "title", "body_file", "base"]
    assert open_pr_parameters["base"].default == "main"


def test_main_exposes_exactly_those_verbs() -> None:
    """Parse `__main__.py` rather than run it: it must stay parsing plus a call."""
    import ast

    source: Path = Path(__file__).resolve().parents[1] / "tools/bot_pr/__main__.py"
    tree: ast.Module = ast.parse(source.read_text())
    calls: list[ast.Call] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Fire"
    ]
    assert len(calls) == 1
    mapping: ast.expr = calls[0].args[0]
    assert isinstance(mapping, ast.Dict)
    verbs: list[str] = [
        key.value for key in mapping.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
    ]
    assert verbs == ["discover", "whoami", "push", "open_pr", "ready"]
    # No definitions left in the entry point; that is the whole point.
    assert not [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]


def test_only_a_rewrite_force_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A plain push is refused as non-fast-forward when GitHub holds a commit this clone lacks;
    a forced one would discard it, so only `--reauthor` forces (#52 review).
    """
    for reauthor, forced in ((False, False), (True, True)):
        recorder: _RecordingRun = _push_with_recorder(monkeypatch, tmp_path, reauthor=reauthor)
        pushes: list[list[str]] = [call.argv for call in recorder.calls if "push" in call.argv]
        assert pushes
        assert any("--force-with-lease" in arg for arg in pushes[-1]) is forced
