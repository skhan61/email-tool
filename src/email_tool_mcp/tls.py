"""The one place TLS is configured (NIST SP 800-171 3.13.8, 3.13.11).

Standard: the stdlib `ssl` module: `ssl.create_default_context()` (certificate and
hostname verification, SNI) with the floor raised explicitly to TLS 1.2, as NIST
SP 800-52 Rev. 2 requires; the default floor is whatever the OS OpenSSL allows.
FIPS state comes from CPython's `_hashlib.get_fips_mode()`, which reports whether
the OpenSSL it is linked to runs its FIPS provider.
Placement: tls.py; imap_session.py and mailbox_book.py take every context from here.
"""

from __future__ import annotations

import ssl


def client_context() -> ssl.SSLContext:
    """A verifying client context that refuses anything older than TLS 1.2."""
    context: ssl.SSLContext = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def fips_enabled() -> bool:
    """True when Python's OpenSSL runs in FIPS mode (FIPS 140 validated module in use)."""
    try:
        import _hashlib  # CPython's binding to OpenSSL's hashing; the only stdlib view of FIPS mode

        return bool(_hashlib.get_fips_mode())
    except (ImportError, AttributeError, ValueError):
        return False


def socket_details(sock: ssl.SSLSocket) -> str:
    """Protocol and cipher a TLS socket negotiated, e.g. "TLSv1.3 TLS_AES_256_GCM_SHA384"."""
    cipher: tuple[str, str, int] | None = sock.cipher()
    return f"{sock.version() or '?'} {cipher[0] if cipher else '?'}"


def describe_context(context: ssl.SSLContext) -> str:
    """What a context enforces, read from the context itself (evidence, not a claim)."""
    floor: str = context.minimum_version.name.replace("TLSv", "TLS ").replace("_", ".")
    verified: bool = context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    return f"minimum accepted: {floor}   certificate verification: {'on' if verified else 'OFF'}"
