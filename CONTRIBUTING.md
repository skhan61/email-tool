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
6. Open a PR with the template filled in, `Fixes #N` in the body. CI must be green.

## Releasing

1. Bump the version in `pyproject.toml`, `manifest.json`, `.claude-plugin/plugin.json` and
   `.claude-plugin/marketplace.json` (`tests/test_versions.py` fails if they differ), then `uv lock`.
2. Merge, then tag `main`: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The release workflow tests, builds the wheel, sdist and `.mcpb` bundle, and publishes a GitHub release.
