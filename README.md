<p align="center"><img src="assets/icon.png" alt="email-tool icon" width="112"></p>

<h1 align="center">email-tool</h1>

<p align="center"><b>Email for any AI agent that speaks MCP: Claude Code, Claude Desktop, Cowork, ChatGPT desktop, Codex and others.</b><br>
Read, search, draft and send mail over IMAP/SMTP.</p>

<p align="center">
  <b>Works with</b><br>
  <a href="https://skhan61.github.io/email-tool/install/"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude%20Code-plugin-D97757?logo=claude&logoColor=white"></a>
  <a href="https://skhan61.github.io/email-tool/install/"><img alt="Claude Desktop and Cowork" src="https://img.shields.io/badge/Claude%20Desktop%20%2F%20Cowork-.mcpb-D97757?logo=claude&logoColor=white"></a>
  <a href="https://skhan61.github.io/email-tool/install/"><img alt="ChatGPT desktop and Codex" src="https://img.shields.io/badge/ChatGPT%20desktop%20%2F%20Codex-plugin-10A37F"></a>
  <a href="https://modelcontextprotocol.io"><img alt="MCP server" src="https://img.shields.io/badge/MCP-server-1F2A44"></a>
</p>

<p align="center">
  <b>Compliance</b><br>
  <a href="https://skhan61.github.io/email-tool/cmmc/"><img alt="CMMC Level 2 / NIST SP 800-171 control mapping" src="https://img.shields.io/badge/CMMC%20L2%20%2F%20NIST%20SP%20800--171-control%20mapping-2B5797"></a>
</p>

<p align="center">
  <b>Build and security</b><br>
  <a href="https://github.com/skhan61/email-tool/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/skhan61/email-tool/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/skhan61/email-tool/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/skhan61/email-tool/actions/workflows/codeql.yml/badge.svg?branch=main"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/skhan61/email-tool"><img alt="OpenSSF Scorecard" src="https://img.shields.io/ossf-scorecard/github.com/skhan61/email-tool?label=OpenSSF%20Scorecard"></a>
  <a href="https://github.com/skhan61/email-tool/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/skhan61/email-tool?label=release&logo=github"></a>
</p>

<p align="center">
  <b>Code quality</b><br>
  <a href="pyproject.toml"><img alt="Python version" src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fskhan61%2Femail-tool%2Fmain%2Fpyproject.toml&logo=python&logoColor=white"></a>
  <a href=".github/workflows/ci.yml"><img alt="Tested on Linux, macOS and Windows" src="https://img.shields.io/badge/tested%20on-Linux%20%7C%20macOS%20%7C%20Windows-555"></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
  <a href="pyproject.toml"><img alt="mypy strict" src="https://img.shields.io/badge/types-mypy%20strict-2A6DB2"></a>
  <a href="https://github.com/astral-sh/uv"><img alt="uv" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json"></a>
  <a href=".pre-commit-config.yaml"><img alt="pre-commit" src="https://img.shields.io/badge/pre--commit-enabled-FAB040?logo=pre-commit&logoColor=white"></a>
  <a href=".github/dependabot.yml"><img alt="Dependabot" src="https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white"></a>
</p>

<p align="center">
  <b>Project</b><br>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/skhan61/email-tool"></a>
  <a href="SECURITY.md"><img alt="Security policy" src="https://img.shields.io/badge/security-policy-C0392B"></a>
  <a href="CONTRIBUTING.md"><img alt="Contributing" src="https://img.shields.io/badge/PRs-welcome-2EA44F"></a>
</p>

email-tool lets an AI assistant read, search, draft and send your email. It runs on your
own computer, keeps passwords in your operating system's keyring, and is built for
organizations under CMMC Level 2 and NIST SP 800-171: every action is logged, sending can
wait for your approval, and CUI-marked mail stays inside the domains you allow.

**Documentation: [skhan61.github.io/email-tool](https://skhan61.github.io/email-tool/)**

## Quick start

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Connect your AI app. In Claude Code:

    ```text
    /plugin marketplace add skhan61/email-tool
    /plugin install email-tool@email-tool
    ```

    Other apps: [Install](https://skhan61.github.io/email-tool/install/).
3. Add a mailbox:

    ```bash
    uv tool install git+https://github.com/skhan61/email-tool
    email-tool-mcp add work --auth microsoft --address you@company.com
    ```

    Gmail, Google Workspace and other accounts: [Add your mailboxes](https://skhan61.github.io/email-tool/mailboxes/).

## Documentation

| Page | What it covers |
|---|---|
| [Install](https://skhan61.github.io/email-tool/install/) | uv, then Claude Code, Claude Desktop and Cowork, ChatGPT desktop and Codex, ChatGPT Business, any MCP app |
| [Add your mailboxes](https://skhan61.github.io/email-tool/mailboxes/) | Outlook, Microsoft 365, GCC High, Gmail, Google Workspace and password mailboxes, step by step |
| [Everyday use](https://skhan61.github.io/email-tool/use/) | What to ask, the tools, approving before sending |
| [Why CMMC](https://skhan61.github.io/email-tool/why-cmmc/) | Each protection, with examples |
| [CMMC control mapping](https://skhan61.github.io/email-tool/cmmc/) | NIST SP 800-171 requirements, evidence and your part |
| [For administrators](https://skhan61.github.io/email-tool/administrators/) | Policy, audit log, FIPS mode, your own Microsoft or Google app |
| [Troubleshooting](https://skhan61.github.io/email-tool/troubleshooting/) | Every message and its fix |
| [Privacy](https://skhan61.github.io/email-tool/privacy/) | What email-tool accesses and where it goes |

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
