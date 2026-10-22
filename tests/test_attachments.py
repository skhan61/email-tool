"""Attachments: sending any file, confirming sensitive ones, CUI inside attachments, audit, saving.

Standard: pytest with the SDK's in-process client; an `elicitation_callback` stands in for the
person, the fake mail server for IMAP and SMTP, and real files in tmp_path for attachments.
Placement: tests/test_attachments.py, beside attachments.py and the tools that use it.
"""

from __future__ import annotations

import io
import json
import zipfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import CallToolResult, TextContent

from email_tool_mcp import attachments as attachments_module
from email_tool_mcp.attachments import Attachment, load, safe_file_name, sensitive
from email_tool_mcp.audit import AuditLog
from email_tool_mcp.cui import message_markings
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy
from email_tool_mcp.server import build_server
from tests.fakes import FakeMailServer
from tests.test_approval import Person


def pdf_with_text(text: str) -> bytes:
    """A one-page PDF whose page text is `text`."""
    stream: bytes = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objects: list[bytes] = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out: bytes = b"%PDF-1.4\n"
    offsets: list[int] = []
    number: int
    body: bytes
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref: int = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += b"trailer\n<</Size " + str(len(objects) + 1).encode() + b"/Root 1 0 R>>\n"
    return out + b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"


def docx_with_text(text: str) -> bytes:
    """A Word file whose body is `text`."""
    buffer: io.BytesIO = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body><w:p><w:t>{text}</w:t></w:p></w:body></w:document>")
    return buffer.getvalue()


def text_of(result: CallToolResult) -> str:
    block: object = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call(
    book: MailboxBook, audit: AuditLog, tool: str, arguments: dict[str, Any], person: Person | None = None
) -> CallToolResult:
    async with Client(build_server(book, audit), elicitation_callback=person) as client:
        return await client.call_tool(tool, arguments)


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path: Path = tmp_path / "report.pdf"
    path.write_bytes(pdf_with_text("Quarterly numbers"))
    return path


@pytest.fixture
def private_key(tmp_path: Path) -> Path:
    folder: Path = tmp_path / ".ssh"
    folder.mkdir()
    path: Path = folder / "id_ed25519"
    path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n")
    return path


def test_any_file_attaches_with_its_type(report: Path) -> None:
    files: list[Attachment] = load([str(report)])
    message: EmailMessage = compose("me@example.com", "you@example.com", "Report", "See attached.", "", "", files)
    assert message.get_content_type() == "multipart/mixed"
    part: EmailMessage = next(iter(message.iter_attachments()))
    assert (part.get_filename(), part.get_content_type()) == ("report.pdf", "application/pdf")
    assert part.get_content() == report.read_bytes()


def test_a_missing_file_or_too_much_in_total_is_refused(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="no such file"):
        load([str(tmp_path / "missing.txt")])
    monkeypatch.setattr(attachments_module, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(ValueError, match="refuse more than"):
        load([str(report)])


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("id_rsa", b"x", "SSH private key"),
        (".env", b"API_KEY=1", "environment file"),
        (".env.production", b"API_KEY=1", "environment file"),
        ("server.pem", b"x", "key or certificate"),
        ("vault.kdbx", b"x", "password database"),
        ("notes.txt", b"-----BEGIN RSA PRIVATE KEY-----", "private key"),
        ("config", b"aws_secret_access_key = abc", "AWS secret key"),
    ],
)
def test_sensitive_looking_files_are_named_with_the_reason(
    tmp_path: Path, name: str, content: bytes, reason: str
) -> None:
    path: Path = tmp_path / name
    path.write_bytes(content)
    found: str = sensitive([str(path)], load([str(path)]))[0].render()
    assert name in found and reason in found


def test_a_file_in_the_ssh_folder_is_sensitive_and_a_report_is_not(private_key: Path, report: Path) -> None:
    paths: list[str] = [str(private_key), str(report)]
    flagged: list[str] = [found.name for found in sensitive(paths, load(paths))]
    assert flagged == ["id_ed25519"]


@pytest.mark.anyio
async def test_an_ordinary_attachment_sends_without_a_question(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, report: Path
) -> None:
    store_password("work", "pw")
    person: Person = Person("accept", True)
    result: CallToolResult = await call(
        book,
        audit,
        "send_email",
        {
            "mailbox": "work",
            "to": "a@example.com",
            "subject": "Report",
            "body": "Attached.",
            "attachments": [str(report)],
        },
        person,
    )
    assert not result.is_error, text_of(result)
    assert person.shown == []
    sent: EmailMessage = mail_server.sent[0][0]
    assert [part.get_filename() for part in sent.iter_attachments()] == ["report.pdf"]


@pytest.mark.anyio
async def test_a_sensitive_attachment_asks_the_user_even_without_required_approval(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, private_key: Path
) -> None:
    store_password("work", "pw")
    arguments: dict[str, Any] = {
        "mailbox": "work",
        "to": "a@example.com",
        "subject": "Key",
        "body": "Here.",
        "attachments": [str(private_key)],
    }
    declining: Person = Person("decline", False)
    refused: CallToolResult = await call(book, audit, "send_email", arguments, declining)
    assert refused.is_error and mail_server.sent == []
    assert "WARNING: id_ed25519 looks sensitive" in declining.shown[0]
    accepting: Person = Person("accept", True)
    sent: CallToolResult = await call(book, audit, "send_email", arguments, accepting)
    assert not sent.is_error, text_of(sent)
    assert len(mail_server.sent) == 1


@pytest.mark.anyio
async def test_without_a_prompt_a_sensitive_send_waits_for_the_users_word(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, private_key: Path
) -> None:
    store_password("work", "pw")
    arguments: dict[str, Any] = {
        "mailbox": "work",
        "to": "a@example.com",
        "subject": "Key",
        "body": "Here.",
        "attachments": [str(private_key)],
    }
    refused: CallToolResult = await call(book, audit, "send_email", arguments)
    assert refused.is_error and mail_server.sent == []
    assert "id_ed25519 looks sensitive" in text_of(refused) and "confirm_sensitive=true" in text_of(refused)
    confirmed: CallToolResult = await call(book, audit, "send_email", {**arguments, "confirm_sensitive": True})
    assert not confirmed.is_error, text_of(confirmed)
    assert len(mail_server.sent) == 1


@pytest.mark.anyio
async def test_a_draft_with_a_sensitive_file_is_saved_with_a_warning(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, private_key: Path
) -> None:
    store_password("work", "pw")
    result: CallToolResult = await call(
        book,
        audit,
        "create_draft",
        {"mailbox": "work", "folder": "Drafts", "to": "a@example.com", "attachments": [str(private_key)]},
    )
    assert not result.is_error, text_of(result)
    assert "Warning: id_ed25519 looks sensitive" in text_of(result)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pricing.docx", docx_with_text("CUI//SP-PROPIN")),
        ("pricing.pdf", pdf_with_text("CUI//SP-PROPIN")),
        ("pricing.csv", b"CUI//SP-PROPIN\nitem,price\n"),
    ],
)
def test_cui_markings_inside_attachments_are_found(tmp_path: Path, name: str, content: bytes) -> None:
    path: Path = tmp_path / name
    path.write_bytes(content)
    message: EmailMessage = compose(
        "me@example.com", "you@example.com", "Prices", "See attached.", "", "", load([str(path)])
    )
    assert any("CUI//SP-PROPIN" in found for found in message_markings(message))


@pytest.mark.anyio
async def test_a_cui_attachment_to_an_outside_domain_is_refused(
    settings_file: Path, tmp_path: Path, mail_server: FakeMailServer, audit: AuditLog
) -> None:
    store_password("work", "pw")
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text('[default]\ncui_recipient_domains = ["example.com"]\n', encoding="utf-8")
    book: MailboxBook = MailboxBook(
        settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=Policy([policy_file])
    )
    path: Path = tmp_path / "pricing.docx"
    path.write_bytes(docx_with_text("CUI//SP-PROPIN"))
    result: CallToolResult = await call(
        book,
        audit,
        "send_email",
        {
            "mailbox": "work",
            "to": "buyer@gmail.com",
            "subject": "Prices",
            "body": "Attached.",
            "attachments": [str(path)],
        },
    )
    assert result.is_error and mail_server.sent == []
    assert "cui_recipient_domains" in text_of(result)


@pytest.mark.anyio
async def test_the_audit_log_keeps_name_size_and_fingerprint_never_the_contents(
    book: MailboxBook, audit: AuditLog, report: Path
) -> None:
    store_password("work", "pw")
    await call(
        book,
        audit,
        "send_email",
        {
            "mailbox": "work",
            "to": "a@example.com",
            "subject": "Report",
            "body": "Attached.",
            "attachments": [str(report)],
        },
    )
    started: dict[str, Any] = next(
        record
        for record in map(json.loads, audit.path.read_text(encoding="utf-8").splitlines())
        if record.get("phase") == "started"
    )
    files: list[dict[str, Any]] = started["arguments"]["attachments"]
    assert files == [{"name": "report.pdf", "size": report.stat().st_size, "sha256": load([str(report)])[0].sha256}]
    assert "Quarterly numbers" not in audit.path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_get_email_lists_attachments_and_save_attachment_keeps_every_copy(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, tmp_path: Path
) -> None:
    store_password("work", "pw")
    hostile: Path = tmp_path / "invoice.pdf"
    hostile.write_bytes(pdf_with_text("Invoice"))
    message: EmailMessage = compose(
        "x@example.com", "me@example.com", "Invoice", "Attached.", "", "", load([str(hostile)])
    )
    part: EmailMessage = next(iter(message.iter_attachments()))
    part.replace_header("Content-Disposition", 'attachment; filename="../../evil:invoice.pdf"')
    uid: int = mail_server.add("INBOX", message.as_bytes())
    shown: CallToolResult = await call(book, audit, "get_email", {"mailbox": "work", "uid": uid})
    assert "1. ../../evil:invoice.pdf (" in text_of(shown)
    downloads: Path = tmp_path / "downloads"
    first: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 1, "directory": str(downloads)}
    )
    second: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 1, "directory": str(downloads)}
    )
    assert not first.is_error and not second.is_error, text_of(first)
    assert sorted(path.name for path in downloads.iterdir()) == ["evil_invoice (2).pdf", "evil_invoice.pdf"]
    assert (downloads / "evil_invoice.pdf").read_bytes() == hostile.read_bytes()
    missing: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 2, "directory": str(downloads)}
    )
    assert "there is no attachment 2" in text_of(missing)


@pytest.mark.parametrize(
    ("given", "saved"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\a.txt", "a.txt"),
        ("\x00bad\x1f.sh", "_bad_.sh"),
        ("..", "attachment"),
    ],
)
def test_attachment_names_are_made_safe(given: str, saved: str) -> None:
    assert safe_file_name(given) == saved


@pytest.mark.anyio
async def test_saving_an_attachment_is_allowed_on_a_read_only_mailbox(
    settings_file: Path, tmp_path: Path, mail_server: FakeMailServer, audit: AuditLog, report: Path
) -> None:
    store_password("work", "pw")
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text("[default]\nread_only = true\n", encoding="utf-8")
    book: MailboxBook = MailboxBook(
        settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=Policy([policy_file])
    )
    message: EmailMessage = compose(
        "x@example.com", "me@example.com", "Report", "Attached.", "", "", load([str(report)])
    )
    uid: int = mail_server.add("INBOX", message.as_bytes())
    result: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 1, "directory": str(tmp_path / "d")}
    )
    assert not result.is_error, text_of(result)
