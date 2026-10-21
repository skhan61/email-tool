# Security

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/skhan61/email-tool/security/advisories/new).
Do not open a public issue. Expect a reply within 7 days.

## What this tool protects

- Passwords are never stored in this repository, in agent config files, or on the command line.
- TLS certificate verification is always on for IMAP and SMTP and cannot be turned off.
- The server runs locally over stdio. It never listens on a network port.
