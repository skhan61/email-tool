"""Fuzz the text extraction of attached files (PDF, Word, Excel, PowerPoint, plain text).

Standard: Atheris (`atheris.Setup` + `atheris.Fuzz`), libFuzzer's coverage-guided engine for Python.
Placement: fuzz/, one target per file, run by .github/workflows/fuzz.yml.

`attachment_text` reads attachments from incoming mail for the CUI check. It returns "" for
a file it cannot read, so the bugs left to find are hangs and runaway memory, which libFuzzer's
`-timeout` and `-rss_limit_mb` report as crashes.
"""

from __future__ import annotations

import sys
from email.message import EmailMessage
from typing import Final

import atheris

with atheris.instrument_imports():
    from email_tool_mcp.attachments import attachment_text

# The first input byte picks the kind of file; the rest is its content.
_NAMES: Final[tuple[str, ...]] = ("file.pdf", "file.docx", "file.xlsx", "file.pptx", "file.txt", "file.bin")


def test_one_input(data: bytes) -> None:
    """Attach `data` under one of the names and extract its text."""
    if not data:
        return
    part: EmailMessage = EmailMessage()
    part.set_content(data[1:], maintype="application", subtype="octet-stream", filename=_NAMES[data[0] % len(_NAMES)])
    attachment_text(part)


def main() -> None:
    # The branches that matter sit in the standard library's parsers (email, zipfile) and in
    # pypdf; instrument them all so the fuzzer can see which inputs reach new code.
    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
