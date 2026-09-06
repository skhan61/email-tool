# email-tool

A Claude Code **plugin** that gives Claude access to your email mailbox over
IMAP/SMTP, read, search, draft, and send mail from inside a session.

It ships its own dependency-free MCP server (`mailbox_mcp/`, Python standard
library only) and adds reusable email workflows (a skill) and slash commands.

> **Each person uses their own mailbox.** This plugin ships *no credentials*.
> You supply your own IMAP/SMTP login via a machine-local secrets file.

---

## What you get

| Type | Name | What it does |
|------|------|--------------|
| MCP server | `alchlight` | IMAP/SMTP tools for the Alchlight work mailbox |
| MCP server | `gmail` | IMAP/SMTP tools for the personal Gmail mailbox |
| Skill | `email-tool` | Email triage / reply / compose workflows with safety rules |
| Command | `/inbox` | Summarize recent inbox messages |
| Command | `/email-search` | Search the mailbox |
| Command | `/email-send` | Draft + send (with confirmation) |

---

## Install

### 1. Prerequisites
- **Python 3.10+** on PATH. There are no third-party packages to install.
- Your mailbox **IMAP/SMTP credentials** (for HostGator-hosted Alchlight mail,
  that's your full email address + mailbox password).

### 2. Install it
```
/plugin marketplace add <git-url-or-path-to-this-repo>
/plugin install email-tool@email-tool
```

Claude Code then **asks you for each mailbox's address and password**. Password
fields are masked as you type and stored in secure storage (the macOS Keychain,
or `~/.claude/.credentials.json`), never in `settings.json` and never in this
repository.

**Leave a mailbox blank to keep it off this machine.** That server logs one line
and exits quietly. This is how one machine runs Alchlight only while another
runs both, with no per-machine config file and nothing to sync.

To change or add credentials later, run `/plugin` and edit the plugin's
configuration.

Gmail needs a Google App Password, not your account password.

### 3. Verify
Restart Claude Code (or reload plugins). Check the servers connect with
`/mcp`, you should see `email-tool` listed.

---

## Usage

- `/inbox`, recent mail at a glance
- `/email-search from:jane invoice`, find messages
- `/email-send reply to the last message from Jane confirming the meeting`
- Or just ask naturally: *"check my inbox", "find the email about the contract",
  "draft a reply to Bob"*. The skill activates automatically.

The skill **always drafts and asks before sending or deleting**, nothing leaves
your mailbox without your explicit confirmation.

---

## Security notes

- Credentials are entered once at install, masked, and held by Claude Code in
  secure storage. They are never in this repo, never in `.mcp.json`, never in
  `settings.json`, and never passed as command-line arguments, so they cannot
  appear in a process listing.
- TLS certificates are **always** verified, and there is no option to disable
  verification. The server sends SNI, which is required by Gmail and by any
  other host that serves more than one domain.
- The MCP server talks directly to your mail host over TLS; mail contents are
  visible to Claude during a session, treat them as you would any data you
  share with an assistant.
- Use a dedicated mailbox password / app password where your provider supports
  it, rather than your primary account password.

---

## Troubleshooting

- **A mailbox is missing from `/mcp`** - its fields were left blank at install.
  Run `/plugin`, edit the plugin config, fill them in, restart.
- **Auth errors** → verify host/port match your provider (Alchlight is HostGator
  `gator3272.hostgator.com`, IMAP 993 / SMTP 465, both TLS).
- **`self-signed certificate` on Gmail** → that was the old `imap-email-mcp`
  engine, which sent no TLS SNI. It is gone; see `mailbox_mcp/imap_session.py`.
