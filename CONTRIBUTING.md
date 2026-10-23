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

## Releasing

Merging a release pull request publishes the release. A pull request that changes
`.github/workflows/release.yml` runs it as a dry run (build and pack, no tag, signing or
publishing), so a workflow error fails the pull request, not the release.
Run the live tests on the maintainer's computer first; release only when they pass.

1. On a branch from `main`, prepare the release and open its pull request:
   ```bash
   uv run python -m tools.release prepare --part=patch   # or minor, major
   git commit -am "Release X.Y.Z"
   uv run python -m tools.bot_pr push --branch=release/X.Y.Z
   uv run python -m tools.bot_pr open_pr --branch=release/X.Y.Z --title="Release X.Y.Z" --body_file=/path
   ```
   `prepare` sets the next version in every file that carries it (`tests/test_manifests.py`
   checks they agree), moves the `## Unreleased` entries of `CHANGELOG.md` under `## X.Y.Z`
   (it refuses when there are none) and relocks with uv 0.13.5. If anything fails, it puts
   every file back.
2. Merge it. `release.yml` runs on `main`, finds no tag `vX.Y.Z`, tags the merge and, in the
   same run, tests, builds the wheel, sdist and `.mcpb` bundle, signs each with Sigstore
   (`*.sigstore.json`), adds SLSA build provenance (`*.intoto.jsonl`) and publishes a GitHub
   release, then the wheel and sdist to PyPI by trusted publishing and `server.json` to the
   official MCP Registry (both only with the repository variable `PYPI_PUBLISH` set to `true`).
   A merge that keeps the version releases nothing. Codex installs the new version from PyPI
   and fails until the `pypi` job succeeds: check https://pypi.org/project/email-tool-mcp/
   after the run. If a job fails, re-run that run's failed jobs. If a fix must reach `main` first,
   delete the tag after it merges and push it again by hand:
   `git push origin :refs/tags/vX.Y.Z`, then `git tag vX.Y.Z && git push origin vX.Y.Z` on `main`.
   A hand-pushed tag releases a version the same way.
3. Verify a download: it must be signed by release.yml on `main`, at the commit tagged `vX.Y.Z`
   (every release from `main` has the same identity; the commit ties it to one version):
   ```bash
   sha="$(git ls-remote https://github.com/skhan61/email-tool refs/tags/vX.Y.Z | cut -f1)"
   uvx sigstore==4.5.0 verify github <file> --sha "$sha" \
     --cert-identity https://github.com/skhan61/email-tool/.github/workflows/release.yml@refs/heads/main
   ```
   Releases up to 5.4.4, and a release made by pushing its tag by hand, are signed on the tag:
   end the identity with `release.yml@refs/tags/vX.Y.Z` instead.

## OpenSSF Scorecard token

Scorecard needs to read branch protection, which the workflow's own token cannot.
Once a year: GitHub > Settings > Developer settings > Fine-grained tokens > Generate:
repository access "Only select repositories" > email-tool; permissions
"Administration: Read-only" (Metadata read-only is added by GitHub); expiry one year.
Then store it without it ever being shown:
```bash
gh secret set SCORECARD_TOKEN --repo skhan61/email-tool
```
