"""Minimal MCP server over line-delimited JSON-RPC on stdio.

stdout carries protocol frames only. Every diagnostic goes to stderr, because
anything printed to stdout would corrupt the stream.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Final, TextIO

from tools.base import Tool

logger: Final[logging.Logger] = logging.getLogger(__name__)

PROTOCOL_VERSION: Final[str] = "2024-11-05"
_METHOD_NOT_FOUND: Final[int] = -32601
_INTERNAL_ERROR: Final[int] = -32603
_PARSE_ERROR: Final[int] = -32700


class MailboxMcpServer:
    """Serve a fixed set of tools over the MCP stdio transport."""

    def __init__(self, server_name: str, version: str, tools: dict[str, Tool]) -> None:
        self._server_name: str = server_name
        self._version: str = version
        self._tools: dict[str, Tool] = tools

    def handle_initialize(self) -> dict[str, Any]:
        """Return the initialize result."""
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self._server_name, "version": self._version},
        }

    def handle_tools_list(self) -> dict[str, Any]:
        """Return every tool descriptor."""
        return {"tools": [tool.describe() for tool in self._tools.values()]}

    def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run one tool and wrap its result in MCP content."""
        tool_name: str = params.get("name", "")
        arguments: dict[str, Any] = params.get("arguments") or {}
        tool: Tool | None = self._tools.get(tool_name)
        if tool is None:
            return self._text_result(f"Unknown tool: {tool_name}", is_error=True)
        try:
            output: str = tool.run(arguments)
        except Exception as error:  # surfaced to the model, never crashes the server
            logger.exception("tool %s failed", tool_name)
            return self._text_result(f"{type(error).__name__}: {error}", is_error=True)
        return self._text_result(output, is_error=False)

    @staticmethod
    def _text_result(text: str, is_error: bool) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Route one request, returning a response or None for notifications."""
        method: str = request.get("method", "")
        request_id: Any = request.get("id")
        if request_id is None:
            logger.debug("notification received: %s", method)
            return None

        try:
            if method == "initialize":
                result: dict[str, Any] = self.handle_initialize()
            elif method == "tools/list":
                result = self.handle_tools_list()
            elif method == "tools/call":
                result = self.handle_tools_call(request.get("params") or {})
            elif method == "ping":
                result = {}
            else:
                return self._error(request_id, _METHOD_NOT_FOUND, f"Unknown method: {method}")
        except Exception as error:
            logger.exception("dispatch failed for %s", method)
            return self._error(request_id, _INTERNAL_ERROR, f"{type(error).__name__}: {error}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def serve(self, stream_in: TextIO = sys.stdin, stream_out: TextIO = sys.stdout) -> None:
        """Read requests until stdin closes."""
        logger.info("%s serving %d tools on stdio", self._server_name, len(self._tools))
        for raw_line in stream_in:
            line: str = raw_line.strip()
            if not line:
                continue
            try:
                request: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError as error:
                logger.error("malformed request: %s", error)
                self._emit(self._error(None, _PARSE_ERROR, str(error)), stream_out)
                continue
            response: dict[str, Any] | None = self.dispatch(request)
            if response is not None:
                self._emit(response, stream_out)
        logger.info("stdin closed, shutting down")

    @staticmethod
    def _emit(payload: dict[str, Any], stream_out: TextIO) -> None:
        stream_out.write(json.dumps(payload) + "\n")
        stream_out.flush()
