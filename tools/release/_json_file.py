"""A JSON file read with the json module and written back in the layout it already had.

Standard: the standard library's `json` (parse and serialize), no text edits of JSON.
Placement: tools/release/_json_file.py, used only by `_prepare.py`.

The manifests use two layouts: two-space indentation throughout (`json.dumps(indent=2)`), and the
same with each list of plain values on one line (`.codex-plugin/plugin.json`). A file that neither
reproduces byte for byte is refused, so a rewrite never reformats a file it does not understand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None

_INDENT: Final[str] = "  "


class LayoutError(ValueError):
    """The file's layout is not one this module writes back unchanged."""


@dataclass
class JsonFile:
    """One parsed JSON file and how to write it back."""

    path: Path
    data: Json
    inline_scalar_lists: bool
    final_newline: bool


def _render(value: Json, inline_scalar_lists: bool, depth: int) -> str:
    inner: str = _INDENT * (depth + 1)
    outer: str = _INDENT * depth
    if isinstance(value, dict):
        if not value:
            return "{}"
        members: list[str] = [
            f"{inner}{json.dumps(key, ensure_ascii=False)}: {_render(item, inline_scalar_lists, depth + 1)}"
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(members) + "\n" + outer + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if inline_scalar_lists and not any(isinstance(item, dict | list) for item in value):
            return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
        elements: list[str] = [inner + _render(item, inline_scalar_lists, depth + 1) for item in value]
        return "[\n" + ",\n".join(elements) + "\n" + outer + "]"
    return json.dumps(value, ensure_ascii=False)


def render(file: JsonFile) -> str:
    """The file's text for its current data, in its own layout."""
    return _render(file.data, file.inline_scalar_lists, 0) + ("\n" if file.final_newline else "")


def load(path: Path) -> JsonFile:
    """Parse `path` and find the layout that writes it back unchanged; raise `LayoutError` if none does."""
    text: str = path.read_text(encoding="utf-8")
    data: Json = json.loads(text)
    inline: bool
    for inline in (False, True):
        candidate: JsonFile = JsonFile(path, data, inline, text.endswith("\n"))
        if render(candidate) == text:
            return candidate
    raise LayoutError(
        f"{path} is laid out in a way this tool does not write back unchanged; "
        "format it with two-space indentation (as `json.dumps(indent=2)` does) and try again"
    )


def save(file: JsonFile) -> None:
    """Write the file's data back in its own layout."""
    file.path.write_text(render(file), encoding="utf-8")
