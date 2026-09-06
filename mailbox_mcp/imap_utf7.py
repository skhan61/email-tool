"""Decode IMAP modified UTF-7 folder names (RFC 3501 section 5.1.3).

Folder names arrive on the wire in a modified UTF-7 where `&` opens a
base64 run, `-` closes it, `&-` is a literal ampersand, and the base64
alphabet uses `,` in place of `/`. Without this, non-ASCII folder names show
up as unreadable fragments such as `&JxQ-`.
"""

from __future__ import annotations

import base64
from typing import Final

_SHIFT_IN: Final[str] = "&"
_SHIFT_OUT: Final[str] = "-"


def _decode_run(run: str) -> str:
    """Decode one base64 run from a modified UTF-7 name."""
    if not run:
        return _SHIFT_IN
    padded: str = run.replace(",", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        raw: bytes = base64.b64decode(padded)
        return raw.decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return _SHIFT_IN + run + _SHIFT_OUT


def _encode_run(run: str) -> str:
    """Encode one non-ASCII run into modified UTF-7."""
    raw: bytes = run.encode("utf-16-be")
    encoded: str = base64.b64encode(raw).decode("ascii").rstrip("=")
    return _SHIFT_IN + encoded.replace("/", ",") + _SHIFT_OUT


def encode(name: str) -> str:
    """Return `name` encoded as modified UTF-7, ready to send to the server.

    Inverse of `decode`, so a folder listed to the user can be selected again.
    """
    chunks: list[str] = []
    pending: list[str] = []
    for character in name:
        if character == _SHIFT_IN:
            if pending:
                chunks.append(_encode_run("".join(pending)))
                pending.clear()
            chunks.append(_SHIFT_IN + _SHIFT_OUT)
        elif "\x20" <= character <= "\x7e":
            if pending:
                chunks.append(_encode_run("".join(pending)))
                pending.clear()
            chunks.append(character)
        else:
            pending.append(character)
    if pending:
        chunks.append(_encode_run("".join(pending)))
    return "".join(chunks)


def decode(name: str) -> str:
    """Return `name` with every modified UTF-7 run decoded."""
    if _SHIFT_IN not in name:
        return name

    chunks: list[str] = []
    index: int = 0
    length: int = len(name)
    while index < length:
        character: str = name[index]
        if character != _SHIFT_IN:
            chunks.append(character)
            index += 1
            continue
        end: int = name.find(_SHIFT_OUT, index + 1)
        if end == -1:
            chunks.append(name[index:])
            break
        chunks.append(_decode_run(name[index + 1 : end]))
        index = end + 1
    return "".join(chunks)
