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
| "Send the report in ~/Documents/q3.pdf to Lee." | Sends the message with that file attached. |
| "Save the invoice attached to Dana's message in ~/Downloads." | Saves the attachment there. It is never opened. |
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
| `get_email` | Opens one message in full, with its attachments listed |
| `save_attachment` | Saves one attachment into a folder you name |
| `create_draft`, `list_drafts`, `get_draft`, `update_draft` | Works with drafts |
| `send_email` | Sends a message, with any attachments |
| `delete_email` | Deletes a message permanently |

## Approve before sending

When your organization turns on approval, your app asks you before email-tool sends,
deletes or replaces a draft. The question shows the real recipients, the subject and the
whole message. Select **Accept** to go ahead or **Decline** to stop. The assistant cannot
answer for you.

## Attachments

The assistant can attach any file you ask for, from any folder, up to 25 MB per message.

If a file looks sensitive, your app asks you before anything is sent and says why, for
example "id_ed25519 looks sensitive: it is an SSH private key". Files that look sensitive
include private keys, `.env` files, cloud credentials, password databases, files in folders
such as `.ssh` or `.aws`, and files with CUI markings. Select **Accept** to send them anyway;
the decision is yours.

If your app cannot show that question, the assistant tells you which files it found and
sends them only after you confirm in the conversation. A draft with such a file is saved,
with the same warning.

Saved attachments get a safe file name and never replace an existing file.

## Your mail and the assistant

Messages you ask about are shown to the AI assistant during the conversation. Treat them as
you treat anything else you share with that assistant.
