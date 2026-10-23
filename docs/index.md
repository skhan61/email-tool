# email-tool

email-tool lets an AI assistant read, search, draft and send your email, with attachments:
it sends the files you name and saves the attachments you receive. It works with Claude Code,
Claude Desktop, Claude Cowork, ChatGPT desktop, Codex and any other app that supports the
Model Context Protocol (MCP).

It runs on your own computer and keeps your passwords in your operating system's keyring.
It is built for organizations that handle Controlled Unclassified Information (CUI) under
CMMC Level 2 and NIST SP 800-171: every action is logged, sending can wait for your
approval, and CUI-marked mail stays inside the domains you allow.

## What you can ask for

- "Summarize the unread mail in my work inbox."
- "Find the invoice Dana sent last week and show it to me."
- "Draft a reply to that message, and keep it in my drafts."
- "Send the draft to the whole project team."
- "Send the report in my Documents folder to Lee."
- "Save the invoice attached to Dana's message in my Downloads."

Files you send and attachments you save are covered in [Attachments](use.md#attachments).

## Get started

[Start here](start.md): three steps for Claude Desktop, Cowork, ChatGPT desktop, Codex,
Claude Code or any other MCP app. No terminal.

1. Install email-tool in your app.
2. Ask your assistant to "add my mailbox". A page opens in your browser.
3. Ask your assistant to check your mail.

## Works with

| App | How it connects |
|---|---|
| Claude Code | plugin |
| Claude Desktop and Claude Cowork | `.mcpb` bundle or config file |
| ChatGPT desktop and Codex | plugin |
| ChatGPT Business and Enterprise (Chat and web) | OpenAI Secure MCP Tunnel |
| Any other MCP app | a local command |

| Mail account | How it signs in |
|---|---|
| Outlook.com, Hotmail, Live | Microsoft sign-in |
| Microsoft 365 (company, school or any organization) | Microsoft sign-in |
| Microsoft 365 GCC High | Microsoft sign-in with your organization's app |
| Gmail | App Password |
| Google Workspace (company, school or any organization) | Google sign-in |
| Any other mailbox with IMAP and SMTP | password |

## Built for regulated work

See [Why CMMC](why-cmmc.md) for what each protection does, with examples, and the
[CMMC control mapping](cmmc.md) for the NIST SP 800-171 requirement each one supports.
Software is not CMMC certified; organizations are.
