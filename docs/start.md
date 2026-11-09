# Start here

Three steps, for any AI app. No terminal.

## 1. Install email-tool in your app

=== "Claude Desktop and Cowork"

    1. [Download email-tool](https://github.com/skhan61/email-tool/releases/latest/download/email-tool.mcpb).
       You get one file, `email-tool.mcpb`.
    2. Open the file (double-click it). Claude Desktop shows an install window.
    3. Leave every field blank and select **Install**.

    Claude Cowork uses what Claude Desktop installs, so it needs nothing more.

=== "ChatGPT desktop and Codex"

    1. Download the installer for your computer and open it:
        - **Windows:** [Install-email-tool.cmd](https://github.com/skhan61/email-tool/releases/latest/download/Install-email-tool.cmd).
          If Windows warns about a downloaded file, select **Run**, or **More info** and then
          **Run anyway**.
        - **macOS:** [Install-email-tool-macOS.zip](https://github.com/skhan61/email-tool/releases/latest/download/Install-email-tool-macOS.zip).
          Open the zip, then right-click **Install-email-tool.command** and select **Open**.
          macOS asks once because the file comes from the internet.
    2. When the installer says **Done**, open the ChatGPT desktop app and select **Plugins** >
       **Add Marketplace**. Type `skhan61/email-tool` and install **email-tool**.
    3. Close ChatGPT and open it again. Use **Work** or **Codex** mode; normal Chat does not
       reach tools on your computer yet.

=== "ChatGPT desktop on Linux"

    These steps work in **Codex** and in **Work**. ChatGPT desktop for Linux is a preview from
    OpenAI. Numbers in a picture show the order of the actions in that step.

    **Before you start**

    1. Install [ChatGPT desktop](https://openai.com/codex) and sign in.
    2. Open a terminal and install uv:

        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```

    3. If you just installed uv for the first time, sign out of your computer and sign in again
       so that ChatGPT can find it.

    **Open Plugins**

    === "Codex"

        At the top left, make sure **Codex** is selected, and then select **Plugins**.

        ![ChatGPT in Codex mode, with the mode menu and the Plugins icon highlighted](assets/screens/chatgpt-linux/codex-home.png)

    === "Work"

        At the top left, select **ChatGPT**, select **Work** at the top of the window, and then
        select **Plugins**.

        ![ChatGPT with the mode menu, the Work tab and the Plugins icon highlighted](assets/screens/chatgpt-linux/work-home.png)

    **Install email-tool**

    1. Select **Add**.

        ![The Plugins page with the Add button highlighted](assets/screens/chatgpt-linux/add-button.png)

    2. Select **Add a marketplace**.

        ![The Add menu with Add a marketplace highlighted](assets/screens/chatgpt-linux/add-menu.png)

    3. The **Add plugin marketplace** window opens. Select the **Source** box.

        ![The Add plugin marketplace window with the Source box highlighted](assets/screens/chatgpt-linux/marketplace-window.png)

    4. In **Source**, type `skhan61/email-tool`. Leave the other boxes empty, and then select
       **Add marketplace**.

        ![skhan61/email-tool typed in the Source box, with the Add marketplace button highlighted](assets/screens/chatgpt-linux/marketplace-source.png)

    5. In **Search plugins**, type `email-tool`. Next to **email-tool**, select **+**.

        ![The search result for email-tool, with the search box and the plus button highlighted](assets/screens/chatgpt-linux/find-email-tool.png)

    6. Wait until **email-tool** appears under **Installed**.

        ![email-tool highlighted in the Installed list](assets/screens/chatgpt-linux/installed.png)

    **Open the setup page**

    === "Codex"

        1. Select the Home icon. In the message box, type **add my mailbox** and press Enter.

            ![add my mailbox typed in the Codex message box](assets/screens/chatgpt-linux/codex-type.png)

        2. In the reply, select the link to the setup page. The link lasts 10 minutes.

            ![The reply from ChatGPT with the mailbox setup link highlighted](assets/screens/chatgpt-linux/codex-link.png)

        3. The **Add a mailbox** page opens in ChatGPT.

            ![The Add a mailbox page open in a tab inside ChatGPT](assets/screens/chatgpt-linux/codex-page.png)

    === "Work"

        1. Select the Home icon, and then select **Work**. In the message box, type
           **add my mailbox** and press Enter.

            ![add my mailbox typed in the Work message box, with the Work tab highlighted](assets/screens/chatgpt-linux/work-type.png)

        2. In the reply, select the link to the setup page. The link lasts 10 minutes.

            ![The reply from ChatGPT with the mailbox setup link highlighted](assets/screens/chatgpt-linux/work-link.png)

        3. The **Add a mailbox** page opens in ChatGPT.

            ![The Add a mailbox page open in a tab inside ChatGPT](assets/screens/chatgpt-linux/work-page.png)

    **Fill in the page**

    This example is for a mailbox at your own domain or a hosting company. For Gmail, Outlook and
    other kinds, see [Add your mailbox](#2-add-your-mailbox).

    1. Select **Any other mailbox**.
    2. Type your email address.
    3. Type your password. Type it only on this page, never in the chat.
    4. Select **Any other mailbox: server names**, and type your provider's **IMAP server** and
       **SMTP server**.
    5. Select **Add mailbox**. When the page says **Mailbox added**, go back to ChatGPT.

    ![The Add a mailbox form with example values, and each box to fill in highlighted](assets/screens/chatgpt-linux/form-example.png)

=== "Claude Code"

    1. Install uv once with the installer for your computer (see the ChatGPT tab), or
       [by hand](install.md#install-uv-by-hand).
    2. In a terminal, add the marketplace and install the plugin:

        ```bash
        claude plugin marketplace add skhan61/email-tool
        claude plugin install email-tool@email-tool
        ```

        ![Claude Code adds the email-tool marketplace](assets/screens/claude-marketplace.svg)

        ![Claude Code installs the email-tool plugin](assets/screens/claude-install.svg)

        Or type the same inside Claude Code: `/plugin marketplace add skhan61/email-tool`,
        then `/plugin install email-tool@email-tool`.
    3. Close Claude Code and open it again.

=== "Another app"

    Any app that supports the Model Context Protocol (MCP) can run email-tool.
    See [Advanced setup](install.md#connect-through-a-configuration-file-or-command).

## 2. Add your mailbox

In your app, type:

> add my mailbox

A page opens in your browser. It runs on your computer only. If your app shows a link
instead, open the link.

![The Add a mailbox page: choose the kind of mailbox, type the email address and, for Gmail, the password](assets/screens/setup-page.png){ width="560" }

1. Choose your kind of mailbox.
2. Type your email address.
3. Then, depending on the kind:
    - **Gmail:** type an App Password, not your Google password.
      [How to get an App Password](mailboxes.md#gmail).
    - **Outlook, Hotmail or Microsoft 365:** nothing more. After you select **Add mailbox**,
      Microsoft's sign-in page opens. Sign in and select **Accept**.
      At a university or company, Microsoft may say **Need admin approval**: your IT
      department must approve email-tool first. Send them the application ID
      `82731d7a-ac7f-4a5e-88d3-acce522f85ce`. If IT gives you its own app ID or a directory ID
      instead, type them under **Outlook or Microsoft 365 at a university or company**.
    - **Google Workspace at a company or school:** ask your IT department for the client file,
      or [create one](mailboxes.md#google-workspace).
    - **Any other mailbox:** type your password and, under **Any other mailbox: server names**,
      the server names from your provider.
4. Select **Add mailbox**. When the page says **Mailbox added**, go back to your app.

Your password never passes through the AI assistant. To add another mailbox, ask again.

## 3. Try it

- "Summarize my unread mail."
- "Draft a reply to the last message from Dana, with the report from my Downloads attached."
- "Send it." Your assistant asks you before it sends anything.

Something not working? See [Troubleshooting](troubleshooting.md).
