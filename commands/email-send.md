---
description: Draft and send an email (with confirmation before sending).
---

Compose an email based on: $ARGUMENTS

Steps:
1. Work out which mailbox to send FROM (the `mailbox` argument of `send_email`;
   `list_mailboxes` shows them). If more than one exists and it is not stated, ask.
2. Work out the recipient, subject, and body. If any is missing, ask me.
3. Show the complete proposed message (From / To / Subject / Body) and STOP.
4. Only after I explicitly confirm, send it.

Never send without my explicit "send it" / "yes". Sending is irreversible.
