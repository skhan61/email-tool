"""Fuzz the text extraction of attached files: PDF, Office, HTML, CSV and plain text, in any charset.

Standard: Atheris (`FuzzedDataProvider`, `Setup`, `Fuzz`), libFuzzer's coverage-guided engine for Python.
Placement: fuzz/, one target per file, run by .github/workflows/fuzz.yml.

`attachment_text` reads attachments for the CUI check. The fuzzer picks the file name, the
content type and the charset the sender declares (an unknown one included), as an incoming
message can; any exception but `UnreadableAttachment` (#127, by design), a hang over
libFuzzer's `-timeout` or memory over `-rss_limit_mb` is a finding.
"""

from __future__ import annotations

import base64
from contextlib import suppress
from email import message_from_bytes
from email.message import Message
from typing import Final

import atheris

from email_tool_mcp.attachments import UnreadableAttachment, attachment_text
from fuzz._run import run

_NAMES: Final[tuple[str, ...]] = (
    "file.pdf",
    "file.docx",
    "file.docm",
    "file.xlsx",
    "file.xlsm",
    "file.pptx",
    "file.pptm",
    "file.txt",
    "file.csv",
    "file.md",
    "file.html",
    "file.htm",
    "file.bin",
)
_TYPES: Final[tuple[str, ...]] = ("application/octet-stream", "text/plain", "text/html", "application/pdf")
_CHARSETS: Final[tuple[str, ...]] = ("", "utf-8", "latin-1", "utf-16", "iso-2022-jp", "bogus")


def test_one_input(data: bytes) -> None:
    """Build an attached part the way a sender could, then extract its text."""
    provider: atheris.FuzzedDataProvider = atheris.FuzzedDataProvider(data)
    name: str = _NAMES[provider.ConsumeIntInRange(0, len(_NAMES) - 1)]
    kind: str = _TYPES[provider.ConsumeIntInRange(0, len(_TYPES) - 1)]
    charset: str = _CHARSETS[provider.ConsumeIntInRange(0, len(_CHARSETS) - 1)]
    content: bytes = provider.ConsumeBytes(provider.remaining_bytes())
    declared: str = f"; charset={charset}" if charset else ""
    raw: bytes = (
        f'Content-Type: {kind}{declared}\r\nContent-Disposition: attachment; filename="{name}"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n"
    ).encode() + base64.encodebytes(content)
    part: Message = message_from_bytes(raw)
    with suppress(UnreadableAttachment):  # refused by design (#127), not a crash
        attachment_text(part)


if __name__ == "__main__":
    run(test_one_input)
