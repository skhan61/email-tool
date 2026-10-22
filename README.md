<p align="center"><img src="assets/icon.png" alt="email-tool icon" width="112"></p>

<h1 align="center">email-tool</h1>

<p align="center"><b>Email for any AI agent that speaks MCP: Claude Code, Claude Desktop, Cowork, ChatGPT desktop, Codex and others.</b><br>
Read, search, draft and send mail over IMAP/SMTP.</p>

<p align="center">
  <b>Works with</b><br>
  <a href="#claude-code"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude%20Code-plugin-D97757?logo=claude&logoColor=white"></a>
  <a href="#claude-desktop-and-claude-cowork"><img alt="Claude Desktop and Cowork" src="https://img.shields.io/badge/Claude%20Desktop%20%2F%20Cowork-.mcpb-D97757?logo=claude&logoColor=white"></a>
  <a href="#chatgpt-desktop-and-codex"><img alt="ChatGPT desktop and Codex" src="https://img.shields.io/badge/ChatGPT%20desktop%20%2F%20Codex-plugin-10A37F"></a>
  <a href="https://modelcontextprotocol.io"><img alt="MCP server" src="https://img.shields.io/badge/MCP-server-1F2A44"></a>
</p>

<p align="center">
  <b>Compliance</b><br>
  <a href="docs/cmmc.md"><img alt="CMMC Level 2 / NIST SP 800-171 control mapping" src="https://img.shields.io/badge/CMMC%20L2%20%2F%20NIST%20SP%20800--171-control%20mapping-2B5797"></a>
</p>

<p align="center">
  <b>Build and security</b><br>
  <a href="https://github.com/skhan61/email-tool/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/skhan61/email-tool/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/skhan61/email-tool/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/skhan61/email-tool/actions/workflows/codeql.yml/badge.svg?branch=main"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/skhan61/email-tool"><img alt="OpenSSF Scorecard" src="https://img.shields.io/ossf-scorecard/github.com/skhan61/email-tool?label=OpenSSF%20Scorecard"></a>
  <a href="https://github.com/skhan61/email-tool/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/skhan61/email-tool?label=release&logo=github"></a>
</p>

<p align="center">
  <b>Code quality</b><br>
  <a href="pyproject.toml"><img alt="Python version" src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fskhan61%2Femail-tool%2Fmain%2Fpyproject.toml&logo=python&logoColor=white"></a>
  <a href=".github/workflows/ci.yml"><img alt="Tested on Linux, macOS and Windows" src="https://img.shields.io/badge/tested%20on-Linux%20%7C%20macOS%20%7C%20Windows-555"></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
  <a href="pyproject.toml"><img alt="mypy strict" src="https://img.shields.io/badge/types-mypy%20strict-2A6DB2"></a>
  <a href="https://github.com/astral-sh/uv"><img alt="uv" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json"></a>
  <a href=".pre-commit-config.yaml"><img alt="pre-commit" src="https://img.shields.io/badge/pre--commit-enabled-FAB040?logo=pre-commit&logoColor=white"></a>
  <a href=".github/dependabot.yml"><img alt="Dependabot" src="https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white"></a>
</p>

<p align="center">
  <b>Project</b><br>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/skhan61/email-tool"></a>
  <a href="SECURITY.md"><img alt="Security policy" src="https://img.shields.io/badge/security-policy-C0392B"></a>
  <a href="CONTRIBUTING.md"><img alt="Contributing" src="https://img.shields.io/badge/PRs-welcome-2EA44F"></a>
</p>

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

Pick the row for your account. Each command checks that reading and sending both
work before it saves anything.

| Your account | How it signs in | Command |
|---|---|---|
| Your own domain or hosting (cPanel, Fastmail, ...) | password | `email-tool-mcp add work` |
| Gmail (personal) | [App Password](https://myaccount.google.com/apppasswords) | `email-tool-mcp add gmail` |
| Outlook.com, Hotmail, Live | Microsoft sign-in | `email-tool-mcp add outlook --auth microsoft --address you@outlook.com` |
| Microsoft 365 at work or university | Microsoft sign-in | `email-tool-mcp add work --auth microsoft --address you@company.com` |
| Google Workspace at work or university, App Passwords turned off | Google sign-in, your own client | `email-tool-mcp add school --auth google --address you@school.edu --client-secrets <file>` |

Not sure which one you have? Ask your IT department, or look at the mail records of your
domain (for example on mxtoolbox.com): `google.com` means Google, `outlook.com` means
Microsoft. Run the commands with `uvx --from git+https://github.com/skhan61/email-tool`
in front if email-tool is not installed as a package.

Passwords go to the OS keyring; sign-ins are kept encrypted (key in the OS keyring) and
refresh themselves. If one ever expires, the assistant tells you the command to run again.
Other commands: `email-tool-mcp list`, `email-tool-mcp remove <name>`.

#### Microsoft sign-in

A browser opens on Microsoft's sign-in page; sign in and approve "email-tool". The
project's app is used by default, so there is nothing to set up. Options:
`--device-code` on a machine without a browser, `--tenant <directory id>` to pin a
Microsoft 365 directory, `--client-id <id>` to use your organisation's own app.
GCC High always needs an app registered in GCC High:
`--cloud gcc-high --client-id <app id>`.

An organisation's IT department can register its own app instead: Microsoft Entra >
App registrations > New registration; supported accounts as needed; redirect URI
"Public client/native", `http://localhost`; then give users its Application (client) ID.

#### Google sign-in (Google Workspace without App Passwords)

Google does not allow one shared app for full Gmail access without a paid review, so
each person, or their IT department once for everyone, creates a small sign-in client:

1. [console.cloud.google.com](https://console.cloud.google.com/projectcreate): create a
   project (a personal Google account is fine; it does not need to be the mail account).
2. Google Auth Platform > Get started: app name `email-tool`, your email as support and
   contact. Audience: **Internal** if you are your organisation's administrator (no
   limits, no warning), otherwise **External**.
3. External only: Audience > Publish app (needs the home page and privacy links on the
   Branding page), so sign-ins do not expire after 7 days. Until then, add yourself
   under Test users.
4. Clients > Create client > **Desktop app** > Create > **Download JSON**.
5. `email-tool-mcp add school --auth google --address you@school.edu --client-secrets ~/Downloads/client_secret_....json`

Google then shows "Google hasn't verified this app" for an External client: it is your
own app, so choose Continue. If the browser is on another computer, or ends on
"site can't be reached", add `--paste-address` and paste back the address it ends on.

#### When a sign-in is refused

| What you see | What it means | What to do |
|---|---|---|
| "Need admin approval" (Microsoft AADSTS90094, 65001) | your organisation approves apps centrally | ask IT to grant admin consent to the app ID in the message, or for their own app's ID |
| "Access blocked: ... admin" (Google) | your Workspace blocks unapproved apps | ask IT to allow your client, or to create an Internal client |
| login check fails after a successful sign-in | IMAP or SMTP is turned off for your mailbox | ask IT to enable IMAP and authenticated SMTP |
| "App Passwords" missing in your Google account | your Workspace turned them off | use Google sign-in above |

### 2. Connect your agent

Every agent runs the same command:

```
uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp serve
```

Desktop apps on macOS do not see your shell's `PATH`, so they need the full
path to `uvx` (`which uvx`, usually `~/.local/bin/uvx`).

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
mailboxes added in step 1). It keeps that password in the OS keychain and hands
it to the server as an environment variable when it starts it.

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

On macOS, replace `uvx` with its full path (`which uvx`). Cowork uses the
servers Claude Desktop runs, so nothing else is needed.

#### ChatGPT desktop and Codex

Install the plugin, which also adds the email skill. In the ChatGPT desktop app:
Plugins > Add Marketplace > `skhan61/email-tool`, then install **email-tool**.
Or in a terminal (Codex CLI):

```
codex plugin marketplace add skhan61/email-tool
codex plugin add email-tool@email-tool
```

On macOS the app may not find `uvx`. If the email tools do not appear, add the
server by hand in `~/.codex/config.toml` with the full path (`which uvx`):

```toml
[mcp_servers.email]
command = "/Users/you/.local/bin/uvx"
args = ["--from", "git+https://github.com/skhan61/email-tool", "email-tool-mcp", "serve"]
```

Known ChatGPT issue: local tools work in **Work / Codex** mode but do not reach
normal **Chat** yet ([openai/codex#38162](https://github.com/openai/codex/issues/38162)).
Nothing changes on this side when OpenAI fixes it.

#### ChatGPT Business / Enterprise: normal Chat and the web

OpenAI's [Secure MCP Tunnel](https://github.com/openai/tunnel-client) carries
ChatGPT's tool calls to the server on your machine over an outbound connection.
No port is opened and the password stays in your keyring, but while
`tunnel-client run` is going, the workspace connector can read, send and delete
mail in every configured mailbox. Do not share the connector with other
workspace members, and stop the tunnel when you are done.

1. Create a tunnel at platform.openai.com > Settings > Tunnels, scoped to your
   ChatGPT workspace (needs the Tunnels Manage role).
2. Run it on your machine:
   ```
   tunnel-client init --sample sample_mcp_stdio_local --profile email \
     --tunnel-id <tunnel_id> \
     --mcp-command "uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp serve"
   tunnel-client run --profile email
   ```
3. In ChatGPT: Settings > Connectors > add, **Connection: Tunnel**, pick the tunnel.
   Keep `tunnel-client run` going while you use it.

#### Any other MCP client

Add a stdio server that runs
`uvx --from git+https://github.com/skhan61/email-tool email-tool-mcp serve`.

## Policy

Limit what agents may do, per mailbox or for all of them. Two files, same format;
the most restrictive combination applies, so a user can tighten the
administrator's policy but never loosen it:

```
email-tool-mcp policy paths          # administrator file (system-wide) and user file
email-tool-mcp policy show work      # the effective rules for one mailbox
```

```toml
[default]                                    # every mailbox
allowed_recipient_domains = ["example.com"]  # send/draft only to these domains

require_approval = true                      # send, delete and replace-draft ask you first
cui_recipient_domains = ["example.com"]      # mail marked CUI only to these domains

allow_environment_mailbox = false            # ignore mailboxes an app sets in its environment

[mailboxes."archive@example.com"]            # by address: binds under any mailbox name
read_only = true                             # no send, draft or delete

[mailboxes.work]                             # by name (case-insensitive); a user could re-enrol under another name
allowed_tools = ["list_emails", "search_emails", "get_email", "create_draft"]
```

With `require_approval`, your app shows you the delivered recipients, the
subject and the whole message (HTML included), or for a delete the message it
removes, and waits for your yes before anything irreversible runs; the AI cannot
answer for you. Apps that cannot show such a prompt are refused. Turn it on in
the administrator file to make it binding.

With `cui_recipient_domains`, any message carrying a CUI marking (a `CUI` or
`CONTROLLED` banner line such as `CUI//SP-PROPIN`, a `(CUI)` portion mark, or a
subject starting with one, per DoD Instruction 5200.48 and the NARA marking
handbook) is refused unless every recipient is in those domains. Every text part
is checked, HTML included. Mentioning CUI in a sentence is not a marking.

Refusals name the rule and are recorded in the audit log. Recipients are checked
on the finished message, the same list the mail server receives. The
administrator file is `/etc/email-tool/policy.toml` on Linux
(`email-tool-mcp policy paths` shows it on macOS and Windows); an existing file
that cannot be read stops every call rather than being skipped.

The policy stops the agent and accidental loosening. A user with full control
of their own machine could run other code, so where that matters, manage the
installation centrally as well.

## Audit log

Every action an agent takes is recorded twice: once before it runs and once with
its outcome. A record holds the time, OS user, host, mailbox, tool, folder,
message UIDs, recipients and the outcome. Subjects, bodies and passwords are
never written. If the "before" record cannot be written, the action is refused.

```
email-tool-mcp audit path      # where the log is
email-tool-mcp audit verify    # detects edited, inserted, reordered or removed records
```

Records are chained with HMAC-SHA256 using a key kept in the OS keyring, and the
newest record's MAC is kept there too, so anyone without access to the user's
keyring cannot change or trim the log unnoticed. Someone in full control of the
account could; send a copy off the machine for that:
`EMAIL_TOOL_AUDIT_SYSLOG=tcp://siem.example.com:6514` (or `udp://`, or `host:port`).
`EMAIL_TOOL_AUDIT_FILE` moves the log. Retention follows your organization's
policy: the tool never deletes records.

## Encryption in transit

IMAP and SMTP always use TLS with certificate verification, never older than
TLS 1.2 (NIST SP 800-52). See what a mailbox actually negotiates:

```
$ email-tool-mcp check work
work (you@example.com)
  IMAP imap.example.com:993  TLSv1.3 TLS_AES_256_GCM_SHA384  (login ok)
  SMTP smtp.example.com:465  TLSv1.3 TLS_AES_256_GCM_SHA384  (login ok)
  minimum accepted: TLS 1.2   certificate verification: on   OpenSSL: ...
  FIPS mode: off
```

`require_fips = true` in the policy refuses every call unless Python's OpenSSL
runs in FIPS mode (a FIPS 140 validated module, as CMMC requires for CUI). FIPS
mode is an operating-system setting, for example Ubuntu Pro FIPS or RHEL in FIPS
mode; this tool only reports and enforces it.

## CMMC Level 2

[docs/cmmc.md](docs/cmmc.md) maps each feature to the NIST SP 800-171 Rev. 2
requirement it supports, the evidence an assessor can check, and what your
organization must still do. Software is not CMMC certified; organizations are.

## Security

- The server reads passwords from the OS keyring, or from `EMAIL_TOOL_PASSWORD`
  when a host such as Claude Desktop keeps the secret itself and passes it in
  the server's environment. They are never
  command-line arguments, so they cannot appear in a process listing.
- Mail contents are visible to the AI agent during a session; treat them as
  any data you share with an assistant.
- Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Troubleshooting

- **"No password for mailbox"**: run `email-tool-mcp add <name>` again.
- **Login refused**: check the servers with `email-tool-mcp list`; ports are
  IMAP 993 is implicit TLS; SMTP uses STARTTLS on ports 25 and 587 and implicit TLS on any other port (465 usually).

## License

[MIT](LICENSE)
