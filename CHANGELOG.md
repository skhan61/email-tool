# Changelog

## 5.2.1

### Security
- pypdf 6.21.1 (was 6.19.0) fixes 8 advisories in reading PDF attachments: infinite loops
  and runaway memory on crafted files.
- The bundle build tool (CI only) uses tmp 0.2.7 (was 0.0.33). node-forge has no fixed
  release for GHSA-86w9-cpqp-85rv; it is ignored for 3 months in
  `.github/tools/mcpb/osv-scanner.toml`, because the tool never verifies signatures.

### Fixed
- A message or attachment in a charset Python does not know (for example `charset=bogus`)
  no longer fails `get_email` or the CUI check; its text is read as UTF-8. Found by fuzzing.
- `email-tool-mcp --help` lists every command (`add`, `check`, `list`, `remove`, `serve`,
  `audit`, `policy`); it showed none.

### Added
- Fuzz tests (Atheris) for attachment text and message parsing, run in CI on pull requests
  and weekly.
- Documentation: every install step checked on a clean computer, with screenshots of the
  terminal, Gmail App Passwords, and the Microsoft and Google sign-in screens.

## 5.2.0

### Added
- Attachments. `send_email`, `create_draft` and `update_draft` attach any file the user asks
  for, from any folder, up to 25 MB per message. `get_email` lists attachments with their
  sizes, and `save_attachment` saves one into a folder the user names, under a safe name that
  never replaces an existing file.
- Files that look sensitive (private keys, `.env` files, cloud credentials, password
  databases, files with CUI markings) make the app ask the user before sending, even when
  `require_approval` is off. The user decides. Without a prompt, the assistant needs the
  user's confirmation in the conversation and resends with `confirm_sensitive`.
- `cui_recipient_domains` also reads text, CSV, Markdown, HTML, Word and PDF attachments.
- The audit log records each attachment's name, size and SHA-256 fingerprint.
- Microsoft sign-in without a browser: the terminal prints the sign-in address and takes back
  the address the browser ends on, and `--paste-address` works for Microsoft as for Google.
- A pull request that changes the release workflow runs it as a dry run.
- Replies join their conversation: `create_draft`, `update_draft` and `send_email` take
  `in_reply_to_uid` (and `in_reply_to_folder`, default `INBOX`) and set `In-Reply-To` and
  `References` from that message. Only well-formed message IDs are copied from it, and the
  approval question shows the message being answered.

### Changed
- New runtime dependency: pypdf 6.19.0, to read PDF attachments for the CUI check.

## 5.1.0

Documentation: https://skhan61.github.io/email-tool/

### Added
- Microsoft sign-in for Outlook.com, Microsoft 365 and GCC High:
  `email-tool-mcp add <name> --auth microsoft --address you@company.com`. The project's
  own app is the default; `--client-id` uses an organization's app and `--tenant` pins
  its directory. GCC High: `--cloud gcc-high --client-id <app registered in GCC High>`.
  `--device-code` signs in without a browser.
- Google sign-in for Google Workspace accounts without App Passwords:
  `email-tool-mcp add <name> --auth google --address you@company.com --client-secrets <file>`,
  with `--paste-address` when the browser is on another computer.
- No password is stored for either: the sign-in is kept encrypted (key in the OS keyring)
  and renews itself. Sign-in traffic uses the same TLS 1.2 floor and 60 s timeout as mail,
  through an HTTPS proxy too. A browser sign-in gives up after 5 minutes.
- Token login (SASL XOAUTH2) for IMAP and SMTP.
- `require_fips` also covers kept sign-ins: a Microsoft or Google mailbox is refused,
  before its sign-in is read, unless the `cryptography` package runs on a FIPS provider.
  `check` reports it.
- A documentation website: install for every app, every account type step by step,
  why CMMC with examples, administration and troubleshooting.
- Release files are signed with Sigstore (`*.sigstore.json`) and carry SLSA build
  provenance (`*.intoto.jsonl`).

### Changed
- The project contact and package maintainer is sayem.eee.kuet@gmail.com.
- Runtime dependencies: pydantic 2.14.0, platformdirs 4.12.4, and `requests` 2.34.2
  pinned directly (sign-in traffic uses it).

### Fixed
- A tool call whose text holds a broken Unicode character (an unpaired surrogate) is
  refused by argument name instead of failing with a raw error, and is still audited.
- A recipient list of a lone quote no longer crashes on Python 3.11 and 3.12.

### Behavior changes when upgrading from 5.0
- SMTP on port 25 or 587 now upgrades with STARTTLS; every other port stays direct TLS.
- `add` refuses options that do not apply to its `--auth`.
- Adding a mailbox again with another kind of login deletes the old password or sign-in.
- Settings files with Microsoft or Google mailboxes cannot be read by 5.0 or earlier.
- A browser sign-in listens on a localhost port until it finishes.
- `email-tool-mcp list` applies the policy, so `require_fips` can refuse to read a sign-in.

## 5.0.0

Controls for using email with AI agents in CMMC Level 2 environments; see
[docs/cmmc.md](docs/cmmc.md) for the NIST SP 800-171 mapping.

### Added
- Tamper-evident audit log of every agent action (`email-tool-mcp audit path|verify`),
  HMAC-chained with a key in the OS keyring, optional syslog copy.
- Policy files (administrator and user): `read_only`, `allowed_tools`,
  `allowed_recipient_domains`, `allow_environment_mailbox`; rules keyed by mailbox
  name or address (`email-tool-mcp policy paths|show`).
- `require_approval`: send, delete and draft replacement wait for your yes in the
  app's own prompt, showing the delivered recipients and the whole message.
- `cui_recipient_domains`: mail carrying a CUI marking goes only to approved domains.
- `require_fips` and `email-tool-mcp check <mailbox>` (negotiated TLS, cipher, FIPS state).
- ChatGPT desktop / Codex plugin; icon; README badges.

### Behaviour changes when upgrading from 4.x
- TLS 1.2 is the minimum: a mail server offering only TLS 1.0 or 1.1 is refused.
- A mailbox described by an app's `EMAIL_TOOL_*` settings no longer replaces an
  enrolled mailbox of the same name.
- With a policy file present, calls it forbids are refused and recorded; with none,
  behaviour is as before.
- Message-ID now uses the sender's domain instead of this computer's name.

### Not yet
- Microsoft 365 / Outlook and Google Workspace sign-in (OAuth): planned for 5.1.

## 4.0.0

Installable MCP server for any agent; passwords in the OS keyring; Claude Desktop
bundle; Claude Code plugin rebuilt on it.

## 3.1.0

Last Claude Code-only plugin with its own standard-library server.
