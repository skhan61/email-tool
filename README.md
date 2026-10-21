# email-tool

Email for any AI agent that speaks MCP (Claude Code, Claude Desktop, Claude
Cowork, ChatGPT desktop, Codex and others): read, search, draft and send mail
over IMAP/SMTP.

- **One server for all your mailboxes.** Work and personal mail side by side;
  every tool takes a `mailbox` argument.
- **Passwords stay in your OS keyring** (Keychain, Credential Manager, GNOME
  Keyring), never in an agent's config file, so an agent update or login
  refresh cannot erase them.
- **Runs on your machine over stdio.** It never opens a network port, and
  TLS certificates are always verified.

## Tools

| Tool | What it does |
|---|---|
| `list_mailboxes` | Mailboxes on this machine, and whether each has a password |
| `list_folders` | Folders in a mailbox |
| `list_emails` | Newest messages in a folder |
| `search_emails` | Search by sender, subject, body, date, or Gmail query |
| `get_email` | One message in full (does not mark it read) |
| `create_draft` / `list_drafts` / `get_draft` / `update_draft` | Drafts |
| `send_email` | Send now (irreversible) |
| `delete_email` | Delete permanently |

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Add each mailbox once per machine

```bash
uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp add work
```

It asks for the address, the IMAP and SMTP servers (filled in for Gmail) and
the password (hidden), checks that both logins work, then saves the servers
to your user settings and the password to the OS keyring. Repeat for each
mailbox (`add home`, ...). Gmail needs an
[App Password](https://myaccount.google.com/apppasswords), not your account
password.

Other commands: `email-tool-mcp list`, `email-tool-mcp remove <name>`.

### 2. Connect your agent

Every agent runs the same command:

```
uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp serve
```

Desktop apps on macOS do not see your shell's `PATH`; if the agent cannot find
`uvx`, use its full path (`which uvx`, usually `~/.local/bin/uvx`).

#### Claude Code

```
/plugin marketplace add skhan61/email-tool
/plugin install email-tool@email-tool
```

Adds the `/inbox`, `/email-search` and `/email-send` commands too.

#### Claude Desktop and Claude Cowork

Either install the bundle: download `email-tool-<version>.mcpb` from the
[latest release](https://github.com/skhan61/email-tool/releases/latest) and
open it. Claude Desktop asks for one mailbox (leave it blank to use only the
mailboxes added in step 1) and keeps that password in the OS keychain.

Or add it to `claude_desktop_config.json` (Settings > Developer > Edit Config):

```json
{
  "mcpServers": {
    "email": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/skhan61/email-tool", "email-tool-mcp", "serve"]
    }
  }
}
```

Cowork uses the servers Claude Desktop runs, so nothing else is needed.

#### ChatGPT desktop and Codex

Settings > Plugins > Add > Add MCP server, type **STDIO**, command `uvx`,
arguments `--from git+https://github.com/skhan61/email-tool email-tool-mcp serve`.
Or add to `~/.codex/config.toml` (shared by the ChatGPT desktop app, the Codex
CLI and the IDE extension):

```toml
[mcp_servers.email]
command = "uvx"
args = ["--from", "git+https://github.com/skhan61/email-tool", "email-tool-mcp", "serve"]
```

Known ChatGPT issue: local tools show in the Codex tab but may not reach normal
chats yet ([openai/codex#38162](https://github.com/openai/codex/issues/38162)).
ChatGPT on the web accepts only internet-hosted servers, which this tool
deliberately is not.

#### Any other MCP client

Add a stdio server with the command above.

## Security

- The server only ever reads passwords from the OS keyring (or, for a host
  that stores secrets itself, from `EMAIL_TOOL_PASSWORD`). They are never
  command-line arguments, so they cannot appear in a process listing.
- Mail contents are visible to the AI agent during a session; treat them as
  any data you share with an assistant.
- Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Troubleshooting

- **"No password for mailbox"**: run `email-tool-mcp add <name>` again.
- **Login refused**: check the servers with `email-tool-mcp list`; ports are
  implicit TLS (IMAP 993, SMTP 465).
