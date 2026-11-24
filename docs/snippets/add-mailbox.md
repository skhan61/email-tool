<!-- Standard: pymdownx.snippets, one copy of the add-mailbox steps for every app tab of start.md but ChatGPT's (which has pictures).
Placement: docs/snippets/, left out of the site by exclude_docs; image paths are relative to docs/start.md. -->

In your app, type:

> add my mailbox

A page opens in your browser. It runs on your computer only. If your app shows a link
instead, open the link.

![The Add a mailbox page, with the kind of mailbox, the email address, the password and the Add mailbox button highlighted](assets/screens/setup-page.png){ width="560" }

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
