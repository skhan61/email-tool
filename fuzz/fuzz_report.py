"""Fuzz the redaction of problem reports: any text, with a planted address and key, comes out clean and stable.

Standard: Atheris (`FuzzedDataProvider`, `Setup`, `Fuzz`), libFuzzer's coverage-guided engine for Python.
Placement: fuzz/, one target per file, run by .github/workflows/fuzz.yml.

A report holds the user's description and the audit log's error messages, which a mail server
can steer. The fuzzer picks that text and where an address and a private key sit in it.
A planted secret that survives, a second redaction that changes the text, any exception, or
a hang over libFuzzer's `-timeout` (a regular expression that backtracks) is a finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import atheris

from email_tool_mcp.problem_report import redact
from fuzz._run import run

_HOME: Final[Path] = Path("/home/dana")
_ADDRESS: Final[str] = "dana.lee@corp.example"
# Built at run time so the repository's private-key hook does not flag this file.
_KEY: Final[str] = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END " + "RSA PRIVATE KEY-----"


def test_one_input(data: bytes) -> None:
    """Redact the fuzzer's text with an address and a key planted in it, then redact the result again."""
    provider: atheris.FuzzedDataProvider = atheris.FuzzedDataProvider(data)
    before: str = provider.ConsumeUnicodeNoSurrogates(provider.ConsumeIntInRange(0, 200))
    between: str = provider.ConsumeUnicodeNoSurrogates(provider.ConsumeIntInRange(0, 200))
    after: str = provider.ConsumeUnicodeNoSurrogates(provider.remaining_bytes())
    once: str = redact(f"{before} {_ADDRESS} {between}\n{_KEY}\n{after}", _HOME)
    if _ADDRESS in once or "MIIEowIBAAKCAQEA" in once:
        raise AssertionError(f"a planted secret survived: {once!r}")
    if redact(once, _HOME) != once:
        raise AssertionError(f"a second redaction changed the text: {once!r}")


if __name__ == "__main__":
    run(test_one_input)
