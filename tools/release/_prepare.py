"""`prepare`: the next version in every place it lives, the CHANGELOG released, `uv.lock` refreshed.

Standard: `uv version --bump` computes the next version and `uv version X.Y.Z` writes it to
pyproject.toml (uv's documented way to set a project's version); `uv lock` records it in uv.lock.
Placement: tools/release/_prepare.py, the package's logic; `__main__.py` only parses arguments.

Everything is checked before anything is written: every manifest must carry the current version
and the CHANGELOG must have entries to release, so a refusal leaves the checkout untouched.
"""

from __future__ import annotations

import logging
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.release import _changelog, _json_file
from tools.release._json_file import Json, JsonFile

log: Final[logging.Logger] = logging.getLogger(__name__)

# The uv that CI uses; CONTRIBUTING.md and this tool lock with the same one.
PINNED_UV: Final[tuple[str, ...]] = ("uvx", "uv@0.13.5")
PARTS: Final[tuple[str, ...]] = ("patch", "minor", "major")
PYPROJECT: Final[str] = "pyproject.toml"
CHANGELOG: Final[str] = "CHANGELOG.md"
LOCK: Final[str] = "uv.lock"

# Runs uv with these arguments in this folder and returns its standard output.
Uv = Callable[[Sequence[str], Path], str]


class ReleaseError(RuntimeError):
    """The release cannot be prepared; nothing was changed."""


@dataclass(frozen=True)
class Location:
    """One place a manifest carries the version: the keys down to it, and the text before the version."""

    file: str
    keys: tuple[str | int, ...]
    prefix: str = ""


# Every version besides pyproject.toml's; tests/test_manifests.py checks they agree with it.
LOCATIONS: Final[tuple[Location, ...]] = (
    Location("manifest.json", ("version",)),
    Location(".claude-plugin/plugin.json", ("version",)),
    Location(".codex-plugin/plugin.json", ("version",)),
    Location(".claude-plugin/marketplace.json", ("metadata", "version")),
    Location("server.json", ("version",)),
    Location("server.json", ("packages", 0, "version")),
    Location(".codex-mcp.json", ("mcpServers", "email", "args", 1), "email-tool-mcp=="),
)


def pinned_uv(arguments: Sequence[str], root: Path) -> str:
    """Run the pinned uv in `root`; raise `ReleaseError` with its output when it fails."""
    finished: subprocess.CompletedProcess[str] = subprocess.run(
        [*PINNED_UV, *arguments], cwd=root, capture_output=True, text=True, check=False
    )
    if finished.returncode != 0:
        raise ReleaseError(f"`uv {' '.join(arguments)}` failed:\n{finished.stderr}")
    return finished.stdout


def _current_version(root: Path) -> str:
    project: dict[str, object] = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))["project"]
    version: object = project["version"]
    if not isinstance(version, str):
        raise ReleaseError(f"{PYPROJECT} has no [project] version")
    return version


def _container(data: Json, location: Location) -> dict[str, Json] | list[Json]:
    """The dict or list that holds the version at `location`."""
    node: Json = data
    key: str | int
    for key in location.keys[:-1]:
        if isinstance(node, dict) and isinstance(key, str) and key in node:
            node = node[key]
        elif isinstance(node, list) and isinstance(key, int) and key < len(node):
            node = node[key]
        else:
            raise ReleaseError(f"{location.file} has nothing at {location.keys}")
    if not isinstance(node, dict | list):
        raise ReleaseError(f"{location.file} has nothing at {location.keys}")
    return node


def _get(data: Json, location: Location) -> Json:
    holder: dict[str, Json] | list[Json] = _container(data, location)
    last: str | int = location.keys[-1]
    if isinstance(holder, dict) and isinstance(last, str) and last in holder:
        return holder[last]
    if isinstance(holder, list) and isinstance(last, int) and last < len(holder):
        return holder[last]
    raise ReleaseError(f"{location.file} has nothing at {location.keys}")


def _set(data: Json, location: Location, value: str) -> None:
    holder: dict[str, Json] | list[Json] = _container(data, location)
    last: str | int = location.keys[-1]
    if isinstance(holder, dict) and isinstance(last, str):
        holder[last] = value
    elif isinstance(holder, list) and isinstance(last, int):
        holder[last] = value


def _load_manifests(root: Path, current: str) -> dict[str, JsonFile]:
    """Every manifest, parsed; raise `ReleaseError` when one is missing, unreadable or not at `current`."""
    manifests: dict[str, JsonFile] = {}
    location: Location
    for location in LOCATIONS:
        if location.file not in manifests:
            try:
                manifests[location.file] = _json_file.load(root / location.file)
            except (OSError, ValueError) as error:
                raise ReleaseError(f"cannot read {location.file}: {error}") from error
        found: Json = _get(manifests[location.file].data, location)
        if found != location.prefix + current:
            raise ReleaseError(
                f"{location.file} {location.keys} is {found!r}, not {location.prefix + current!r} as "
                f"{PYPROJECT} says; make them agree (tests/test_manifests.py) before releasing"
            )
    return manifests


def _snapshot(root: Path, names: Sequence[str]) -> dict[str, bytes]:
    return {name: (root / name).read_bytes() if (root / name).is_file() else b"" for name in names}


def prepare(part: str, root: str = ".") -> str:
    """Bump the version by `part` (patch, minor or major) everywhere it lives, move the CHANGELOG's
    Unreleased entries under it and relock with the pinned uv; return the files that changed.

    Then commit, push and open the pull request with `tools.bot_pr`; merging it publishes the release.
    """
    return prepare_with(part, Path(root), pinned_uv)


def prepare_with(part: str, root: Path, uv: Uv) -> str:
    """`prepare`, running uv through `uv` (the tests run it without the network)."""
    if part not in PARTS:
        raise ReleaseError(f"--part must be one of {', '.join(PARTS)}, not {part!r}")
    checkout: Path = root.resolve()
    current: str = _current_version(checkout)
    version: str = uv(["version", "--bump", part, "--dry-run", "--short"], checkout).strip()
    manifests: dict[str, JsonFile] = _load_manifests(checkout, current)
    try:
        notes: str = _changelog.release((checkout / CHANGELOG).read_text(encoding="utf-8"), version)
    except _changelog.ChangelogError as error:
        raise ReleaseError(str(error)) from error

    names: list[str] = [PYPROJECT, *manifests, CHANGELOG, LOCK]
    before: dict[str, bytes] = _snapshot(checkout, names)
    # Without re-locking here: the lock below is the pinned uv's, with nothing else in between.
    uv(["version", version, "--frozen"], checkout)
    location: Location
    for location in LOCATIONS:
        _set(manifests[location.file].data, location, location.prefix + version)
    manifest: JsonFile
    for manifest in manifests.values():
        _json_file.save(manifest)
    (checkout / CHANGELOG).write_text(notes, encoding="utf-8")
    uv(["lock"], checkout)
    if _current_version(checkout) != version:
        raise ReleaseError(f"{PYPROJECT} does not say {version} after `uv version`")

    after: dict[str, bytes] = _snapshot(checkout, names)
    changed: list[str] = [name for name in names if before[name] != after[name]]
    log.info("%s -> %s", current, version)
    return "\n".join([f"{current} -> {version}; changed:", *changed])
