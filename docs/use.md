# Everyday use

Talk to your assistant in plain language. Name the mailbox when you have more than one.

## Examples

| You say | What happens |
|---|---|
| "Which mailboxes do I have?" | Lists your mailboxes and whether each can log in. |
| "Summarize today's mail in my work inbox." | Lists the newest messages and summarizes them. |
| "Find Dana's message about the invoice from last week." | Searches by sender, subject, text and date. |
| "Show me that message." | Opens the whole message. It stays unread in your mail app. |
| "Draft a reply saying I agree, and save it." | Saves a draft. Nothing is sent. |
| "Change the draft: add Lee in Cc." | Replaces the draft with the new version. |
| "Send it." | Sends the message. Sending cannot be undone. |
| "Delete the newsletter from this morning." | Deletes that message permanently. |

In Claude Code, the plugin also adds three commands: `/inbox`, `/email-search` and
`/email-send`.

## What the assistant can do

| Tool | What it does |
|---|---|
| `list_mailboxes` | Lists your mailboxes and whether each can log in |
| `list_folders` | Lists the folders in a mailbox |
| `list_emails` | Lists the newest messages in a folder |
| `search_emails` | Searches by sender, subject, text, date, or a Gmail search |
| `get_email` | Opens one message in full |
| `create_draft`, `list_drafts`, `get_draft`, `update_draft` | Works with drafts |
| `send_email` | Sends a message |
| `delete_email` | Deletes a message permanently |

## Approve before sending

When your organization turns on approval, your app asks you before email-tool sends,
deletes or replaces a draft. The question shows the real recipients, the subject and the
whole message. Select **Accept** to go ahead or **Decline** to stop. The assistant cannot
answer for you.

## Your mail and the assistant

Messages you ask about are shown to the AI assistant during the conversation. Treat them as
you treat anything else you share with that assistant.
