---
name: email-tool
description: Read, search, triage, draft, and send email from the connected IMAP/SMTP mailbox. Use whenever the user wants to check their inbox, find a specific message, reply to someone, compose or send mail, or manage drafts and folders.
---

# Email Tool

This skill drives the IMAP/SMTP mailbox servers shipped by the `email-tool`
plugin, acting on the user's real mail.

## Mailboxes

This plugin exposes one MCP server per mailbox. A machine enables only the
mailboxes it needs, so the set present varies:

- `mcp__alchlight__*`, the Alchlight work mailbox (HostGator)
- `mcp__gmail__*`, the personal Gmail mailbox

Pick the server that matches the mailbox the user means. If both are present
and the request is ambiguous, ask which mailbox before acting.

## Available tools

Each mailbox server exposes the same ten tools, prefixed by its own name.

- `list_folders`, list mailbox folders (INBOX, Sent, Drafts, ...).
- `list_emails`, list messages in a folder (most recent first).
- `search_emails`, search by sender, subject, date range, or text.
- `get_email`, fetch the full body + headers of one message.
- `send_email`, send a new message immediately.
- `create_draft` / `get_draft` / `list_drafts` / `update_draft`, manage drafts.
- `delete_email`, delete a message (destructive, confirm first).

## Workflows

### Triage the inbox
1. `list_emails` on INBOX (default 20 most recent).
2. Summarize as a table: sender · subject · date · unread?.
3. Ask the user what to act on. Do not open every body unprompted, only
   `get_email` for messages the user wants to read.

### Find a specific message
Prefer `search_emails` with the narrowest filter you have (sender + subject
keyword + date range) over listing and scanning. Fall back to `list_emails`
only when search returns nothing.

### Reply or compose
1. For a reply, `get_email` the original to quote context and reuse the
   subject (prefix `Re:`) and recipient.
2. **Draft first.** Create the draft or show the user the full proposed
   message (To / Subject / Body) and wait for explicit approval.
3. Only call `send_email` after the user confirms. Sending is irreversible
   and outward-facing, never send unprompted.

## Safety rules

- **Never send or delete without explicit user confirmation.** Show the exact
  recipient, subject, and body, then wait for a clear "send it" / "yes".
- Treat email addresses and message contents as private, don't echo full
  bodies to external tools or include them in web searches.
- If both mailbox servers are enabled, confirm which mailbox before acting.
- Never move mail between mailboxes without being asked.
- Quote message-IDs or subjects when referring to mail so the user can verify.
