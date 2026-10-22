"""The one place TLS is configured (NIST SP 800-171 3.13.8, 3.13.11).

Standard: the stdlib `ssl` module: `ssl.create_default_context()` (certificate and
hostname verification, SNI) with the floor raised explicitly to TLS 1.2, as NIST
SP 800-52 Rev. 2 requires; the default floor is whatever the OS OpenSSL allows.
FIPS state comes from CPython's `_hashlib.get_fips_mode()`, which reports whether
the OpenSSL it is linked to runs its FIPS provider, and, for the kept sign-ins that
`cryptography` encrypts, from that package's own OpenSSL binding (its wheels bundle
their own OpenSSL, separate from Python's).
`requests` carries the sign-in traffic (MSAL, google-auth); `TlsAdapter` gives it the
same context and the network timeout.
Placement: tls.py; imap_session.py, mailbox_book.py and the sign-in modules take every context from here.
"""

from __future__ import annotations

import ssl
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from email_tool_mcp.settings import NETWORK_TIMEOUT_SECONDS


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


def sign_in_storage_fips_enabled() -> bool:
    """True when `cryptography`, which encrypts kept sign-ins, runs on a FIPS provider."""
    try:
        # The binding cryptography's own `backend._fips_enabled` reads; it has no public name.
        from cryptography.hazmat.bindings._rust import openssl

        return bool(openssl.is_fips_enabled())
    except Exception:
        # Moved or failing private binding: fail closed, so require_fips refuses rather than trusts.
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


class TlsAdapter(HTTPAdapter):
    """HTTPS with the TLS context and network timeout every IMAP and SMTP connection uses."""

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        pool_kwargs["ssl_context"] = client_context()
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        # Through HTTPS_PROXY too: the proxy pool is built separately from the direct one.
        proxy_kwargs["ssl_context"] = client_context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float | None, float | None] | None = None,
        verify: bool | str = True,
        cert: str | tuple[str, str] | None = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Response:
        # Always the project's timeout: google-auth passes its own 120 s, MSAL none.
        return super().send(request, stream, NETWORK_TIMEOUT_SECONDS, verify, cert, proxies)


def https_session() -> requests.Session:
    """The HTTP client every sign-in and token refresh (Microsoft, Google) goes through."""
    session: requests.Session = requests.Session()
    session.mount("https://", TlsAdapter(max_retries=1))
    return session
