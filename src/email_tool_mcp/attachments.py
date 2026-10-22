"""Files attached to outgoing mail, files that look sensitive, and attachments saved from incoming mail.

Standard: `email.message.EmailMessage.add_attachment` with the type `mimetypes` guesses from the
file name; text inside Word files read from their XML (`zipfile`), inside PDFs with pypdf.
Sensitive-file signs follow the usual secret-scanning patterns (private key headers,
credential files and folders, password databases). The user decides: a sensitive file is
never refused, only shown for confirmation before it is sent.
Placement: attachments.py; message_compose.py attaches, approval.py asks, cui.py reads the
text, tools/reading.py saves.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage, Message
from pathlib import Path
from typing import Final

from pypdf import PdfReader

# Gmail and Outlook both refuse messages much above 25 MB.
MAX_TOTAL_BYTES: Final[int] = 25 * 1024 * 1024
# Text read from one attachment for the CUI check; enough for any banner or portion mark.
_TEXT_LIMIT: Final[int] = 2_000_000

_SENSITIVE_NAMES: Final[dict[str, str]] = {
    "id_rsa": "an SSH private key",
    "id_ed25519": "an SSH private key",
    "id_ecdsa": "an SSH private key",
    "id_dsa": "an SSH private key",
    ".env": "an environment file, which usually holds passwords and API keys",
    ".netrc": "a file of saved logins",
    ".pgpass": "a file of database passwords",
    ".pypirc": "a file of package-index passwords",
    ".npmrc": "a file that can hold a package-registry token",
    "credentials": "a credentials file",
    "credentials.json": "a credentials file",
    "wallet.dat": "a cryptocurrency wallet",
}
_SENSITIVE_SUFFIXES: Final[dict[str, str]] = {
    ".pem": "a key or certificate file",
    ".key": "a private key file",
    ".p12": "a certificate with its private key",
    ".pfx": "a certificate with its private key",
    ".kdbx": "a password database",
    ".keychain": "a keychain",
    ".keychain-db": "a keychain",
    ".ovpn": "a VPN profile, which can hold its keys",
}
_SENSITIVE_FOLDERS: Final[dict[str, str]] = {
    ".ssh": "it is in .ssh, the SSH keys folder",
    ".aws": "it is in .aws, the AWS credentials folder",
    ".gnupg": "it is in .gnupg, the PGP keys folder",
    ".kube": "it is in .kube, the Kubernetes credentials folder",
    "gcloud": "it is in gcloud, the Google Cloud credentials folder",
    ".docker": "it is in .docker, which can hold registry logins",
    "keyrings": "it is in a keyring folder",
}
_SENSITIVE_TEXT: Final[tuple[tuple[re.Pattern[bytes], str], ...]] = (
    (re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "it contains a private key"),
    (re.compile(rb"aws_secret_access_key", re.IGNORECASE), "it contains an AWS secret key"),
    (re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), "it contains an AWS access key ID"),
)
_XML_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_UNSAFE_NAME: Final[re.Pattern[str]] = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


@dataclass(frozen=True)
class Attachment:
    """One file to attach, read once."""

    name: str
    size: int
    content: bytes = field(repr=False)
    maintype: str
    subtype: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def label(self) -> str:
        """`report.pdf (1.2 MB)`."""
        return f"{self.name} ({human_size(self.size)})"


@dataclass(frozen=True)
class SensitiveFile:
    """Why one attachment looks sensitive."""

    name: str
    reasons: tuple[str, ...]

    def render(self) -> str:
        return f"{self.name} looks sensitive: {'; '.join(self.reasons)}"


def human_size(size: int) -> str:
    """Bytes as the user reads them: 830 B, 12.4 KB, 3.1 MB."""
    amount: float = float(size)
    unit: str
    for unit in ("B", "KB", "MB"):
        if amount < 1024 or unit == "MB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} MB"


def load(paths: Sequence[str]) -> list[Attachment]:
    """Read every file in `paths` (any folder, `~` allowed); ValueError for a missing file or too much in total."""
    loaded: list[Attachment] = []
    raw: str
    for raw in paths:
        path: Path = Path(raw).expanduser()
        if not path.is_file():
            raise ValueError(f"cannot attach {raw!r}: no such file")
        guessed: str | None = mimetypes.guess_type(path.name)[0]
        maintype: str
        subtype: str
        maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
        content: bytes = path.read_bytes()
        loaded.append(Attachment(path.name, len(content), content, maintype, subtype))
    total: int = sum(attachment.size for attachment in loaded)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(
            f"the attachments add up to {human_size(total)}; mail servers refuse more than "
            f"{human_size(MAX_TOTAL_BYTES)} per message"
        )
    return loaded


def sensitive(paths: Sequence[str], attachments: Sequence[Attachment]) -> list[SensitiveFile]:
    """The attachments that look sensitive, with every reason; `paths` and `attachments` in the same order."""
    found: list[SensitiveFile] = []
    raw: str
    attachment: Attachment
    for raw, attachment in zip(paths, attachments, strict=True):
        path: Path = Path(raw).expanduser()
        name: str = path.name.lower()
        reasons: list[str] = []
        if name in _SENSITIVE_NAMES or name.startswith(".env."):
            reasons.append(f"it is {_SENSITIVE_NAMES.get(name, _SENSITIVE_NAMES['.env'])}")
        if path.suffix.lower() in _SENSITIVE_SUFFIXES:
            reasons.append(f"it is {_SENSITIVE_SUFFIXES[path.suffix.lower()]}")
        folder: str
        for folder in path.resolve().parent.parts:
            if folder.lower() in _SENSITIVE_FOLDERS:
                reasons.append(_SENSITIVE_FOLDERS[folder.lower()])
                break
        pattern: re.Pattern[bytes]
        reason: str
        for pattern, reason in _SENSITIVE_TEXT:
            if pattern.search(attachment.content):
                reasons.append(reason)
        if reasons:
            found.append(SensitiveFile(attachment.name, tuple(dict.fromkeys(reasons))))
    return found


def attach(message: EmailMessage, attachments: Sequence[Attachment]) -> None:
    """Add every attachment to `message`, which becomes multipart/mixed."""
    attachment: Attachment
    for attachment in attachments:
        message.add_attachment(
            attachment.content, maintype=attachment.maintype, subtype=attachment.subtype, filename=attachment.name
        )


def attachment_text(part: Message) -> str:
    """Readable text of one attached part (text, Word, PDF), for the CUI check; "" when there is none."""
    name: str = (part.get_filename() or "").lower()
    payload: object = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    try:
        if name.endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                xml: str = archive.read("word/document.xml").decode("utf-8", "replace")
            return _XML_TAG.sub("\n", xml)[:_TEXT_LIMIT]
        if name.endswith(".pdf"):
            reader: PdfReader = PdfReader(io.BytesIO(payload))
            return "\n".join(page.extract_text() or "" for page in reader.pages)[:_TEXT_LIMIT]
    except Exception:
        # An unreadable file has no markings this check can read; the policy still applies to the rest.
        return ""
    if part.get_content_maintype() == "text" or name.endswith((".csv", ".md", ".txt", ".html", ".htm")):
        charset: str = part.get_content_charset() or "utf-8"
        return payload.decode(charset, "replace")[:_TEXT_LIMIT]
    return ""


def safe_file_name(name: str) -> str:
    """An attachment's name made safe to save: no folders, control or reserved characters."""
    base: str = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned: str = _UNSAFE_NAME.sub("_", base).strip(" .")
    return cleaned[:200] or "attachment"


def free_path(directory: Path, name: str) -> Path:
    """`directory/name`, or `name (2)`, `name (3)`, ... when that file exists already."""
    candidate: Path = directory / name
    stem: str = candidate.stem
    suffix: str = candidate.suffix
    number: int = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({number}){suffix}"
        number += 1
    return candidate
