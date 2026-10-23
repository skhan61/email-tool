"""Start libFuzzer on one target, with every loaded module instrumented.

The branches that matter sit in the standard library's parsers (email, zipfile, codecs) and
in pypdf as much as in email_tool_mcp, so all of them report coverage to the fuzzer.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import atheris


def run(test_one_input: Callable[[bytes], None]) -> None:
    """Instrument every loaded module, then fuzz `test_one_input` with the command line's options."""
    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
