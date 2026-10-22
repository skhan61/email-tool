# email-tool and CMMC Level 2 (NIST SP 800-171 Rev. 2)

**Software is not CMMC certified; organizations are.** CMMC Level 2 assesses an
organization against the 110 security requirements of NIST SP 800-171 Rev. 2.
This page lists the requirements email-tool helps meet when AI agents use email,
how to show it to an assessor, and what remains the organization's job. Use it
when writing your System Security Plan (SSP).

## Scope

email-tool is a local MCP server that lets an AI agent (Claude, ChatGPT, Codex)
read, draft and send mail over IMAP/SMTP. It does not store mail; messages stay
on your mail server. It adds controls around what the agent may do. Your mail
system, the AI service, and the endpoints remain in your CMMC scope on their own
terms: if CUI flows through them, they must meet the requirements themselves
(for example Microsoft 365 GCC High for mail, and an AI service authorized for
CUI).

## Requirements it supports

| Requirement | What email-tool does | Evidence for the assessor | Still the organization's job |
|---|---|---|---|
| **3.1.1** Limit system access to authorized users and processes | Each mailbox is enrolled per user and machine (`email-tool-mcp add`, login checked); the agent uses only enrolled mailboxes, plus at most one mailbox an app (Claude Desktop) describes in its environment, which never replaces an enrolled one and which `allow_environment_mailbox = false` switches off | `email-tool-mcp list`; settings file per user; policy file | Account management on the mail server; who may install the tool; set `allow_environment_mailbox = false` |
| **3.1.2** Limit access to permitted transactions and functions | Administrator policy: `read_only`, `allowed_tools`; `require_approval` makes the human approve every send, delete and draft replacement in the app's own prompt, after seeing the delivered recipients and the whole message, or for a delete the headers of the message removed; the model cannot approve for itself | `/etc/email-tool/policy.toml`; `email-tool-mcp policy show <mailbox>`; audit outcomes `ok (approved by the user)` | Writing the policy; deciding which roles get which mailboxes |
| **3.1.3** Control the flow of CUI per approved authorizations | `cui_recipient_domains`: mail carrying a CUI marking (banner, portion mark or subject, per DoDI 5200.48) is refused unless every recipient is in an approved domain; `allowed_recipient_domains` limits all mail | Policy file; refusals in the audit log naming the marking | Marking CUI correctly; deciding the approved domains; unmarked CUI is not detected |
| **3.1.5** Employ least privilege | Most-restrictive combination of administrator and user policy: a user can tighten, never loosen. Rules keyed by mailbox address (`[mailboxes."you@company.com"]`) bind whatever name the account is enrolled under | `policy show` output | Keying administrator rules by address; least privilege on the mail accounts themselves |
| **3.3.1** Create and retain audit records | Every agent action is recorded before it runs and with its outcome: time, OS account, host, mailbox, tool, folder, UIDs, recipients | `email-tool-mcp audit path` (run with the same `EMAIL_TOOL_AUDIT_FILE` as the agent, if set); the JSON Lines file | Retention period and storage; forwarding to your SIEM |
| **3.3.2** Trace actions to individual users | Each record carries the OS account taken from the process credentials (not from `USER`/`LOGNAME`, which can be set freely) and the host | Audit records | Unique OS accounts (no shared logins) |
| **3.3.4** Alert on audit logging failure | Fails closed: if the "started" record cannot be written, the action is refused and the agent is told why | Refusal message; test `test_an_unwritable_log_refuses_the_action` | Monitoring and alerting on those refusals |
| **3.3.8** Protect audit information from modification and deletion | Records are HMAC-SHA256 chained with a key in the OS keyring, and the newest record is anchored there; `email-tool-mcp audit verify` detects edited, inserted, reordered or removed records | `audit verify` output | A copy off the machine against someone in full control of the account: `EMAIL_TOOL_AUDIT_SYSLOG` sends plain syslog (UDP or TCP), so point it at a local relay (rsyslog, syslog-ng) that forwards to the SIEM over TLS. If the target is down, the tool warns and keeps the local log |
| **3.5.10** Store and transmit only cryptographically protected passwords | Passwords of enrolled mailboxes live only in the OS keyring (Keychain, Credential Manager, Secret Service), never in this tool's files, arguments or logs, and are sent only inside TLS. Microsoft and Google mailboxes store no password: their sign-in (OAuth tokens, including the refresh token) is a per-user file readable only by its owner, encrypted with Fernet (AES-128-CBC + HMAC-SHA256), the key in the OS keyring. A mailbox an app describes in its environment gets its password from that app (`EMAIL_TOOL_PASSWORD`) | `email-tool-mcp list` shows "password in keyring" or "signed in to microsoft/google"; settings file holds no password or token | Set `allow_environment_mailbox = false` so no password comes from an app's config; keyring protection on the endpoint (disk encryption, screen lock) |
| **3.13.8** Protect CUI in transit with cryptography | IMAP and SMTP always use TLS with certificate verification, TLS 1.2 minimum. Microsoft and Google sign-in and token refresh use the same TLS context, minimum and network timeout | `email-tool-mcp check <mailbox>` shows the negotiated version and cipher for IMAP and SMTP; test `test_sign_in_traffic_uses_the_tls_floor_and_the_timeout` for sign-in | TLS on the mail server; the AI service's own transport |
| **3.13.11** Employ FIPS-validated cryptography for CUI | `require_fips = true` refuses every connection (agent calls, `add`, `check`) unless Python's OpenSSL runs in FIPS mode. A mailbox with a kept sign-in (Microsoft) is also refused, before its sign-in is read (listing included), unless the `cryptography` package that encrypts the sign-in runs on a FIPS provider (its PyPI wheels bundle their own OpenSSL, so this needs a FIPS build of `cryptography`) | `email-tool-mcp check` shows "FIPS mode: on" and, for a signed-in mailbox, "sign-in storage FIPS: on" | Running the OS in FIPS mode (e.g. Ubuntu Pro FIPS, RHEL FIPS) |

## Not covered

- **CUI at rest** (3.13.16): the tool stores no mail. The audit log holds no
  subjects or bodies, but does hold recipient addresses and message UIDs.
- **Identification and authentication of the person** (3.5.1 to 3.5.3, MFA):
  handled by the OS login and the mail provider.
- **The AI service**: what the model provider does with message content is
  outside this tool. Use a service authorized for the data you give it.
- **Unmarked CUI**: the CUI guard reads markings; it does not classify content.

## Configuration for a CMMC environment

Administrator file, `/etc/email-tool/policy.toml` on Linux (`email-tool-mcp policy
paths` shows the macOS and Windows location), writable only by administrators:

```toml
[default]
require_approval = true
require_fips = true
allow_environment_mailbox = false
allowed_recipient_domains = ["yourcompany.com", "prime-contractor.com"]
cui_recipient_domains = ["yourcompany.com"]

[mailboxes."shared-inbox@yourcompany.com"]   # keyed by address: binds under any name
read_only = true
```

Then set `EMAIL_TOOL_AUDIT_SYSLOG=udp://127.0.0.1:514` for the agent process,
with the local syslog daemon forwarding to your SIEM over TLS, and check each
machine with `email-tool-mcp check <mailbox>` and `email-tool-mcp audit verify`
(run in the same environment as the agent).
