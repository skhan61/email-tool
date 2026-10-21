# Changelog

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
