---
description: Search a mailbox for messages matching a query.
---

Search using the `search_emails` tool of the mailbox the user means:
`mcp__alchlight__search_emails` or `mcp__gmail__search_emails`. If both servers
are available and $ARGUMENTS does not say which, ask first.

Search for: $ARGUMENTS

Parse $ARGUMENTS into the narrowest filter you can (sender, subject keywords,
date range, free text). On Gmail you may also use `gmail_query` for native
Gmail search syntax. Present results as a table: sender, subject, date.
If nothing matches, say so and suggest a broader query. Then ask which result
to open with `get_email`.
