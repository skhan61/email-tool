# Why CMMC

## The problem

Defense contractors that handle Controlled Unclassified Information (CUI) must meet
**CMMC Level 2** ([32 CFR Part 170](https://www.ecfr.gov/current/title-32/subtitle-A/chapter-I/subchapter-G/part-170)),
which assesses the 110 security requirements of
[NIST SP 800-171 Rev. 2](https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final).
Email is where much of that CUI travels.

An AI assistant with access to a mailbox can read, send and delete mail on its own. Without
controls at that point, an organization cannot show an assessor:

- what the assistant did, and on whose account;
- that it could only do what the organization allows;
- that a person approved each message before it left;
- that CUI-marked mail never went to an outside address;
- that the connection to the mail server was encrypted.

email-tool adds those controls where the assistant touches mail. Each section below shows
what you see. The [CMMC control mapping](cmmc.md) lists the evidence for an assessor and
what your organization still has to do.

## Every action is recorded

*NIST SP 800-171 3.3.1, 3.3.2, 3.3.4, 3.3.8*

email-tool writes a record before each action and another with its result. If it cannot
write the first record, it refuses the action. Records never hold subjects, message text or
passwords. For example, when the assistant sends a message:

```json
{"time": "2026-10-22T14:03:11.204+00:00", "user": "jdoe", "host": "eng-laptop-12", "call": "5f0c…", "phase": "started", "mailbox": "work", "tool": "send_email", "arguments": {"to": "lee@example.com"}, "previous": "9a41…", "mac": "c27e…"}
{"time": "2026-10-22T14:03:12.877+00:00", "user": "jdoe", "host": "eng-laptop-12", "call": "5f0c…", "phase": "finished", "mailbox": "work", "tool": "send_email", "outcome": "ok", "previous": "c27e…", "mac": "e810…"}
```

The records are chained with a key kept in the operating system's keyring, so an edited,
inserted or removed record is detected:

```text
$ email-tool-mcp audit verify
OK: 2 record(s), chain intact and matches the keyring.
```

To keep a copy off the computer, send the records to your security monitoring system
(SIEM) over syslog. See [For administrators](administrators.md#audit-log).

## The assistant does only what you allow

*NIST SP 800-171 3.1.1, 3.1.2, 3.1.5*

An administrator policy file limits what the assistant may do, for every mailbox or for
one. A user can tighten the rules on their own computer but never loosen them.

```toml
[default]
allowed_recipient_domains = ["example.com"]   # send and draft only to these domains

[mailboxes."archive@example.com"]
read_only = true                              # no send, draft or delete
```

When the assistant tries to email an outside address, it gets this answer, and the refusal
is recorded:

```text
policy: partner@gmail.com outside allowed_recipient_domains for 'work'
```

## A person approves before anything irreversible

*NIST SP 800-171 3.1.1, 3.1.2*

With `require_approval = true`, sending, deleting and replacing a draft wait for you. Your
app shows the actual recipients, the subject and the full message, and you select
**Accept** or **Decline**. The assistant cannot answer for you, and apps that cannot show
the question are refused.

## CUI-marked mail stays inside approved domains

*NIST SP 800-171 3.1.3*

email-tool reads the markings defined by
[DoD Instruction 5200.48](https://www.esd.whs.mil/Portals/54/Documents/DD/issuances/dodi/520048p.PDF)
and the [NARA CUI program](https://www.archives.gov/cui): a banner line such as
`CUI//SP-PROPIN`, a portion mark such as `(CUI)`, or a subject that starts with one. It
checks every text part, HTML included, and ignores look-alike and hidden characters.

With `cui_recipient_domains = ["example.com"]`, a message with this body:

```text
CUI//SP-PROPIN

Attached is the pricing for the next lot.
```

sent to `buyer@gmail.com` is refused:

```text
policy: the message carries CUI markings (banner: CUI//SP-PROPIN) and buyer@gmail.com are outside cui_recipient_domains
```

A sentence that only mentions CUI is not a marking. Marking CUI correctly remains your
organization's job.

## Mail is encrypted in transit

*NIST SP 800-171 3.13.8, 3.13.11*

Every connection uses TLS 1.2 or newer with certificate checks. This includes the Microsoft
and Google sign-in. You can see what a mailbox actually uses:

```text
$ email-tool-mcp check work
work (jdoe@example.com)
  IMAP outlook.office365.com:993  TLSv1.3 TLS_AES_256_GCM_SHA384  (login ok)
  SMTP smtp.office365.com:587  TLSv1.3 TLS_AES_256_GCM_SHA384  (login ok)
  minimum accepted: TLS 1.2   certificate verification: on   OpenSSL: OpenSSL 3.5.7 9 Jun 2026
  FIPS mode: on   sign-in storage FIPS: on
```

With `require_fips = true`, email-tool refuses to connect unless the cryptography in use is
FIPS 140 validated, which CMMC requires for CUI. FIPS mode is an operating system setting,
for example Ubuntu Pro FIPS or Red Hat Enterprise Linux in FIPS mode.

## Passwords never leave the keyring

*NIST SP 800-171 3.5.10*

Passwords go into the operating system's keyring and are never written to settings files,
command lines or logs. Microsoft and Google mailboxes store no password: their sign-in is
kept encrypted, with the key in the keyring.

## What email-tool does not do

Software is not CMMC certified; organizations are. email-tool supports the requirements
above. Your organization still sets the policy, marks CUI, protects the computers it runs
on, keeps the logs for the required time, and handles the rest of the 110 requirements.
The [CMMC Program](https://dodcio.defense.gov/CMMC/) site explains the assessment.
