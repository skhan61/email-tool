"""The single place that declares which tools this server exposes."""

from __future__ import annotations

from config import MailboxConfig
from tools.base import Tool
from tools.drafts import CreateDraft, GetDraft, ListDrafts, UpdateDraft
from tools.folders import ListFolders
from tools.messages import DeleteEmail, GetEmail, ListEmails, SearchEmails
from tools.outbound import SendEmail

_TOOL_CLASSES: tuple[type[Tool], ...] = (
    ListFolders,
    ListEmails,
    SearchEmails,
    GetEmail,
    DeleteEmail,
    CreateDraft,
    ListDrafts,
    GetDraft,
    UpdateDraft,
    SendEmail,
)


def build_tools(config: MailboxConfig) -> dict[str, Tool]:
    """Instantiate every tool for `config`, keyed by tool name."""
    tools: dict[str, Tool] = {}
    for tool_class in _TOOL_CLASSES:
        tool: Tool = tool_class(config)
        tools[tool.name] = tool
    return tools
