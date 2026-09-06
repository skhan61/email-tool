---
description: Configure a mailbox on this machine (asks for the password in your terminal, never in chat).
---

Set up email-tool credentials on this machine.

$ARGUMENTS may name a mailbox (e.g. "gmail"). If it does not, work it out below.

## Rules

**Never ask the user to type a password into this conversation.** Anything typed
here is written to the session transcript in plaintext. The setup script prompts
in the user's own terminal with hidden input instead. Do not offer a shortcut
around this, and do not offer to write the secrets file yourself.

Do not run the setup script through your Bash tool either. It needs a real
terminal to hide the password, and your tool calls have none.

## Steps

1. Show the user which mailboxes exist and which are already configured on this
   machine by running:

   `python3 "${CLAUDE_PLUGIN_ROOT}/setup/__main__.py" --list`

   This reads only key names, never any secret.

2. If $ARGUMENTS did not name a mailbox, ask which one they want. If every
   mailbox is already configured, say so and stop, unless they want to replace
   a password.

3. Give them the exact line to paste into a terminal, and stop:

   ```
   python3 "<expanded plugin root>/setup/__main__.py" --mailbox <name>
   ```

   Expand `${CLAUDE_PLUGIN_ROOT}` to the real path first, so it can be pasted
   into a plain shell. Tell them it asks for the address, then the password
   with the typing hidden, verifies both against the real mail server, and only
   writes the file if the login actually works.

4. Wait for them to report back. Then confirm with `--list` that the mailbox now
   shows as configured, and remind them to restart Claude Code so the server
   starts.

## Notes

- Gmail requires a Google App Password, not the account password.
- The file written is `~/.config/claude-secrets.env` at mode 600. It is
  machine-local and is never committed.
- A mailbox with no keys on this machine simply will not start here. That is how
  one machine runs a different set of mailboxes from another.
