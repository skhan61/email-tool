# Contributing

1. Open an issue first (bug report or feature request form).
2. Branch from `main` as `feat/<issue>-<slug>` or `fix/<issue>-<slug>`.
3. Set up once:
   ```bash
   uv sync
   uv run pre-commit install
   ```
4. Every function and variable is fully typed (`mypy --strict` runs on every commit).
5. Tests run offline: never against a real mailbox, never with a real password.
   ```bash
   uv run pytest
   ```
6. Open a PR with the template filled in, `Fixes #N` in the body. CI must be green,
   and `main` needs one approval from someone other than the PR's author.

The maintainer's own changes are opened by `skhan61-bot[bot]` (a GitHub App), so the
maintainer reviews and approves them like anyone else's; an approved PR with green
CI merges itself:
```bash
uv run python -m tools.bot_pr push --branch=feat/N-x
uv run python -m tools.bot_pr open_pr --branch=feat/N-x --title="..." --body_file=/path
uv run python -m tools.bot_pr ready --pr=N   # after the code review is posted
```

## Releasing

1. Bump the version in `pyproject.toml`, `manifest.json`, `.claude-plugin/plugin.json`,
   `.codex-plugin/plugin.json` and `.claude-plugin/marketplace.json` (`tests/test_manifests.py` fails if they differ), then `uv lock`.
   Add the version's section to `CHANGELOG.md`, including behaviour changes.
2. Merge, then tag `main` at once: `git tag vX.Y.Z && git push origin vX.Y.Z`
   (the Codex plugin points at that tag, so it must exist as soon as the bump lands).
3. The release workflow tests, builds the wheel, sdist and `.mcpb` bundle, and publishes a GitHub release.
