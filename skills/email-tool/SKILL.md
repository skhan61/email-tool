---
name: email-tool
description: Read, search, triage, draft, and send email from the connected IMAP/SMTP mailbox. Use whenever the user wants to check their inbox, find a specific message, reply to someone, compose or send mail, or manage drafts and folders.
---

# Alchlight Email

This skill drives the `email-tool` MCP server (an IMAP/SMTP bridge). Use the
`mcp__email-tool__*` tools to act on the user's real mailbox.

## Available tools

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
- If multiple folders/accounts exist, confirm which one before acting.
- Quote message-IDs or subjects when referring to mail so the user can verify.
