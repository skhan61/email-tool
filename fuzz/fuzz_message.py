"""Fuzz the parsing of incoming messages (body, attachments, reply headers) and the CUI check.

Standard: Atheris (`atheris.Setup` + `atheris.Fuzz`), libFuzzer's coverage-guided engine for Python.
Placement: fuzz/, one target per file, run by .github/workflows/fuzz.yml.

Every function here reads text a stranger can shape, and none may raise on it, except
`thread_headers`, which refuses a parent without a Message-ID with ValueError by design.
Incoming mail is parsed as the read tools parse it (`parse_message`, the classic parser);
the CUI check runs on text an outgoing message carries, which an incoming email can steer.
"""

from __future__ import annotations

import sys
from email.message import Message

import atheris

with atheris.instrument_imports():
    from email_tool_mcp.cui import markings, tag_lines
    from email_tool_mcp.message_compose import message_ids, thread_headers
    from email_tool_mcp.message_render import (
        attachment_names,
        every_text,
        extract_body,
        header_block,
        parse_message,
    )


def test_one_input(data: bytes) -> None:
    """Parse `data` as the read tools parse mail, and check it as the CUI guard checks text."""
    message: Message = parse_message(data)
    extract_body(message)
    every_text(message)
    header_block(message)
    attachment_names(message)
    message_ids(message.get("References"))
    try:
        thread_headers(message)
    except ValueError:
        pass
    text: str = data.decode("utf-8", "replace")
    markings(text[:200], text)
    tag_lines(text)


def main() -> None:
    # The branches that matter sit in the standard library's parsers (email, zipfile) and in
    # pypdf; instrument them all so the fuzzer can see which inputs reach new code.
    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
