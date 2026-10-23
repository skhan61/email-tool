# Security

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/skhan61/email-tool/security/advisories/new).
Do not open a public issue. Expect a reply within 7 days.

## What this tool protects

- Passwords are never stored in this repository, in agent config files, or on the command line.
- TLS certificate verification is always on for IMAP and SMTP and cannot be turned off.
- The server runs locally over stdio. It never listens on a network port; only `add --auth microsoft` and `add --auth google` listen on a localhost port until the browser sign-in finishes, at most 5 minutes (`--device-code` and `--paste-address` avoid it).

## Automatic first look at problem reports

A new issue labelled `user-report` gets one comment from `.github/workflows/first-look.yml`:
Claude's guess at the likely cause, with related code and related issues. Anyone can write a
report, so the report is handled as untrusted data:

- Claude can only read and search this repository and a copy of the report and earlier issues
  (Read, Grep and Glob), with system paths such as `/proc` and `.git` denied so it cannot read
  a token. It has no shell, cannot edit files, push, open pull requests or call GitHub, and its
  job's token is read-only.
- A separate job without Claude checks the answer and writes the comment: plain repository
  paths and issue numbers only, `@` mentions broken so nobody is pinged. That job can only
  write issue comments.
- At most 3 looks run per UTC day; a later report gets a short note that the maintainer will
  read it by hand. Without the `CLAUDE_CODE_OAUTH_TOKEN` repository secret, nothing runs.
- The comment is a guess and may be wrong. To run it again, delete the comment, then remove
  and add the label again.
