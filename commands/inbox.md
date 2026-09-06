---
description: Show a summary of the most recent messages in the inbox.
---

List the most recent messages in INBOX using the `list_emails` tool of the
mailbox the user means: `mcp__alchlight__list_emails` for Alchlight work mail,
`mcp__gmail__list_emails` for personal Gmail. If both servers are available and
the request does not say which, ask first.

Present them as a compact table: sender, subject, date.

Do not open individual message bodies unless I ask. End by asking which message
(if any) I want to read, reply to, or act on.

$ARGUMENTS may contain a mailbox, a folder name, or a count (e.g. "gmail Sent 10");
honor it if present.
