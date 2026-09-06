---
description: Search the mailbox for messages matching a query.
---

Search the mailbox using `mcp__email-tool__search_emails` for: $ARGUMENTS

Parse $ARGUMENTS into the narrowest filter you can (sender, subject keywords,
date range, free text). Present results as a table: sender · subject · date.
If nothing matches, say so and suggest a broader query. Then ask which result
to open with `get_email`.
