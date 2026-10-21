# Contributing

1. Open an issue first (bug report or feature request form).
2. Branch from `main` as `feat/<issue>-<slug>` or `fix/<issue>-<slug>`.
3. Set up once:
   ```bash
   uv sync
   .venv/bin/pre-commit install
   ```
4. Every function and variable is fully typed (`mypy --strict` runs on every commit).
5. Tests run offline: never against a real mailbox, never with a real password.
   ```bash
   uv run pytest
   ```
6. Open a PR with the template filled in, `Fixes #N` in the body. CI must be green.
