# For administrators

## Policy

Two policy files share one format. The **administrator file** applies to everyone on the
computer; each user's own **user file** can add rules. The most restrictive combination
applies, so a user can tighten the administrator's policy but never loosen it.

```bash
email-tool-mcp policy paths          # where both files are
email-tool-mcp policy show work      # the rules that apply to one mailbox
```

The administrator file is `/etc/email-tool/policy.toml` on Linux and
`/Library/Application Support/email-tool/policy.toml` on macOS. Run
`email-tool-mcp policy paths` to see it on Windows. Changes apply on the next
action, without a restart.

```toml
[default]                                    # every mailbox
allowed_recipient_domains = ["example.com"]  # send and draft only to these domains
require_approval = true                      # send, delete and replace-draft ask the user first
cui_recipient_domains = ["example.com"]      # CUI-marked mail only to these domains
require_fips = true                          # refuse unless FIPS mode is on
allow_environment_mailbox = false            # ignore a mailbox an app passes in its settings

[mailboxes."archive@example.com"]            # by address: applies under any mailbox name
read_only = true                             # no send, draft or delete

[mailboxes.work]                             # by name (not case sensitive)
allowed_tools = ["list_emails", "search_emails", "get_email", "create_draft"]
```

| Setting | Effect |
|---|---|
| `read_only` | Refuses sending, drafts and deleting. |
| `allowed_tools` | Allows only the listed tools. |
| `allowed_recipient_domains` | Allows sending and drafts only to these domains. |
| `require_approval` | The user approves each send, delete and draft replacement in the app. |
| `cui_recipient_domains` | Allows CUI-marked mail only to these domains. |
| `require_fips` | Refuses every connection unless FIPS-validated cryptography is in use. |
| `allow_environment_mailbox` | With `false`, ignores a mailbox that an app describes in its own settings. |

Key rules by address (`[mailboxes."you@example.com"]`): a rule keyed by name stops applying
if the user adds the same account under another name. If an existing policy file cannot be
read, every action is refused.

`cui_recipient_domains` also reads attachments: text, CSV, Markdown, HTML, Word (.docx) and
PDF files. The audit log records each attachment's name, size and SHA-256 fingerprint, never
its contents. Saving an attachment changes no mail, so `read_only` allows it.

Every refusal names the rule and is recorded in the audit log. Recipients are checked on the
finished message, which is the list the mail server receives.

!!! note
    The policy stops the assistant and accidental loosening. A user with full control of
    their own computer can run other software, so manage the installation centrally where
    that matters.

## Audit log

```bash
email-tool-mcp audit path      # where the log is
email-tool-mcp audit verify    # check that no record was edited, added, reordered or removed
```

| Variable | Effect |
|---|---|
| `EMAIL_TOOL_AUDIT_FILE` | Moves the log to this file. |
| `EMAIL_TOOL_AUDIT_SYSLOG` | Also sends each record over syslog: `tcp://siem.example.com:6514`, `udp://host:514` or `host:port`. |

Syslog is sent as plain text. Point it at a local relay such as rsyslog or syslog-ng that
forwards to your SIEM over TLS. If the syslog target is down, email-tool warns and keeps
the local log. email-tool never deletes records; keep them as long as your policy requires.

## FIPS mode

`require_fips = true` needs FIPS mode in the operating system, for example Ubuntu Pro FIPS
or Red Hat Enterprise Linux in FIPS mode. `email-tool-mcp check <mailbox>` reports it.
Microsoft and Google mailboxes also need a FIPS build of the Python `cryptography` package,
because its standard downloads include their own OpenSSL. Where that is not available,
use password mailboxes.

## Your own Microsoft app

email-tool signs in with its own Microsoft app by default. Your organization can register
its own app instead, and GCC High always needs one:

1. In the [Microsoft Entra admin center](https://entra.microsoft.com) (for GCC High, your
   GCC High portal), go to **App registrations** > **New registration**.
2. **Name:** `email-tool`. **Supported account types:** your organization only, or as you
   need.
3. **Redirect URI:** choose **Public client/native (mobile & desktop)** and enter
   `http://localhost`. Select **Register**.
4. Go to **Authentication**, set **Allow public client flows** to **Yes**, and select
   **Save**. Users need this for `--device-code`.
5. To approve the app for everyone ahead of time, go to **API permissions** > **Add a
   permission**, search for and add the delegated permissions `IMAP.AccessAsUser.All` and
   `SMTP.Send`, then select **Grant admin consent**. Without this step, each user approves
   the app at their first sign-in, if your organization allows that.
6. Give users the **Application (client) ID** from **Overview**. They add
   `--client-id <id>` (and `--cloud gcc-high` for GCC High).

To approve email-tool's default app for your organization instead, grant admin consent to
application ID `82731d7a-ac7f-4a5e-88d3-acce522f85ce`.

IMAP and authenticated SMTP must also be turned on for each mailbox in Exchange.

## Your own Google client

For Google Workspace, create the client once for everyone with **Audience: Internal**
(follow [Create the sign-in client](mailboxes.md#create-the-sign-in-client)). An Internal
client shows no warning, has no user limit, and needs no publishing. Share the downloaded
client file with your users through a channel you trust.

If your organization restricts third-party apps, allow the client under **Security** >
**API controls** in the Google Admin console.
