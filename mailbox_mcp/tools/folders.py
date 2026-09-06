"""Folder-level tools."""

from __future__ import annotations

from typing import Any

from tools.base import Tool


class ListFolders(Tool):
    """Expose every folder on the server."""

    @property
    def name(self) -> str:
        return "list_folders"

    @property
    def description(self) -> str:
        return "List every folder in the mailbox."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, arguments: dict[str, Any]) -> str:
        with self.open_session() as session:
            names: list[str] = session.list_folders()
        if not names:
            return "No folders found."
        return "\n".join(sorted(names))
