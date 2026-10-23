"""Prepare a release pull request: one new version everywhere, the CHANGELOG moved, the lock refreshed.

Standard: `uv version` writes and bumps the package version (uv's documented release step); the
manifests that must agree with it are updated through the `json` module.
Placement: tools/release/__init__.py, the package's public surface (`prepare`), as in tools/bot_pr.

Merging that pull request publishes the release: `.github/workflows/release.yml` runs on `main`,
sees a version with no tag yet, tags it and releases it (CONTRIBUTING.md, "Releasing").

LAYOUT
------
    _json_file.py  read a JSON file and write it back in the same layout it had
    _changelog.py  move the `## Unreleased` entries under the new version's heading
    _prepare.py    every place the version lives, `prepare`, and the pinned uv it runs
    __main__.py    `fire.Fire` over `prepare`, and nothing else
"""

from __future__ import annotations

from tools.release._prepare import ReleaseError, prepare

__all__: list[str] = ["ReleaseError", "prepare"]
