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
maintainer reviews and approves them like anyone else's. Two gates (`gates.yml`) fail
a PR the maintainer opened himself and a PR with no review starting `## Code review`.
`ready` turns on auto-merge, so an approved PR with green CI merges itself:
```bash
uv run python -m tools.bot_pr push --branch=feat/N-x
uv run python -m tools.bot_pr open_pr --branch=feat/N-x --title="..." --body_file=/path
uv run python -m tools.bot_pr ready --pr=N   # after the code review is posted
```

## Documentation

The site lives in `docs/` (MkDocs Material, configured in `mkdocs.yml`) and is published
from `main`. Preview it while you edit:

```bash
uv run --group docs mkdocs serve
```

Pull requests build it with `--strict`, so a broken link fails the check.

## Live tests

`tests/` runs offline against a fake mail server. `tests/live` runs the same tools against
real mailboxes on this computer (settings, keyring and sign-ins), so it finds what only a real
server shows. It is skipped unless `EMAIL_TOOL_LIVE=1`, never runs in CI, and no real
password leaves the computer. It sends one mailbox's messages to another, each with a unique
code in the subject, and deletes them afterwards; junk or spam filing is reported as a warning.

```bash
EMAIL_TOOL_LIVE=1 uv run pytest tests/live -q
# other mailboxes than gmail -> outlook:
EMAIL_TOOL_LIVE=1 EMAIL_TOOL_LIVE_FROM=work EMAIL_TOOL_LIVE_TO=home uv run pytest tests/live -q
```

Weekly on Linux, with a systemd user timer (`tools/live-timer/`): set `WorkingDirectory` in
`email-tool-live.service` to your checkout, then

```bash
mkdir -p ~/.config/systemd/user ~/.local/state/email-tool
cp tools/live-timer/* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now email-tool-live.timer
```

A failed run shows a desktop notification; the log is `~/.local/state/email-tool/live.log`.

## Releasing

A pull request that changes `.github/workflows/release.yml` runs it as a dry run (build and
pack, no signing or publishing), so a workflow error fails the pull request, not the release.

Before step 1, run the live tests on the maintainer's computer; release only when they pass.

1. Bump the version in `pyproject.toml`, `manifest.json`, `.claude-plugin/plugin.json`,
   `.codex-plugin/plugin.json`, `.claude-plugin/marketplace.json` and the `@vX.Y.Z` pin in
   `.codex-mcp.json` (`tests/test_manifests.py` fails if they differ), then `uv lock` with the
   uv version CI uses.
   Add the version's section to `CHANGELOG.md`, including behaviour changes.
2. Merge, then tag `main` at once: `git tag vX.Y.Z && git push origin vX.Y.Z`
   (the Codex plugin points at that tag, so it must exist as soon as the bump lands).
3. The release workflow tests, builds the wheel, sdist and `.mcpb` bundle, signs each with
   Sigstore (`*.sigstore.json`), adds SLSA build provenance (`*.intoto.jsonl`) and publishes a
   GitHub release. With the repository variable `PYPI_PUBLISH` set to `true` (after the PyPI
   trusted publisher exists, #31), it also publishes the wheel and sdist to PyPI.
   Verify a download (X.Y.Z the version): it must be signed by release.yml on that tag:
   ```bash
   uvx sigstore==4.5.0 verify identity <file> \
     --cert-identity https://github.com/skhan61/email-tool/.github/workflows/release.yml@refs/tags/vX.Y.Z \
     --cert-oidc-issuer https://token.actions.githubusercontent.com
   ```

## OpenSSF Scorecard token

Scorecard needs to read branch protection, which the workflow's own token cannot.
Once a year: GitHub > Settings > Developer settings > Fine-grained tokens > Generate:
repository access "Only select repositories" > email-tool; permissions
"Administration: Read-only" (Metadata read-only is added by GitHub); expiry one year.
Then store it without it ever being shown:
```bash
gh secret set SCORECARD_TOKEN --repo skhan61/email-tool
```
