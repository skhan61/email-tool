"""One step's command and output as an SVG terminal window.

Standard: rich's `Console(record=True).export_svg`, which writes real text as vector SVG.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

from rich.console import Console
from rich.text import Text

_WIDTH: Final[int] = 100


def save_svg(path: Path, title: str, command: str, output: str) -> None:
    """Write `command` and its `output` to `path` as a terminal window titled `title`."""
    console: Console = Console(record=True, width=_WIDTH, file=io.StringIO(), color_system=None)
    console.print(Text(f"$ {command}", style="bold"))
    console.print(Text(output.rstrip("\n")))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Trailing spaces trimmed, as the repository's pre-commit hook requires.
    svg: str = "\n".join(line.rstrip() for line in console.export_svg(title=title).splitlines())
    path.write_text(svg + "\n", encoding="utf-8")
