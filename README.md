# alchlight-email

A Claude Code **plugin** that gives Claude access to your email mailbox over
IMAP/SMTP — read, search, draft, and send mail from inside a session.

It wraps the public [`imap-email-mcp`](https://www.npmjs.com/package/imap-email-mcp)
MCP server and adds reusable email workflows (a skill) and slash commands.

> **Each person uses their own mailbox.** This plugin ships *no credentials*.
> You supply your own IMAP/SMTP login via environment variables.

---

## What you get

| Type | Name | What it does |
|------|------|--------------|
| MCP server | `alchlight-email` | IMAP/SMTP tools: list, search, read, draft, send, delete |
| Skill | `alchlight-email` | Email triage / reply / compose workflows with safety rules |
| Command | `/inbox` | Summarize recent inbox messages |
| Command | `/email-search` | Search the mailbox |
| Command | `/email-send` | Draft + send (with confirmation) |

---

## Install

### 1. Prerequisites
- **Node.js** installed (the MCP server runs via `npx`).
- Your mailbox **IMAP/SMTP credentials** (for HostGator-hosted Alchlight mail,
  that's your full email address + mailbox password).

### 2. Set your credentials
Copy `.env.example`, fill in your own values, and make sure the variables are
**exported in the shell that launches Claude Code**:

```bash
export IMAP_USER="you@alchlight.com"
export IMAP_PASSWORD="your-mailbox-password"
# host/port default to the Alchlight server; override only if yours differs
```

Add these to `~/.bashrc` / `~/.zshrc` (or a [direnv](https://direnv.net/) `.envrc`)
so they persist. **Do not commit them.**

### 3. Add the marketplace and install
From Claude Code:

```
/plugin marketplace add <git-url-or-path-to-this-repo>
/plugin install alchlight-email@alchlight-tools
```

Or for a local checkout:

```
/plugin marketplace add ~/alchlight-email-plugin
/plugin install alchlight-email@alchlight-tools
```

Restart Claude Code (or reload plugins). Verify the MCP server connects with
`/mcp` — you should see `alchlight-email` listed.

---

## Usage

- `/inbox` — recent mail at a glance
- `/email-search from:jane invoice` — find messages
- `/email-send reply to the last message from Jane confirming the meeting`
- Or just ask naturally: *"check my inbox", "find the email about the contract",
  "draft a reply to Bob"*. The skill activates automatically.

The skill **always drafts and asks before sending or deleting** — nothing leaves
your mailbox without your explicit confirmation.

---

## Security notes

- Credentials live **only** in your environment, never in this repo. The
  `.gitignore` blocks `.env`.
- The MCP server talks directly to your mail host over TLS; mail contents are
  visible to Claude during a session — treat them as you would any data you
  share with an assistant.
- Use a dedicated mailbox password / app password where your provider supports
  it, rather than your primary account password.

---

## Troubleshooting

- **`/mcp` shows it failing to connect** → check `IMAP_USER` / `IMAP_PASSWORD`
  are exported in the same shell that started Claude Code; confirm Node is on PATH.
- **Auth errors** → verify host/port match your provider (defaults are HostGator
  `gator3272.hostgator.com`, IMAP 993 / SMTP 465, both TLS).
- **`npx` is slow on first run** → it downloads `imap-email-mcp` once, then caches it.
