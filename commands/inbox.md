---
description: Show a summary of the most recent messages in the inbox.
---

List the most recent messages in INBOX with `list_emails`. Pick the mailbox with the `mailbox` argument (`list_mailboxes` shows them). If more than one exists and the request does not say which, ask first.

Present them as a compact table: sender, subject, date.

Do not open individual message bodies unless I ask. End by asking which message
(if any) I want to read, reply to, or act on.

$ARGUMENTS may contain a mailbox, a folder name, or a count (e.g. "home Sent 10");
honor it if present.
