"""Tamper-evident record of every action an agent takes (NIST SP 800-171 3.3.1, 3.3.2).

Standard: append-only JSON Lines with a SHA-256 hash chain (each record carries the
previous record's hash), `filelock` for concurrent writers, and the stdlib
SysLogHandler for optional forwarding to a SIEM.
Placement: audit.py in the src layout; server.py calls `AuditLog.record` once per tool call.

A record names who, when, which mailbox and tool, the folder, UIDs and recipients,
and the outcome. It never holds a subject, a body or a password: those may carry CUI.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import logging.handlers
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from filelock import FileLock
from platformdirs import user_log_path

from email_tool_mcp.settings import APP_NAME

ENV_AUDIT_FILE: Final[str] = "EMAIL_TOOL_AUDIT_FILE"
ENV_AUDIT_SYSLOG: Final[str] = "EMAIL_TOOL_AUDIT_SYSLOG"
GENESIS: Final[str] = "0" * 64
# Arguments safe to record. Subjects, bodies and HTML are deliberately absent.
RECORDED_ARGUMENTS: Final[tuple[str, ...]] = ("folder", "uid", "to", "cc", "limit", "sender", "since")

logger: Final[logging.Logger] = logging.getLogger(__name__)


def default_audit_path() -> Path:
    """Return the per-user audit file location for this OS."""
    return user_log_path(APP_NAME, appauthor=False) / "audit.jsonl"


def record_hash(previous: str, body: Mapping[str, Any]) -> str:
    """Hash `body` together with the previous record's hash."""
    canonical: str = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()


def last_hash(path: Path) -> str:
    """Return the hash of the final record in `path`, or the genesis hash for an empty log."""
    if not path.is_file() or path.stat().st_size == 0:
        return GENESIS
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position: int = handle.tell()
        chunk: bytes = b""
        while position > 0 and chunk.count(b"\n") < 2:
            step: int = min(4096, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step) + chunk
    final_line: bytes = chunk.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    found: str = json.loads(final_line)["hash"]
    return found


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of checking a log's chain."""

    records: int
    broken_at: int | None
    reason: str

    def render(self) -> str:
        """One line a person can read."""
        if self.broken_at is None:
            return f"OK: {self.records} record(s), chain intact."
        return f"BROKEN at line {self.broken_at}: {self.reason}"


def verify(path: Path) -> VerifyResult:
    """Recompute every hash; report the first line edited, inserted or removed."""
    if not path.is_file():
        return VerifyResult(0, None, "")
    previous: str = GENESIS
    count: int = 0
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            try:
                record: dict[str, Any] = json.loads(line)
                stored: str = record.pop("hash")
            except (json.JSONDecodeError, KeyError):
                return VerifyResult(count, number, "not a valid audit record")
            if record.get("previous") != previous:
                return VerifyResult(count, number, "a record before it was removed or reordered")
            if record_hash(previous, record) != stored:
                return VerifyResult(count, number, "this record was edited")
            previous = stored
            count += 1
    return VerifyResult(count, None, "")


class AuditLog:
    """Appends one hash-chained record per tool call; optionally mirrors it to syslog."""

    def __init__(self, path: Path, syslog_address: str = "") -> None:
        self._path: Path = path
        self._lock: FileLock = FileLock(str(path) + ".lock")
        self._syslog: logging.Logger | None = None
        if syslog_address:
            host, _, port = syslog_address.partition(":")
            handler: logging.Handler = logging.handlers.SysLogHandler(address=(host, int(port or 514)))
            self._syslog = logging.getLogger(f"{APP_NAME}.audit")
            self._syslog.addHandler(handler)
            self._syslog.setLevel(logging.INFO)
            self._syslog.propagate = False

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> AuditLog:
        """Build from EMAIL_TOOL_AUDIT_FILE / EMAIL_TOOL_AUDIT_SYSLOG, defaulting to the user log folder."""
        path: Path = Path(environment.get(ENV_AUDIT_FILE, "") or default_audit_path())
        return cls(path, environment.get(ENV_AUDIT_SYSLOG, ""))

    @property
    def path(self) -> Path:
        """Where the records are written."""
        return self._path

    def ensure_writable(self) -> None:
        """Raise OSError unless a record could be appended now; callers refuse to act (fail closed)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._path.open("a", encoding="utf-8"):
            pass

    def record(self, mailbox: str, tool: str, arguments: Mapping[str, Any], outcome: str) -> None:
        """Append one record. `outcome` is "ok", or the error type and message."""
        body: dict[str, Any] = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "user": getpass.getuser(),
            "host": socket.gethostname(),
            "mailbox": mailbox,
            "tool": tool,
            "arguments": {key: arguments[key] for key in RECORDED_ARGUMENTS if arguments.get(key) not in (None, "")},
            "outcome": outcome,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            body["previous"] = last_hash(self._path)
            line: str = json.dumps({**body, "hash": record_hash(body["previous"], body)}, ensure_ascii=False)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if self._syslog is not None:
            self._syslog.info(line)
