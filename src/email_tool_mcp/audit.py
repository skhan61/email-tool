"""Tamper-evident record of every action an agent takes (NIST SP 800-171 3.3.1, 3.3.2, 3.3.4).

Standard: append-only JSON Lines chained with HMAC-SHA256 (stdlib `hmac`), the key
and the latest record's MAC held in the OS keyring (`keyring`), `filelock` for
concurrent writers, and the stdlib SysLogHandler for an off-machine copy.
Placement: audit.py in the src layout; server.py writes a "started" record before
each tool call and a "finished" record after it.

What it proves: anyone without the user's keyring cannot edit, insert, reorder or
remove records, or cut off the newest ones, without `verify` saying so. Someone
who controls the whole account can; the syslog copy is the defence against that.

A record names who, when, which mailbox and tool, the folder, UIDs and
recipients, and the outcome. It never holds a subject, a body or a password.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import secrets
import socket
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import SplitResult, urlsplit

import keyring
from filelock import FileLock
from platformdirs import user_log_path

from email_tool_mcp.settings import APP_NAME, SettingsError

ENV_AUDIT_FILE: Final[str] = "EMAIL_TOOL_AUDIT_FILE"
ENV_AUDIT_SYSLOG: Final[str] = "EMAIL_TOOL_AUDIT_SYSLOG"
KEYRING_SERVICE: Final[str] = f"{APP_NAME}-audit"
GENESIS: Final[str] = "0" * 64
logger: Final[logging.Logger] = logging.getLogger(__name__)
# Arguments safe to record. Subjects, bodies and HTML are deliberately absent.
RECORDED_ARGUMENTS: Final[tuple[str, ...]] = ("folder", "uid", "to", "cc", "limit", "sender", "since")


class AuditError(RuntimeError):
    """Raised when a record cannot be written; the caller must not act."""


@functools.cache
def os_account() -> str:
    """The account this process runs as, from its credentials, not from USER/LOGNAME (3.3.2).

    Computed once: the process account does not change. A POSIX uid with no passwd
    entry (common in containers) is recorded as `uid:<n>`, still from the credentials.
    """
    if sys.platform == "win32":
        import ctypes

        size: ctypes.c_ulong = ctypes.c_ulong(257)
        buffer: ctypes.Array[ctypes.c_wchar] = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):  # type: ignore[attr-defined]
            return str(buffer.value)
        raise OSError("GetUserNameW failed")
    import pwd

    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return f"uid:{os.getuid()}"


def default_audit_path() -> Path:
    """Return the per-user audit file location for this OS."""
    return user_log_path(APP_NAME, appauthor=False) / "audit.jsonl"


def audit_key(path: Path) -> bytes:
    """Return this log's HMAC key from the keyring, creating it on first use."""
    stored: str | None = keyring.get_password(KEYRING_SERVICE, f"key:{path}")
    if stored is None:
        stored = secrets.token_hex(32)
        keyring.set_password(KEYRING_SERVICE, f"key:{path}", stored)
    return bytes.fromhex(stored)


def record_mac(key: bytes, previous: str, body: Mapping[str, Any]) -> str:
    """MAC `body` together with the previous record's MAC."""
    canonical: str = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key, (previous + canonical).encode("utf-8"), hashlib.sha256).hexdigest()


def anchored_head(path: Path) -> str:
    """The MAC of the newest record, as last written to the keyring."""
    return keyring.get_password(KEYRING_SERVICE, f"head:{path}") or GENESIS


def final_line(path: Path) -> bytes:
    """Return the last line of `path` without reading the whole file."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position: int = handle.tell()
        chunk: bytes = b""
        while position > 0 and chunk.rstrip(b"\n").count(b"\n") < 1:
            step: int = min(4096, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step) + chunk
    return chunk.rstrip(b"\n").rsplit(b"\n", 1)[-1]


def parse_record(line: str | bytes) -> dict[str, Any] | None:
    """Return the record on `line`, or None when it is not one."""
    try:
        record: Any = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("mac"), str):
        return None
    return record


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of checking a log's chain."""

    records: int
    broken_at: int | None
    reason: str

    def render(self) -> str:
        """One line a person can read."""
        if self.broken_at is None and self.reason:
            return self.reason
        if self.broken_at is None:
            return f"OK: {self.records} record(s), chain intact and matches the keyring."
        return f"BROKEN at line {self.broken_at}: {self.reason}"


def verify(path: Path) -> VerifyResult:
    """Recompute every MAC and compare the newest one with the keyring anchor."""
    head: str = anchored_head(path)
    if not path.is_file():
        if head != GENESIS:
            return VerifyResult(0, 1, "the log file is missing")
        return VerifyResult(0, None, f"No audit log at {path} yet: nothing has been recorded there.")
    key: bytes = audit_key(path)
    previous: str = GENESIS
    count: int = 0
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            record: dict[str, Any] | None = parse_record(line)
            if record is None:
                return VerifyResult(count, number, "not a valid audit record")
            stored: str = record.pop("mac")
            if record.get("previous") != previous:
                return VerifyResult(count, number, "a record before it was removed or reordered")
            if not hmac.compare_digest(record_mac(key, previous, record), stored):
                return VerifyResult(count, number, "this record was edited")
            previous = stored
            count += 1
    if previous != head:
        return VerifyResult(count, count + 1, "the newest record(s) were removed")
    return VerifyResult(count, None, "")


def syslog_target(address: str) -> tuple[str, int, socket.SocketKind]:
    """Parse `host:port`, `udp://host:port` or `tcp://host:port`; SettingsError when malformed."""
    target: SplitResult = urlsplit(address if "://" in address else f"udp://{address}")
    if target.scheme not in ("udp", "tcp") or not target.hostname:
        raise SettingsError(f"{ENV_AUDIT_SYSLOG}={address!r}: use host:port, udp://host:port or tcp://host:port")
    try:
        port: int = target.port or 514
    except ValueError as error:
        raise SettingsError(f"{ENV_AUDIT_SYSLOG}={address!r}: the port is not a number") from error
    transport: socket.SocketKind = socket.SOCK_STREAM if target.scheme == "tcp" else socket.SOCK_DGRAM
    return target.hostname, port, transport


def syslog_handler(address: str) -> logging.Handler:
    """Open a SysLogHandler to `address`; OSError when the target cannot be reached now."""
    target: tuple[str, int, socket.SocketKind] = syslog_target(address)
    return logging.handlers.SysLogHandler(address=(target[0], target[1]), socktype=target[2])


class AuditLog:
    """Writes one MAC-chained record before and one after each tool call."""

    def __init__(self, path: Path, syslog_address: str = "") -> None:
        self._path: Path = path
        self._lock: FileLock = FileLock(str(path) + ".lock")
        self._syslog_address: str = syslog_address
        self._syslog: logging.Handler | None = None
        if syslog_address:
            syslog_target(syslog_address)  # a malformed address is a settings error at once
            self._connect_syslog()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], with_syslog: bool) -> AuditLog:
        """Build from EMAIL_TOOL_AUDIT_FILE / EMAIL_TOOL_AUDIT_SYSLOG, defaulting to the user log folder."""
        path: Path = Path(environment.get(ENV_AUDIT_FILE, "") or default_audit_path())
        return cls(path, environment.get(ENV_AUDIT_SYSLOG, "") if with_syslog else "")

    def _connect_syslog(self) -> None:
        """(Re)open the syslog copy; a target that is down is retried on the next record."""
        try:
            self._syslog = syslog_handler(self._syslog_address)
        except OSError as error:
            self._syslog = None
            logger.warning("audit copy to %s unavailable, retrying on the next record: %s", self._syslog_address, error)

    @property
    def path(self) -> Path:
        """Where the records are written."""
        return self._path

    def started(self, mailbox: str, tool: str, arguments: Mapping[str, Any]) -> str:
        """Record that a call is about to run and return its id; raise AuditError if it cannot be recorded."""
        call: str = uuid.uuid4().hex
        self._append({"call": call, "phase": "started", "mailbox": mailbox, "tool": tool, "arguments": arguments})
        return call

    def finished(self, call: str, mailbox: str, tool: str, outcome: str) -> None:
        """Record how call `call` ended; `outcome` is "ok" or the error type and message."""
        self._append({"call": call, "phase": "finished", "mailbox": mailbox, "tool": tool, "outcome": outcome})

    def _append(self, fields: dict[str, Any]) -> None:
        arguments: Mapping[str, Any] = fields.pop("arguments", {})
        try:
            account: str = os_account()
        except Exception as error:
            raise AuditError(f"cannot tell which OS account is running: {error}") from error
        body: dict[str, Any] = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "user": account,
            "host": socket.gethostname(),
            **fields,
        }
        if fields["phase"] == "started":
            body["arguments"] = {
                key: arguments[key] for key in RECORDED_ARGUMENTS if arguments.get(key) not in (None, "")
            }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                key: bytes = audit_key(self._path)
                previous: str = anchored_head(self._path)
                if self._path.is_file() and self._path.stat().st_size > 0:
                    last: dict[str, Any] | None = parse_record(final_line(self._path))
                    if last is None or last["mac"] != previous:
                        raise AuditError("the log does not match its keyring anchor; run `email-tool-mcp audit verify`")
                body["previous"] = previous
                mac: str = record_mac(key, previous, body)
                line: str = json.dumps({**body, "mac": mac}, ensure_ascii=False)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                keyring.set_password(KEYRING_SERVICE, f"head:{self._path}", mac)
        except AuditError:
            raise
        except Exception as error:
            raise AuditError(f"cannot write the audit log {self._path}: {error}") from error
        if self._syslog_address and self._syslog is None:
            self._connect_syslog()
        if self._syslog is not None:
            self._syslog.handle(logging.makeLogRecord({"msg": line, "levelno": logging.INFO, "levelname": "INFO"}))
