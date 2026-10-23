"""The GitHub side of the report bridge: the `user-report` label, its issues, and opening one, as the bot.

Standard: PyGithub over the repository bot's installation token, reusing `tools.bot_pr` for the token,
the repository and GitHub's own error text, so the bot (not the maintainer) opens every issue.
Placement: tools/report_bridge/_github.py, the GitHub half of the report bridge.
"""

from __future__ import annotations

from typing import Final

from github import GithubException
from github.Issue import Issue
from github.Repository import Repository

from tools.bot_pr import BotError
from tools.bot_pr._github import _as_bot, _repository, _said
from tools.bot_pr._identity import bot_login

LABEL: Final[str] = "user-report"
"""The label the issue form (#95) also gives a report, so both kinds are listed together."""

_LABEL_COLOR: Final[str] = "d93f0b"
_LABEL_DESCRIPTION: Final[str] = "A problem a user reported from their app"


class BotTracker:
    """The repository's issues, read and opened as the bot."""

    def __init__(self, repository: Repository, author: str) -> None:
        self._repository: Repository = repository
        self._author: str = author

    def _has_label(self) -> bool:
        try:
            self._repository.get_label(LABEL)
        except GithubException as error:
            if error.status == 404:
                return False
            raise BotError(f"could not read the {LABEL!r} label ({_said(error)})") from None
        return True

    def filed(self) -> list[str]:
        """The body of every issue the bot opened, open or closed, whatever its labels now.

        Not only `user-report` issues: a report relabelled during triage must still count as filed.
        Only the bot's own: a user's issue (the #95 form) cannot claim a report's marker.
        """
        try:
            return [
                issue.body or ""
                for issue in self._repository.get_issues(state="all")
                if issue.user is not None and issue.user.login == self._author
            ]
        except GithubException as error:
            raise BotError(f"could not list the issues ({_said(error)})") from None

    def ensure_label(self) -> None:
        """Create the `user-report` label when it is missing."""
        if self._has_label():
            return
        try:
            self._repository.create_label(LABEL, _LABEL_COLOR, _LABEL_DESCRIPTION)
        except GithubException as error:
            raise BotError(f"could not create the {LABEL!r} label ({_said(error)})") from None

    def open_issue(self, title: str, body: str) -> str:
        """Open one `user-report` issue and return its URL."""
        try:
            made: Issue = self._repository.create_issue(title=title, body=body, labels=[LABEL])
        except GithubException as error:
            raise BotError(f"could not open the issue ({_said(error)})") from None
        return made.html_url


def bot_tracker() -> BotTracker:
    """The tracker for this checkout's repository (from `origin`), signed in as the bot."""
    return BotTracker(_repository(_as_bot()), bot_login())
