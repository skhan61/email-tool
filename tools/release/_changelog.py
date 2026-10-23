"""Move CHANGELOG.md's `## Unreleased` entries under a new `## X.Y.Z` heading.

Standard: Keep a Changelog's "Unreleased" section, released by renaming it to the version.
Placement: tools/release/_changelog.py, used only by `_prepare.py`.

`## Unreleased` stays, empty, above the new section, ready for the next change. The release
notes are this section: release.yml copies the text under `## X.Y.Z` into the GitHub release.
"""

from __future__ import annotations

from typing import Final

UNRELEASED: Final[str] = "## Unreleased"


class ChangelogError(ValueError):
    """The CHANGELOG cannot be released as it is."""


def release(text: str, version: str) -> str:
    """`text` with the Unreleased entries under `## <version>`; raise `ChangelogError` when there are none."""
    lines: list[str] = text.split("\n")
    if UNRELEASED not in lines:
        raise ChangelogError(f"CHANGELOG.md has no `{UNRELEASED}` heading")
    if f"## {version}" in lines:
        raise ChangelogError(f"CHANGELOG.md already has a `## {version}` section")
    start: int = lines.index(UNRELEASED) + 1
    end: int = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))
    entries: list[str] = lines[start:end]
    while entries and not entries[0].strip():
        entries.pop(0)
    while entries and not entries[-1].strip():
        entries.pop()
    if not entries:
        raise ChangelogError(
            f"CHANGELOG.md has nothing under `{UNRELEASED}`: add this release's changes there, then run again"
        )
    released: list[str] = [*lines[:start], "", f"## {version}", "", *entries, ""]
    return "\n".join([*released, *lines[end:]])
