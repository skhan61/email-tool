"""Entry point for the mailbox MCP server.

    python3 mailbox_mcp/__main__.py \
        --label gmail \
        --imap-host imap.gmail.com --imap-port 993 \
        --imap-user you@gmail.com \
        --smtp-host smtp.gmail.com --smtp-port 465 \
        --secrets-file ~/.config/claude-secrets.env \
        --password-key GMAIL_APP_PASSWORD
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MailboxConfig, parse_config  # noqa: E402
from jsonrpc_server import MailboxMcpServer  # noqa: E402
from tools.base import Tool  # noqa: E402
from tools.registry import build_tools  # noqa: E402

VERSION: Final[str] = "2.0.0"


def configure_logging() -> None:
    """Send all logging to stderr so stdout stays a clean protocol stream."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str]) -> int:
    """Build the server from `argv` and serve until stdin closes."""
    configure_logging()
    logger: logging.Logger = logging.getLogger("mailbox_mcp")
    try:
        config: MailboxConfig = parse_config(argv)
    except (FileNotFoundError, KeyError) as error:
        logger.error("cannot resolve credentials: %s", error)
        return 2

    tools: dict[str, Tool] = build_tools(config)
    server: MailboxMcpServer = MailboxMcpServer(
        server_name=f"mailbox-mcp:{config.label}",
        version=VERSION,
        tools=tools,
    )
    server.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
