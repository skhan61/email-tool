"""The setup tool: add a mailbox through a page in the user's browser, never through the assistant.

Standard: tool methods with typed signatures, registered on the MCP SDK's MCPServer.
Placement: tools/setup.py, one module per tool group.
"""

from __future__ import annotations

from email_tool_mcp.setup_page import SetupPage


class SetupTools:
    """The one tool that adds mailboxes."""

    def __init__(self, page: SetupPage) -> None:
        self._page: SetupPage = page

    def add_mailbox(self) -> str:
        """Open a setup page in the user's browser to add a mailbox: Gmail, Outlook or Microsoft 365, Google
        Workspace, or any other. The user types any password on that page only; never ask for it in the chat.
        """
        return self._page.start()
