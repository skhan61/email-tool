---
description: Search a mailbox for messages matching a query.
---

Search with `search_emails`. Pick the mailbox with the `mailbox` argument (`list_mailboxes` shows them). If more than one exists and the request does not say which, ask first.

Search for: $ARGUMENTS

Parse $ARGUMENTS into the narrowest filter you can (sender, subject keywords,
date range, free text). On Gmail you may also use `gmail_query` for native
Gmail search syntax. Present results as a table: sender, subject, date.
If nothing matches, say so and suggest a broader query. Then ask which result
to open with `get_email`.
