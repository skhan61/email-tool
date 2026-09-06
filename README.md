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

### 2. Set your credentials
Put them in a machine-local secrets file. The server reads this file directly,
so it does not matter what the shell that launched Claude Code exported:

```bash
cat >> ~/.config/claude-secrets.env <<'EOF'
export ALCHLIGHT_MAIL_USER=you@alchlight.com
export ALCHLIGHT_MAIL_PASSWORD=your-mailbox-password
EOF
chmod 600 ~/.config/claude-secrets.env
```

**Do not commit them.** See `.env.example` for adding a second mailbox.

### 3. Add the marketplace and install
From Claude Code:

```
/plugin marketplace add <git-url-or-path-to-this-repo>
/plugin install email-tool@alchlight-tools
```

Or for a local checkout:

```
/plugin marketplace add ~/.claude/vendor/email-tool
/plugin install email-tool@alchlight-tools
```

Restart Claude Code (or reload plugins). Verify the MCP server connects with
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

- Credentials live **only** in `~/.config/claude-secrets.env` (mode 600),
  never in this repo and never in `.mcp.json`. The `.gitignore` blocks `.env`.
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

- **`/mcp` shows it failing to connect** → check the keys named by `--user-key`
  and `--password-key` in `.mcp.json` actually exist in
  `~/.config/claude-secrets.env`. The server logs the missing key to stderr and
  exits with status 2.
- **Auth errors** → verify host/port match your provider (Alchlight is HostGator
  `gator3272.hostgator.com`, IMAP 993 / SMTP 465, both TLS).
- **`self-signed certificate` on Gmail** → that was the old `imap-email-mcp`
  engine, which sent no TLS SNI. It is gone; see `mailbox_mcp/imap_session.py`.
