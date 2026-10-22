# email-tool privacy policy

email-tool is open-source software that runs on your own computer. It lets an AI
assistant you choose read, draft and send email from mailboxes you add.

## What it accesses

- **Your mail**, over IMAP and SMTP, only when your AI assistant calls one of its tools.
- **Your sign-in** with Google or Microsoft, when you add a mailbox that uses one. It
  asks for full mail access (`https://mail.google.com/` for Google, `IMAP.AccessAsUser.All`
  and `SMTP.Send` for Microsoft) and your email address, because IMAP and SMTP need it.

## Where your data goes

- Nothing is sent to the developers of email-tool. There is no server, analytics or
  telemetry.
- Passwords stay in your operating system's keyring. Google and Microsoft sign-ins are
  kept on your computer, encrypted, with the key in your keyring.
- Mail goes only between your computer and your mail provider, over TLS 1.2 or newer,
  and to the AI assistant you connected, under that assistant's own terms.
- The optional audit log stays on your computer (or your own syslog server) and holds
  no subjects or message bodies.

## Removing access

`email-tool-mcp remove <name>` deletes a mailbox's password or sign-in from your
computer. You can also revoke access at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions) or
[account.live.com/consent/Manage](https://account.live.com/consent/Manage).

## Google user data

email-tool's use and transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

## Contact

Sayem Khan, sayem.eee.kuet@gmail.com, or an issue at
[github.com/skhan61/email-tool](https://github.com/skhan61/email-tool/issues).
