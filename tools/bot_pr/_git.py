"""The git side: push a branch as the bot, rewriting its commits to the bot only when asked.

THE TOKEN IS NOT IN argv, AND NOT IN ANY FILE
---------------------------------------------
It used to be embedded in the push URL, which put it in `git push`'s argv --
readable from /proc/<pid>/cmdline by any local user for the life of the push,
and re-passed to the git-remote-https child. Worse, git calls
credential_approve() after a successful HTTPS auth even when the password came
from the URL, so on any machine with `credential.helper=store` the one-hour
token was written to ~/.git-credentials.

Instead: an empty `credential.helper` first, which CLEARS every inherited
helper so nothing can persist the token, then an inline helper that reads it
from the environment. The env of a process is not world-readable on Linux the
way its argv is.

THE MERGE BASE IS TAKEN AGAINST A FRESHLY FETCHED main
------------------------------------------------------
`reauthor_range` fetches before it asks for a merge base, and the fetch is
inside the same function on purpose: with a stale `origin/main`,
`merge_base..branch` includes commits that are ALREADY ON main, filter-branch
re-authors them to the bot with new SHAs, the branch permanently diverges, and
the PR diff shows other people's commits reattributed. A caller
that could forget to fetch first is a caller that can reintroduce that.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from tools.bot_pr._github import installation_token
from tools.bot_pr._identity import (
    BotError,
    bot_email,
    bot_identity,
    bot_login,
    slug,
)

log: logging.Logger = logging.getLogger(__name__)

# filter-branch prints a paragraph recommending git-filter-repo on every run.
# Sound advice for large histories; this rewrites a handful of commits on one
# branch, and adding a third-party binary to every machine to silence a warning
# is the worse trade.
_SQUELCH: dict[str, str] = {"FILTER_BRANCH_SQUELCH_WARNING": "1"}


def run_git(
    args: list[str],
    why: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> str:
    """Run git, or raise BotError carrying git's own stderr.

    `check=True` with `capture_output=True` raises CalledProcessError, whose
    message is only the return code -- the captured stderr is discarded. That
    turned a routine "cannot rewrite branches: you have unstaged changes" into
    "returned non-zero exit status 1" with no cause.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise BotError(f"{why}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def reauthor_range(branch: str, cwd: Path | None = None) -> str:
    """`<merge-base>..<branch>`, computed against a JUST-FETCHED origin/main."""
    run_git(["fetch", "--quiet", "origin", "main"], "could not fetch origin/main", cwd=cwd)
    merge_base: str = run_git(
        ["merge-base", "origin/main", branch],
        f"could not find where {branch} left main",
        cwd=cwd,
    )
    return f"{merge_base}..{branch}"


def reauthor_commits(branch: str, cwd: Path | None = None) -> str:
    """Rewrite the branch's own commits to the bot. Returns the range rewritten.

    The commits on a branch carry whatever `git config user.name` said when they
    were made. Bot-opened PRs have the bot as commit author, so this keeps the history
    uniform rather than leaving a branch whose PR is the bot's and whose commits
    are the operator's.
    """
    rewrite: str = reauthor_range(branch, cwd=cwd)
    # An empty range is not an error, but filter-branch thinks it is: it exits 2
    # with "Found nothing to rewrite", which `run_git` turns into "could not
    # rewrite authorship: Found nothing to rewrite" and the push never happens.
    # That is the ordinary case of re-pushing a branch that main has caught up
    # with, so it must not be fatal.
    if not run_git(["rev-list", rewrite], f"could not list the commits on {branch}", cwd=cwd):
        log.info("%s adds no commits to main; nothing to re-author", branch)
        return rewrite
    email: str = bot_email()
    login: str = bot_login()
    log.info("rewriting authorship of %s to the bot", rewrite)
    run_git(
        [
            "filter-branch",
            "-f",
            "--env-filter",
            f'export GIT_AUTHOR_NAME="{login}"; '
            f'export GIT_AUTHOR_EMAIL="{email}"; '
            f'export GIT_COMMITTER_NAME="{login}"; '
            f'export GIT_COMMITTER_EMAIL="{email}"',
            rewrite,
        ],
        "could not rewrite authorship",
        env={**os.environ, **_SQUELCH},
        cwd=cwd,
    )
    log.info("authorship now %s", bot_identity())
    return rewrite


def lease_flag(branch: str, cwd: Path | None = None) -> str:
    """`--force-with-lease` pinned to the ref we just fetched.

    Without an explicit value it compares to refs/remotes/origin/<branch>, which
    a URL push never updates, so it failed "stale info" even when nothing had
    changed. Used only with `--reauthor`: re-authoring rewrites every SHA, and a
    plain --force would discard a concurrent push silently.
    """
    remote_sha: str = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    ).stdout.strip()
    return f"--force-with-lease={branch}:{remote_sha}" if remote_sha else "--force-with-lease"


def push_branch(branch: str, token: str, cwd: Path | None = None, force: bool = False) -> None:
    """Push `branch` over HTTPS with `token`, which reaches only the environment.

    PLAIN UNLESS `force` (#52 review): only a rewrite needs the lease. A plain push is refused as
    non-fast-forward when GitHub holds a commit this clone lacks (an "Update branch" merge, an
    accepted suggestion), where a forced one would have discarded it.
    """
    credential_helper: str = '!f() { echo username=x-access-token; echo "password=$GH_BOT_TOKEN"; }; f'
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            f"credential.helper={credential_helper}",
            "push",
            *([lease_flag(branch, cwd=cwd)] if force else []),
            f"https://github.com/{slug()}.git",
            f"{branch}:{branch}",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env={**os.environ, "GH_BOT_TOKEN": token},
    )
    if result.returncode != 0:
        # Scrub, belt and braces: the token should not appear in git's output,
        # but a redacted-URL error message is not worth betting a credential on.
        combined: str = f"{result.stderr.strip()}\n{result.stdout.strip()}".strip()
        raise BotError(f"push failed: {combined.replace(token, '<token>')[:400]}")


def push(branch: str, reauthor: bool = False) -> str:
    """Push `branch` as the bot. With `reauthor`, rewrite its commits to the bot.

    OFF BY DEFAULT (#51): GitHub's rule against approving your own PR looks at who OPENED it, which
    `open_pr` makes the bot, not at who wrote the commits. Rewriting changed every SHA after the
    push, so a merge had to look up the new head before it could name it.
    """
    token: str = installation_token()

    # Fetch the branch too, so `lease_flag` has a ref to pin the lease to. It is
    # allowed to fail: on a first push the branch does not exist on the remote.
    subprocess.run(["git", "fetch", "--quiet", "origin", branch], capture_output=True, check=False)
    if reauthor:
        reauthor_commits(branch)
    push_branch(branch, token, force=reauthor)
    log.info("pushed %s as the bot", branch)
    return branch
