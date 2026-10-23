"""The documented steps, run in a clean environment: empty home, system PATH only.

A step that exits non-zero stops the run: that is a broken instruction in the docs.
The empty home's path is shown as `~` in the saved output.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.clean_install._render import save_svg

log: Final[logging.Logger] = logging.getLogger(__name__)

_REPOSITORY: Final[str] = "git+https://github.com/skhan61/email-tool"
_SYSTEM_PATH: Final[str] = "/usr/local/bin:/usr/bin:/bin"
# A long package list adds nothing a reader acts on.
_PACKAGE_LINE: Final[str] = " + "


@dataclass(frozen=True)
class Step:
    """One command a user types, as the docs show it, and the SVG it becomes."""

    name: str
    title: str
    shown: str
    run: str


class StepFailed(RuntimeError):
    """A documented command failed on a clean machine."""


def steps(source: str) -> list[Step]:
    """The steps in the order the docs give them; `source` is what `uv tool install` installs."""
    return [
        Step(
            "uv-install",
            "Install uv",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
        ),
        Step("uv-check", "Check uv", "uvx --version", "uvx --version"),
        Step(
            "tool-install",
            "Install the email-tool-mcp command",
            f"uv tool install {_REPOSITORY}",
            f"uv tool install {source}",
        ),
        Step("tool-help", "See the commands", "email-tool-mcp --help", "PAGER=cat email-tool-mcp --help"),
        Step("tool-list", "List your mailboxes", "email-tool-mcp list", "email-tool-mcp list"),
        Step(
            "claude-marketplace",
            "Add the marketplace in Claude Code",
            "claude plugin marketplace add skhan61/email-tool",
            "claude plugin marketplace add skhan61/email-tool",
        ),
        Step(
            "claude-install",
            "Install the plugin in Claude Code",
            "claude plugin install email-tool@email-tool",
            "claude plugin install email-tool@email-tool",
        ),
    ]


def _readable(output: str, home: Path, source: str) -> str:
    # A local checkout under test is shown as the address the docs give.
    shown: str = output.replace(f"file://{source}", _REPOSITORY) if source != _REPOSITORY else output
    lines: list[str] = shown.replace(str(home), "~").splitlines()
    packages: int = sum(1 for line in lines if line.startswith(_PACKAGE_LINE))
    kept: list[str] = [line for line in lines if not line.startswith(_PACKAGE_LINE)]
    if packages:
        kept.insert(len(kept) - 1, f" + ... {packages} packages")
    return "\n".join(kept)


def _execute(step: Step, home: Path, tools: Path) -> str:
    environment: dict[str, str] = {
        "HOME": str(home),
        "PATH": f"{_SYSTEM_PATH}:{tools}",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
    }
    # A login shell, as a reopened terminal is: it reads the PATH the uv installer added.
    finished: subprocess.CompletedProcess[str] = subprocess.run(
        ["bash", "-lc", step.run],
        cwd=home,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=600,
        check=False,
    )
    output: str = finished.stdout
    if finished.returncode != 0:
        raise StepFailed(f"{step.name}: `{step.shown}` exited {finished.returncode}:\n{output}")
    return output


def run(source: str = _REPOSITORY, out: str = "docs/assets/screens") -> str:
    """Run every step in a fresh empty home and save `<out>/<step>.svg`; stop at the first failure."""
    claude: str | None = shutil.which("claude")
    if claude is None:
        raise StepFailed("the Claude Code steps need `claude` installed on this machine")
    with tempfile.TemporaryDirectory(prefix="clean-home-") as directory:
        home: Path = Path(directory) / "home"
        home.mkdir()
        # Only `claude` itself joins the clean PATH, never the rest of this user's tool folder.
        tools: Path = Path(directory) / "tools"
        tools.mkdir()
        (tools / "claude").symlink_to(claude)
        step: Step
        for step in steps(source):
            output: str = _execute(step, home, tools)
            save_svg(Path(out) / f"{step.name}.svg", step.title, step.shown, _readable(output, home, source))
            log.info("ok: %s", step.shown)
    return f"all {len(steps(source))} steps passed on a clean home; SVGs in {out}"
