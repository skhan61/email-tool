"""Base class every mailbox tool implements.

Adding a tool means adding one subclass in this folder and registering it in
`registry.py`. Nothing else in the server changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from config import MailboxConfig
from imap_session import ImapSession


class Tool(ABC):
    """One MCP tool bound to one mailbox."""

    def __init__(self, config: MailboxConfig) -> None:
        self._config: MailboxConfig = config

    @property
    @abstractmethod
    def name(self) -> str:
        """The tool name exposed over MCP."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description shown to the model."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for this tool's arguments."""

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> str:
        """Execute the tool and return its textual result."""

    def open_session(self) -> ImapSession:
        """Return a fresh, unopened IMAP session for this mailbox."""
        return ImapSession(self._config)

    def describe(self) -> dict[str, Any]:
        """Return this tool's MCP descriptor."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
