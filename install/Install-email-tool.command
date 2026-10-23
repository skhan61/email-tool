#!/bin/bash
# email-tool setup for ChatGPT desktop and Codex on macOS: installs uv, which runs email-tool.
# The same command as the documentation's Install page, so nothing needs typing.
echo "Installing uv, the program that runs email-tool. This takes about a minute."
echo
if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
  echo
  echo "The installation did not finish. See https://skhan61.github.io/email-tool/troubleshooting/"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
echo
echo "Done. Next, in the ChatGPT desktop app:"
echo "  1. Select Plugins, then Add Marketplace, and type skhan61/email-tool"
echo "  2. Install email-tool, then quit ChatGPT (Command-Q) and open it again"
echo "  3. In Work or Codex mode, ask: add my mailbox"
echo
read -n 1 -s -r -p "Press any key to close."
