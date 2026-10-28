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

from email_tool_mcp.message_render import decode_text

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
    "secring.gpg": "a PGP secret keyring",
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
# Also removed from problem reports (problem_report.py).
SENSITIVE_TEXT: Final[tuple[tuple[re.Pattern[bytes], str], ...]] = (
    (re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"), "it contains a private key"),
    (re.compile(rb"aws_secret_access_key", re.IGNORECASE), "it contains an AWS secret key"),
    (re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), "it contains an AWS access key ID"),
)
_XML_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
# Paragraph and line ends in Office XML; every other tag joins its runs without a break.
_XML_BREAK: Final[re.Pattern[str]] = re.compile(r"</(?:w:p|a:p|w:tr|row)>|<(?:w:br|w:tab|a:br)\b[^>]*/>")
# Office files (zip of XML) and where their text lives: body, headers, footers, cells, slides.
_OFFICE_TEXT: Final[dict[str, re.Pattern[str]]] = {
    ".docx": re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$"),
    ".docm": re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$"),
    ".xlsx": re.compile(r"^xl/(sharedStrings|worksheets/sheet\d+)\.xml$"),
    ".xlsm": re.compile(r"^xl/(sharedStrings|worksheets/sheet\d+)\.xml$"),
    ".pptx": re.compile(r"^ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml$"),
    ".pptm": re.compile(r"^ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml$"),
}
# Compressed files are sent as such, never under the type of what they contain.
_COMPRESSED: Final[dict[str, str]] = {
    "gzip": "application/gzip",
    "bzip2": "application/x-bzip2",
    "xz": "application/x-xz",
}
# Saving into these folders or under these names can make a file run, or let someone in.
_RISKY_FOLDERS: Final[dict[str, str]] = {
    ".ssh": "the SSH folder, where a file can grant someone access",
    "autostart": "a folder whose files run at login",
    "startup": "a folder whose files run at login",
    "launchagents": "a folder whose files run at login",
    "launchdaemons": "a folder whose files run at startup",
    "hooks": "a folder of scripts that run on their own",
    "init.d": "a folder of scripts that run at startup",
    "systemd": "a folder of services that run on their own",
    "bin": "a folder of programs that run by name",
}
_RISKY_NAMES: Final[frozenset[str]] = frozenset(
    {"authorized_keys", ".bashrc", ".bash_profile", ".profile", ".zshrc", ".zprofile", "crontab"}
)
_RUNNABLE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".desktop",
        ".sh",
        ".bash",
        ".command",
        ".exe",
        ".bat",
        ".cmd",
        ".ps1",
        ".vbs",
        ".wsf",
        ".msi",
        ".lnk",
        ".scr",
        ".plist",
        ".service",
        ".jar",
        ".app",
    }
)
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
    files: list[Path] = [Path(raw).expanduser() for raw in paths]
    path: Path
    for path in files:
        if not path.is_file():
            raise ValueError(f"cannot attach {str(path)!r}: no such file")
    # Sizes first, so a huge file is refused before it is read.
    total: int = sum(path.stat().st_size for path in files)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(
            f"the attachments add up to {human_size(total)}; mail servers refuse more than "
            f"{human_size(MAX_TOTAL_BYTES)} per message"
        )
    loaded: list[Attachment] = []
    for path in files:
        maintype: str
        subtype: str
        maintype, _, subtype = attachment_type(path.name).partition("/")
        content: bytes = path.read_bytes()
        loaded.append(Attachment(path.name, len(content), content, maintype, subtype))
    return loaded


def attachment_type(name: str) -> str:
    """The MIME type to send a file as: guessed from its name, compressed files as such.

    message/* is sent as a plain file: those types may not be base64-encoded (RFC 2046).
    """
    guessed: str | None
    encoding: str | None
    guessed, encoding = mimetypes.guess_type(name)
    if encoding is not None:
        return _COMPRESSED.get(encoding, "application/octet-stream")
    if guessed is None or guessed.startswith("message/"):
        return "application/octet-stream"
    return guessed


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
        for pattern, reason in SENSITIVE_TEXT:
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


def attachment_bytes(part: Message) -> bytes:
    """The file an attached part carries; a forwarded email (message/rfc822) as its own bytes."""
    payload: object = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload
    inner: object = part.get_payload()
    if isinstance(inner, list) and inner and isinstance(inner[0], Message):
        return inner[0].as_bytes()
    return b""


def office_text(name: str, content: bytes) -> str:
    """The text of a Word, Excel or PowerPoint file, from every part that holds text."""
    wanted: re.Pattern[str] = _OFFICE_TEXT[Path(name).suffix.lower()]
    archive: zipfile.ZipFile
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        parts: list[str] = sorted(member for member in archive.namelist() if wanted.match(member))
        xml: str = "\n".join(archive.read(member).decode("utf-8", "replace") for member in parts)
    return _XML_TAG.sub("", _XML_BREAK.sub("\n", xml))


class UnreadableAttachment(ValueError):
    """A PDF or Office attachment the CUI check could not read; its message is the file's name."""


def attachment_text(part: Message) -> str:
    """Readable text of one attached part (text, Office, PDF), for the CUI check; "" when it is of
    no kind the check reads (an image, an archive).

    Raises `UnreadableAttachment` when a PDF or Office file cannot be read (#127): a check that
    passed what it could not read let an encrypted CUI PDF go out unflagged.
    """
    name: str = (part.get_filename() or "").lower()
    content: bytes = attachment_bytes(part)
    try:
        if Path(name).suffix in _OFFICE_TEXT:
            return office_text(name, content)[:_TEXT_LIMIT]
        if is_pdf(name, part, content):
            return pdf_text(content)
    except Exception as error:
        raise UnreadableAttachment(part.get_filename() or "an attachment") from error
    if part.get_content_maintype() == "text" or name.endswith((".csv", ".md", ".txt", ".html", ".htm")):
        return decode_text(content, part.get_content_charset())[:_TEXT_LIMIT]
    return ""


def is_pdf(name: str, part: Message, content: bytes) -> bool:
    """A PDF by its name, its type or its own header (#127): a CUI PDF attached as `pricing` is a PDF."""
    return name.endswith(".pdf") or part.get_content_type() == "application/pdf" or content.startswith(b"%PDF-")


def pdf_text(content: bytes) -> str:
    """The text of a PDF's pages, read only until `_TEXT_LIMIT` characters (#127)."""
    reader: PdfReader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    read: int = 0
    for page in reader.pages:
        text: str = page.extract_text() or ""
        pages.append(text)
        read += len(text) + 1
        if read >= _TEXT_LIMIT:
            break
    return "\n".join(pages)[:_TEXT_LIMIT]


def save_directory(given: str) -> Path:
    """Where to save: `~` expanded, and a relative folder taken from the user's home, as people say it."""
    folder: Path = Path(given).expanduser()
    return folder if folder.is_absolute() else Path.home() / folder


def risky_save(directory: Path, name: str) -> list[str]:
    """Why saving `name` into `directory` could make it run or let someone in; [] when it cannot."""
    reasons: list[str] = []
    folder: str
    for folder in directory.parts:
        if folder.lower() in _RISKY_FOLDERS:
            reasons.append(f"{directory} is {_RISKY_FOLDERS[folder.lower()]}")
            break
    if name.lower() in _RISKY_NAMES:
        reasons.append(f"{name} is a file the system reads to run commands or grant access")
    if Path(name).suffix.lower() in _RUNNABLE_SUFFIXES:
        reasons.append(f"{name} is a program or a file that runs when opened")
    return reasons


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
