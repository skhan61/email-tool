---
name: email-tool
description: Read, search, triage, draft, and send email from the connected IMAP/SMTP mailbox. Use whenever the user wants to check their inbox, find a specific message, reply to someone, compose or send mail, or manage drafts and folders.
---

# Email Tool

This skill drives the IMAP/SMTP mail server shipped by the `email-tool`
plugin, acting on the user's real mail.

## Mailboxes

One MCP server (`email`) serves every mailbox configured on this machine.
Each tool takes a `mailbox` argument; `list_mailboxes` names them and says
whether each has a password. If more than one exists and the request is
ambiguous, ask which mailbox before acting.

A tool error saying there is no password means the user must run
`email-tool-mcp add <name>` in a terminal. Never ask for the password in chat.

## Available tools

- `list_mailboxes`, the mailboxes on this machine.
- `add_mailbox`, open a setup page in the user's browser to add a mailbox
  (Gmail, Outlook / Microsoft 365, Google Workspace or any other). Call it when
  no mailbox is configured or the user asks to add one. Never ask for a
  password in the chat: the user types it on that page only.
- `list_folders`, list mailbox folders (INBOX, Sent, Drafts, ...).
- `list_emails`, list messages in a folder (most recent first).
- `search_emails`, search by sender, subject, date range, or text.
- `get_email`, fetch the full body + headers of one message.
- `send_email`, send a new message immediately.
- `create_draft` / `get_draft` / `list_drafts` / `update_draft`, manage drafts.
- `delete_email`, delete a message (destructive, confirm first).
- `report_problem`, build a problem report for the email-tool maintainer when the
  user wants to report a problem. Show it exactly as returned; it sends nothing.
- `email_problem_report`, email that report to the maintainer from a mailbox the
  user picks; their app asks them to approve the exact text first.

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
   subject (prefix `Re:`) and recipient. Pass its UID as `in_reply_to_uid`
   (and its folder as `in_reply_to_folder` when not INBOX) to `create_draft`,
   `update_draft` or `send_email`, so the reply joins that conversation.
2. **Draft first.** Create the draft or show the user the full proposed
   message (To / Subject / Body) and wait for explicit approval.
3. Only call `send_email` after the user confirms. Sending is irreversible
   and outward-facing, never send unprompted.

### Links and formatting
Never paste a bare URL into a message. Pass `html` with the link behind
descriptive text (`<a href="...">NSC 2026 customer list</a>`), and a matching
plain-text `body` as the fallback. `send_email`, `create_draft` and
`update_draft` all accept `html`; a draft saved with it opens in rich-text
mode in the mail client.

## Safety rules

- **Never send or delete without explicit user confirmation.** Show the exact
  recipient, subject, and body, then wait for a clear "send it" / "yes".
- Treat email addresses and message contents as private, don't echo full
  bodies to external tools or include them in web searches.
- If several mailboxes exist, confirm which one before acting.
- Never move mail between mailboxes without being asked.
- Quote message-IDs or subjects when referring to mail so the user can verify.
