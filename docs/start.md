# Start here

For **Claude Desktop** and **Claude Cowork** on Windows and macOS. Three steps, no terminal.

## 1. Download

[Download email-tool](https://github.com/skhan61/email-tool/releases/latest/download/email-tool.mcpb).
You get one file, `email-tool.mcpb`.

## 2. Install

Open the file (double-click it). Claude Desktop shows an install window for **email-tool**.
Leave every field blank and select **Install**.

## 3. Add your mailbox

In Claude, type:

> add my mailbox

A page opens in your browser. It runs on your computer only:

![The Add a mailbox page: choose the kind of mailbox, type the email address and, for Gmail, the password](assets/screens/setup-page.png){ width="560" }

1. Choose your kind of mailbox.
2. Type your email address.
3. Then, depending on the kind:
    - **Gmail:** type an App Password, not your Google password.
      [How to get an App Password](mailboxes.md#gmail).
    - **Outlook, Hotmail or Microsoft 365:** nothing more. After you select **Add mailbox**,
      Microsoft's sign-in page opens. Sign in and select **Accept**.
    - **Google Workspace at a company or school:** ask your IT department for the client file,
      or [create one](mailboxes.md#google-workspace).
    - **Any other mailbox:** type your password and, under **Any other mailbox: server names**,
      the server names from your provider.
4. Select **Add mailbox**. When the page says **Mailbox added**, go back to Claude.

Your password never passes through Claude. To add another mailbox, ask again.

## Try it

- "Summarize my unread mail."
- "Draft a reply to the last message from Dana, with the report from my Downloads attached."
- "Send it." Claude asks you before it sends anything.

Something not working? See [Troubleshooting](troubleshooting.md).

Using **Claude Code**, **ChatGPT desktop** or **Codex**? See [Install](install.md).
