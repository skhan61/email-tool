# Troubleshooting

Find the message you see, then follow the fix. Messages from email-tool also reach your
assistant, which can tell you the same.

## Setup

| You see | Fix |
|---|---|
| `uvx: command not found` | [Install uv](install.md#step-1-install-uv), then close and reopen the terminal. |
| The email tools do not appear in a desktop app on macOS | The app cannot find `uvx`. Use its full path from `which uvx` in the app's settings, as shown in [Install](install.md). |
| The email tools do not appear in normal ChatGPT Chat | Local tools work in ChatGPT's **Work** and **Codex** modes. Normal Chat does not reach them yet. |
| `No mailbox is configured.` | [Add a mailbox](mailboxes.md). |
| `No mailbox called 'x'. Configured: ...` | Use one of the names listed, or add that mailbox. |
| `Several mailboxes are configured; name one of: ...` | Tell the assistant which mailbox to use. |

## Passwords and App Passwords

| You see | Fix |
|---|---|
| `No password for mailbox 'work' on this machine.` | Run `email-tool-mcp add work` again. |
| The login check fails for a Gmail address | Gmail needs an [App Password](mailboxes.md#gmail), not your account password. |
| App Passwords is missing from your Google account | Your organization turned them off. Use [Google Workspace](mailboxes.md#google-workspace). |
| The login check fails for any other mailbox | Check the server names and ports with `email-tool-mcp list`. IMAP uses port 993. SMTP uses STARTTLS on ports 25 and 587 and direct TLS on other ports (usually 465). Then ask your provider whether IMAP is turned on. |

## Microsoft sign-in

| You see | Fix |
|---|---|
| `Need admin approval` (AADSTS90094 or AADSTS65001) | Your IT department must approve email-tool. Ask them to grant admin consent to application ID `82731d7a-ac7f-4a5e-88d3-acce522f85ce`, or to give you their own app's ID for `--client-id`. |
| `work needs a new Microsoft sign-in` | Run the command in the message. It signs you in again. |
| The sign-in works but the login check fails | IMAP or authenticated SMTP is turned off for your mailbox. Ask your IT department to turn them on. |
| No browser opens | Add `--device-code` and enter the code it shows at microsoft.com/devicelogin. |

## Google sign-in

| You see | Fix |
|---|---|
| `Google hasn't verified this app` | Expected for your own External client. Select **Continue**. |
| `Access blocked: ... admin` | Your organization blocks apps it has not approved. Ask your IT department to allow your client, or to create an Internal one. |
| `This site can't be reached` after you allow access | Run the command again with `--paste-address`, then paste back the address the browser ends on. |
| `No browser can be opened from here` | Open the address the terminal prints in a browser on the same computer, or use `--paste-address`. |
| `no answer from the browser within 5 minutes` | Run the command again and finish the sign-in within 5 minutes. |
| `Google granted less than was asked` | Run the command again and leave every permission selected. |
| `signed in as ..., not ...` | Gmail logs in as the Google account itself. Use `--address` with the account you signed in with. |
| `work needs a new Google sign-in` | Run the command in the message. A client in **Testing** ends sign-ins after 7 days: [publish it](mailboxes.md#create-the-sign-in-client). |

## Policy and audit log

| You see | Fix |
|---|---|
| A message that starts with `policy:` | Your organization's policy refused the action. The message names the rule. See [For administrators](administrators.md#policy). |
| `Refused, nothing was done: ...` | The audit log could not be written, so nothing ran. Check that the log's folder exists and has space (`email-tool-mcp audit path`). |
| `the log does not match its keyring anchor` | The log was changed or replaced. Run `email-tool-mcp audit verify` and report the result to your security team. |
| `... contains invalid text (a broken Unicode character)` | The assistant sent text that is not valid. Ask it to try again. |

## Still stuck

Open an issue at [github.com/skhan61/email-tool/issues](https://github.com/skhan61/email-tool/issues)
with the message you see and the output of `email-tool-mcp list`. Remove anything private
first. Report security problems privately, as described in the
[security policy](https://github.com/skhan61/email-tool/blob/main/SECURITY.md).
