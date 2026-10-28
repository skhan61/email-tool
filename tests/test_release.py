"""`tools.release prepare`: the new version in every place it lives, the CHANGELOG released.

Standard: pytest with `tmp_path`, on a copy of the repository's own version files.
Placement: tests/test_release.py, beside tests/test_bot_pr.py, the other tools/ package's tests.

Offline: uv runs as `uv --offline` on the copy (`uv version` reads and writes only pyproject.toml);
`uv lock`, which resolves against PyPI, is recorded instead of run.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests import test_manifests
from tools.release import ReleaseError, _changelog, _json_file, _prepare
from tools.release._prepare import LOCATIONS, Location

ROOT: Path = Path(__file__).resolve().parent.parent
COPIED: tuple[str, ...] = (
    "pyproject.toml",
    "CHANGELOG.md",
    "README.md",
    "uv.lock",
    *sorted({location.file for location in LOCATIONS}),
)
ENTRY: str = "### Added\n- Something new, for the test."


class FakeUv:
    """Runs uv offline on the copy; records `uv lock` (which needs PyPI) and marks uv.lock instead."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, arguments: Sequence[str], root: Path) -> str:
        self.calls.append(list(arguments))
        if list(arguments) == ["lock"]:
            with (root / "uv.lock").open("a", encoding="utf-8") as lock:
                lock.write("# relocked\n")
            return ""
        uv: str | None = shutil.which("uv")
        assert uv is not None, "uv must be on PATH (the suite runs under `uv run`)"
        finished: subprocess.CompletedProcess[str] = subprocess.run(
            [uv, "--offline", *arguments], cwd=root, capture_output=True, text=True, check=True
        )
        return finished.stdout


def version_of(root: Path) -> str:
    version: str = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    return version


def bumped(version: str, part: str) -> str:
    major: int
    minor: int
    patch: int
    major, minor, patch = (int(number) for number in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """The repository's version files, with one entry under `## Unreleased`."""
    name: str
    for name in COPIED:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    changelog: Path = tmp_path / "CHANGELOG.md"
    text: str = changelog.read_text(encoding="utf-8")
    lines: list[str] = text.split("\n")
    start: int = lines.index(_changelog.UNRELEASED) + 1
    end: int = next(index for index in range(start, len(lines)) if lines[index].startswith("## "))
    changelog.write_text("\n".join([*lines[:start], "", ENTRY, "", *lines[end:]]), encoding="utf-8")
    return tmp_path


def value_at(root: Path, location: Location) -> _json_file.Json:
    value: _json_file.Json = _json_file.load(root / location.file).data
    key: str | int
    for key in location.keys:
        if isinstance(value, dict) and isinstance(key, str):
            value = value[key]
        elif isinstance(value, list) and isinstance(key, int):
            value = value[key]
    return value


@pytest.mark.parametrize("part", ["patch", "minor", "major"])
def test_every_version_location_gets_the_next_version(checkout: Path, part: str) -> None:
    old: str = version_of(checkout)
    new: str = bumped(old, part)
    _prepare.prepare_with(part, checkout, FakeUv())
    assert version_of(checkout) == new
    location: Location
    for location in LOCATIONS:
        assert value_at(checkout, location) == location.prefix + new, location


def test_the_manifest_tests_pass_on_the_result(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare.prepare_with("minor", checkout, FakeUv())
    monkeypatch.setattr(test_manifests, "ROOT", checkout)
    relative: str
    path: tuple[str, ...]
    for relative, path in [
        ("manifest.json", ("version",)),
        (".claude-plugin/plugin.json", ("version",)),
        (".codex-plugin/plugin.json", ("version",)),
        (".claude-plugin/marketplace.json", ("metadata", "version")),
    ]:
        test_manifests.test_manifest_version_matches_the_package(relative, path)
    test_manifests.test_registry_entry_names_this_release_and_the_readme_proves_it()
    test_manifests.test_codex_plugin_runs_the_release_matching_its_version()


def test_only_the_version_lines_change_and_each_file_keeps_its_layout(checkout: Path) -> None:
    files: list[str] = sorted({location.file for location in LOCATIONS})
    before: dict[str, list[str]] = {name: (checkout / name).read_text(encoding="utf-8").split("\n") for name in files}
    _prepare.prepare_with("patch", checkout, FakeUv())
    name: str
    for name in files:
        after: list[str] = (checkout / name).read_text(encoding="utf-8").split("\n")
        assert len(after) == len(before[name]), name
        changed: int = sum(1 for old, new in zip(before[name], after, strict=True) if old != new)
        assert changed == sum(1 for location in LOCATIONS if location.file == name), name


def test_the_unreleased_entries_move_under_the_new_version(checkout: Path) -> None:
    old: str = version_of(checkout)
    original: str = (checkout / "CHANGELOG.md").read_text(encoding="utf-8")
    _prepare.prepare_with("patch", checkout, FakeUv())
    new: str = bumped(old, "patch")
    text: str = (checkout / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## Unreleased\n\n## {new}\n\n{ENTRY}\n\n## {old}\n" in text
    assert text.replace(f"## {new}\n\n", "", 1) == original


def test_the_release_notes_job_reads_the_new_section(checkout: Path) -> None:
    """release.yml's awk takes the lines under `## X.Y.Z` up to the next `## ` heading."""
    _prepare.prepare_with("patch", checkout, FakeUv())
    notes: subprocess.CompletedProcess[str] = subprocess.run(
        ["awk", "-v", f"v=## {version_of(checkout)}", "$0==v{f=1;next} /^## /{f=0} f", "CHANGELOG.md"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    )
    assert notes.stdout.strip() == ENTRY


def test_an_empty_unreleased_section_is_refused_and_nothing_changes(checkout: Path) -> None:
    shutil.copyfile(ROOT / "CHANGELOG.md", checkout / "CHANGELOG.md")
    changelog: Path = checkout / "CHANGELOG.md"
    lines: list[str] = changelog.read_text(encoding="utf-8").split("\n")
    start: int = lines.index(_changelog.UNRELEASED) + 1
    end: int = next(index for index in range(start, len(lines)) if lines[index].startswith("## "))
    changelog.write_text("\n".join([*lines[:start], "", *lines[end:]]), encoding="utf-8")
    before: dict[str, bytes] = {name: (checkout / name).read_bytes() for name in COPIED}
    uv: FakeUv = FakeUv()
    with pytest.raises(ReleaseError, match="nothing under `## Unreleased`"):
        _prepare.prepare_with("patch", checkout, uv)
    assert {name: (checkout / name).read_bytes() for name in COPIED} == before
    assert ["lock"] not in uv.calls


def test_a_manifest_out_of_step_is_refused_and_nothing_changes(checkout: Path) -> None:
    server: Path = checkout / "server.json"
    server.write_text(server.read_text(encoding="utf-8").replace(version_of(checkout), "0.0.1", 1), encoding="utf-8")
    before: dict[str, bytes] = {name: (checkout / name).read_bytes() for name in COPIED}
    with pytest.raises(ReleaseError, match="server.json"):
        _prepare.prepare_with("patch", checkout, FakeUv())
    assert {name: (checkout / name).read_bytes() for name in COPIED} == before


def test_an_unknown_part_is_refused(checkout: Path) -> None:
    uv: FakeUv = FakeUv()
    with pytest.raises(ReleaseError, match="--part must be one of"):
        _prepare.prepare_with("prerelease", checkout, uv)
    assert uv.calls == []


def test_uv_writes_the_version_and_the_lock_comes_last(checkout: Path) -> None:
    uv: FakeUv = FakeUv()
    _prepare.prepare_with("patch", checkout, uv)
    new: str = version_of(checkout)
    assert uv.calls == [["version", "--bump", "patch", "--dry-run", "--short"], ["version", new, "--frozen"], ["lock"]]


class FailingLock(FakeUv):
    """`uv lock` fails, as it does without the network."""

    def __call__(self, arguments: Sequence[str], root: Path) -> str:
        if list(arguments) == ["lock"]:
            raise ReleaseError("`uv lock` failed: no network")
        return super().__call__(arguments, root)


def test_a_failed_lock_puts_every_file_back(checkout: Path) -> None:
    before: dict[str, bytes] = {name: (checkout / name).read_bytes() for name in COPIED}
    with pytest.raises(ReleaseError, match="uv lock"):
        _prepare.prepare_with("patch", checkout, FailingLock())
    assert {name: (checkout / name).read_bytes() for name in COPIED} == before


def test_a_pyproject_without_a_version_is_refused_plainly(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 120\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="cannot read the \\[project\\] version"):
        _prepare.prepare_with("patch", tmp_path, FakeUv())


def test_every_tracked_file_that_carries_the_version_is_one_prepare_updates() -> None:
    """A new manifest that carries the version must be added to LOCATIONS, or this fails."""
    # .github/tools pins third-party CI tools, whose versions can equal ours by chance
    # (pretty-bytes 5.6.0 in the bundle tool's lockfile).
    listed: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "ls-files", "*.json", "*.toml", "*.yml", "*.yaml", ":(exclude).github/tools/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    version: str = version_of(ROOT)
    texts: dict[str, str] = {name: (ROOT / name).read_text(encoding="utf-8") for name in listed.stdout.split()}
    carrying: set[str] = {name for name, text in texts.items() if f'"{version}"' in text or f"=={version}" in text}
    assert carrying == {"pyproject.toml", *(location.file for location in LOCATIONS)}


def test_the_report_names_every_changed_file(checkout: Path) -> None:
    report: str = _prepare.prepare_with("patch", checkout, FakeUv())
    assert report.split("\n")[1:] == [
        "pyproject.toml",
        *dict.fromkeys(location.file for location in LOCATIONS),
        "CHANGELOG.md",
        "uv.lock",
    ]


def test_a_json_layout_it_cannot_reproduce_is_refused(tmp_path: Path) -> None:
    odd: Path = tmp_path / "odd.json"
    odd.write_text('{\n    "version": "1.0.0"\n}\n', encoding="utf-8")
    with pytest.raises(_json_file.LayoutError, match="two-space indentation"):
        _json_file.load(odd)


@pytest.mark.parametrize("name", sorted({location.file for location in LOCATIONS}))
def test_every_manifest_is_written_back_byte_for_byte(name: str, tmp_path: Path) -> None:
    copy: Path = tmp_path / "copy.json"
    shutil.copyfile(ROOT / name, copy)
    _json_file.save(_json_file.load(copy))
    assert copy.read_bytes() == (ROOT / name).read_bytes()
