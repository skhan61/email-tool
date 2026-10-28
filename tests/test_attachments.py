"""Attachments: sending any file, confirming sensitive ones, CUI inside attachments, audit, saving.

Standard: pytest with the SDK's in-process client; an `elicitation_callback` stands in for the
person, the fake mail server for IMAP and SMTP, and real files in tmp_path for attachments.
Placement: tests/test_attachments.py, beside attachments.py and the tools that use it.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Callable
from email import message_from_bytes
from email.message import EmailMessage, Message
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import CallToolResult, TextContent
from pypdf import PageObject, PdfReader, PdfWriter

from email_tool_mcp import attachments as attachments_module
from email_tool_mcp.attachments import (
    Attachment,
    UnreadableAttachment,
    attachment_text,
    load,
    safe_file_name,
    sensitive,
)
from email_tool_mcp.audit import AuditLog
from email_tool_mcp.cui import message_markings
from email_tool_mcp.mailbox_book import MailboxBook
from email_tool_mcp.message_compose import compose
from email_tool_mcp.passwords import store_password
from email_tool_mcp.policy import Policy
from email_tool_mcp.server import build_server
from tests.fakes import FakeMailServer
from tests.test_approval import Person

# A fake key's first line, joined at run time so no file holds it whole (the repository's
# private-key hook scans for that line).
KEY_HEADER: str = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"


def _encrypted(content: bytes) -> bytes:
    """`content`, a PDF, encrypted with a password the CUI check does not have."""
    writer: PdfWriter = PdfWriter(clone_from=PdfReader(io.BytesIO(content)))
    writer.encrypt("not-known-here")
    out: io.BytesIO = io.BytesIO()
    writer.write(out)
    return out.getvalue()


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
    path.write_text(f"{KEY_HEADER}\nabc\n")
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
        ("notes.txt", KEY_HEADER.encode(), "private key"),
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


def use_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point `~` and Path.home() at `home`: POSIX reads HOME, Windows reads USERPROFILE."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


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


def code_in(refusal: CallToolResult) -> str:
    found: re.Match[str] | None = re.search(r'confirm_sensitive="([0-9a-f]+)"', text_of(refusal))
    assert found is not None, text_of(refusal)
    return found.group(1)


@pytest.mark.anyio
async def test_without_a_prompt_a_sensitive_send_needs_the_code_from_the_warning(
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
    async with Client(build_server(book, audit)) as client:
        made_up: CallToolResult = await client.call_tool("send_email", {**arguments, "confirm_sensitive": "deadbeef"})
        assert made_up.is_error and mail_server.sent == []
        assert "id_ed25519 looks sensitive" in text_of(made_up)
        other_recipient: CallToolResult = await client.call_tool(
            "send_email", {**arguments, "to": "b@example.com", "confirm_sensitive": code_in(made_up)}
        )
        assert other_recipient.is_error and mail_server.sent == []
        code: str = code_in(other_recipient)
        private_key.write_text(private_key.read_text() + "changed\n")
        changed_file: CallToolResult = await client.call_tool(
            "send_email", {**arguments, "to": "b@example.com", "confirm_sensitive": code}
        )
        assert changed_file.is_error and mail_server.sent == []
        confirmed: CallToolResult = await client.call_tool(
            "send_email", {**arguments, "confirm_sensitive": code_in(changed_file)}
        )
        assert confirmed.is_error, "a code is bound to its own recipients"
        fresh: str = code_in(confirmed)
        sent: CallToolResult = await client.call_tool("send_email", {**arguments, "confirm_sensitive": fresh})
        assert not sent.is_error, text_of(sent)
        assert len(mail_server.sent) == 1
        again: CallToolResult = await client.call_tool("send_email", {**arguments, "confirm_sensitive": fresh})
        assert again.is_error and len(mail_server.sent) == 1, "a code works once"


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
@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pricing.docx", docx_with_text("CUI//SP-PROPIN")),
        # #127: one the check cannot read may be CUI, so it is refused the same way.
        ("pricing.pdf", _encrypted(pdf_with_text("CUI//SP-PROPIN"))),
    ],
)
async def test_a_cui_attachment_to_an_outside_domain_is_refused(
    settings_file: Path, tmp_path: Path, mail_server: FakeMailServer, audit: AuditLog, name: str, content: bytes
) -> None:
    store_password("work", "pw")
    policy_file: Path = tmp_path / "admin.toml"
    policy_file.write_text('[default]\ncui_recipient_domains = ["example.com"]\n', encoding="utf-8")
    book: MailboxBook = MailboxBook(
        settings_file, {}, mail_server.open_imap, mail_server.open_smtp, policy=Policy([policy_file])
    )
    path: Path = tmp_path / name
    path.write_bytes(content)
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
    assert "has no attachment 2" in text_of(missing)


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


def message_with(name: str, content: bytes, subtype: str = "octet-stream") -> EmailMessage:
    message: EmailMessage = compose("x@example.com", "me@example.com", "Files", "Attached.", "", "")
    message.add_attachment(content, maintype="application", subtype=subtype, filename=name)
    return message


@pytest.mark.parametrize(
    ("directory", "name"),
    [(".config/autostart", "update.desktop"), ("~/.ssh", "authorized_keys"), ("~/Documents", "setup.exe")],
)
@pytest.mark.anyio
async def test_saving_where_a_file_can_run_asks_first(
    book: MailboxBook,
    audit: AuditLog,
    mail_server: FakeMailServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory: str,
    name: str,
) -> None:
    store_password("work", "pw")
    use_home(monkeypatch, tmp_path)
    uid: int = mail_server.add("INBOX", message_with(name, b"payload").as_bytes())
    arguments: dict[str, Any] = {"mailbox": "work", "uid": uid, "index": 1, "directory": directory}
    declining: Person = Person("decline", False)
    refused: CallToolResult = await call(book, audit, "save_attachment", arguments, declining)
    assert refused.is_error and "WARNING:" in declining.shown[0]
    assert not any(tmp_path.rglob(name))
    accepting: Person = Person("accept", True)
    saved: CallToolResult = await call(book, audit, "save_attachment", arguments, accepting)
    assert not saved.is_error, text_of(saved)
    assert len(list(tmp_path.rglob(name))) == 1


@pytest.mark.anyio
async def test_a_relative_folder_means_the_users_home(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_password("work", "pw")
    use_home(monkeypatch, tmp_path)
    uid: int = mail_server.add("INBOX", message_with("notes.txt", b"hello").as_bytes())
    result: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 1, "directory": "Downloads"}
    )
    assert not result.is_error, text_of(result)
    assert (tmp_path / "Downloads" / "notes.txt").read_bytes() == b"hello"


@pytest.mark.anyio
async def test_a_forwarded_email_is_saved_with_its_content(
    book: MailboxBook, audit: AuditLog, mail_server: FakeMailServer, tmp_path: Path
) -> None:
    store_password("work", "pw")
    inner: EmailMessage = compose("a@example.com", "b@example.com", "Original", "The original text.", "", "")
    outer: EmailMessage = compose("x@example.com", "me@example.com", "Fwd", "See below.", "", "")
    outer.add_attachment(inner, filename="original.eml")
    uid: int = mail_server.add("INBOX", outer.as_bytes())
    result: CallToolResult = await call(
        book, audit, "save_attachment", {"mailbox": "work", "uid": uid, "index": 1, "directory": str(tmp_path)}
    )
    assert not result.is_error, text_of(result)
    assert b"The original text." in (tmp_path / "original.eml").read_bytes()


@pytest.mark.parametrize(
    ("name", "content_type"),
    [("saved.eml", "application/octet-stream"), ("logs.tar.gz", "application/gzip"), ("a.pdf", "application/pdf")],
)
def test_files_are_sent_under_a_type_mail_allows(tmp_path: Path, name: str, content_type: str) -> None:
    path: Path = tmp_path / name
    path.write_bytes(b"data")
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    assert next(iter(message.iter_attachments())).get_content_type() == content_type


def test_an_armored_pgp_secret_key_is_sensitive(tmp_path: Path) -> None:
    path: Path = tmp_path / "mykey.asc"
    path.write_text("-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\nabc\n")
    assert sensitive([str(path)], load([str(path)]))


def test_the_size_is_checked_before_any_file_is_read(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attachments_module, "MAX_TOTAL_BYTES", 10)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("read before the size check"))
    with pytest.raises(ValueError, match="refuse more than"):
        load([str(report)])


def office_file(parts: dict[str, str]) -> bytes:
    buffer: io.BytesIO = io.BytesIO()
    archive: zipfile.ZipFile
    with zipfile.ZipFile(buffer, "w") as archive:
        member: str
        xml: str
        for member, xml in parts.items():
            archive.writestr(member, xml)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "parts", "marking"),
    [
        (
            "memo.docx",
            {"word/document.xml": "<w:p><w:t>Hi</w:t></w:p>", "word/header1.xml": "<w:p><w:t>CUI//SP-CTI</w:t></w:p>"},
            "CUI//SP-CTI",
        ),
        (
            "memo.docx",
            {"word/document.xml": "<w:p><w:r><w:t>(</w:t></w:r><w:r><w:t>CUI)</w:t></w:r> Plan</w:p>"},
            "(CUI)",
        ),
        ("prices.xlsx", {"xl/sharedStrings.xml": "<si><t>CUI//SP-PROPIN</t></si>"}, "CUI//SP-PROPIN"),
        ("brief.pptx", {"ppt/slides/slide1.xml": "<a:p><a:t>CUI</a:t></a:p>"}, "CUI"),
    ],
)
def test_cui_is_read_from_every_office_part(tmp_path: Path, name: str, parts: dict[str, str], marking: str) -> None:
    path: Path = tmp_path / name
    path.write_bytes(office_file(parts))
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    assert any(marking in found for found in message_markings(message))


def test_an_attachment_in_an_unknown_charset_is_still_read() -> None:
    """The charset comes from the sender; an unknown one must not hide a CUI banner or crash the check."""
    part: Message = message_from_bytes(
        b'Content-Type: text/plain; charset=bogus\r\nContent-Disposition: attachment; filename="notes.txt"\r\n\r\n'
        b"CUI//SP-PROPIN\r\nPrices inside.\r\n"
    )
    assert "CUI//SP-PROPIN" in attachment_text(part)


def test_a_pdf_that_cannot_be_read_counts_as_cui_marked(tmp_path: Path) -> None:
    """#127: an unreadable PDF counted as having no markings, so an encrypted CUI PDF went out
    unflagged under a cui_recipient_domains rule. It is now listed, so the rule applies to it.
    """
    path: Path = tmp_path / "pricing.pdf"
    path.write_bytes(_encrypted(pdf_with_text("CUI//SP-PROPIN")))
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    with pytest.raises(UnreadableAttachment):
        attachment_text(next(part for part in message.walk() if part.get_filename()))
    assert any(found.startswith("unreadable attachment: pricing.pdf") for found in message_markings(message))


def test_a_pdf_is_read_whatever_its_name(tmp_path: Path) -> None:
    """#127: a PDF was read only when its name ended in .pdf, so one attached as `pricing` was not."""
    path: Path = tmp_path / "pricing"
    path.write_bytes(pdf_with_text("CUI//SP-PROPIN"))
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    assert any("CUI//SP-PROPIN" in found for found in message_markings(message))


def test_a_pdf_is_read_only_up_to_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """#127: every page was extracted before the limit was applied."""
    writer: PdfWriter = PdfWriter()
    page: PageObject = PdfReader(io.BytesIO(pdf_with_text("CUI page"))).pages[0]
    for _ in range(5):
        writer.add_page(page)
    out: io.BytesIO = io.BytesIO()
    writer.write(out)
    read: list[int] = []
    extract: Callable[..., str] = PageObject.extract_text

    def counted(self: PageObject, *args: Any, **kwargs: Any) -> str:
        read.append(1)
        return str(extract(self, *args, **kwargs))

    monkeypatch.setattr(PageObject, "extract_text", counted)
    monkeypatch.setattr(attachments_module, "_TEXT_LIMIT", 5)
    assert attachments_module.pdf_text(out.getvalue()) == "CUI p"
    assert len(read) == 1


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pricing.txt", pdf_with_text("CUI//SP-PROPIN")),  # a PDF typed as text
        ("pricing", b"\n" + pdf_with_text("CUI//SP-PROPIN")),  # a byte before the header
        ("pricing", docx_with_text("CUI//SP-PROPIN")),  # a Word file without its name
    ],
)
def test_a_renamed_file_is_read_as_what_it_is(tmp_path: Path, name: str, content: bytes) -> None:
    """#127 review: the kind came from the name, so a renamed CUI file was never read."""
    path: Path = tmp_path / name
    path.write_bytes(content)
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    assert any("CUI//SP-PROPIN" in found for found in message_markings(message))


@pytest.mark.parametrize(
    ("name", "content", "why"),
    [
        ("pricing.doc", bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 512, "old or password-protected Office"),
        ("scan.pdf", pdf_with_text(""), "scanned document"),
    ],
)
def test_what_the_check_cannot_read_counts_as_marked(tmp_path: Path, name: str, content: bytes, why: str) -> None:
    """#127 review: an old Office file and a PDF with no text cannot be read for markings either."""
    path: Path = tmp_path / name
    path.write_bytes(content)
    message: EmailMessage = compose("me@example.com", "you@example.com", "s", "b", "", "", load([str(path)]))
    found: list[str] = message_markings(message)
    assert any(item.startswith(f"unreadable attachment: {name}") and why in item for item in found), found


def test_an_attachment_without_a_name_is_checked() -> None:
    """#127 review: only parts with a file name were read."""
    message: EmailMessage = EmailMessage()
    message["Subject"] = "Prices"
    message.set_content("See attached.")
    message.add_attachment(pdf_with_text("CUI//SP-PROPIN"), maintype="application", subtype="pdf")
    assert any("CUI//SP-PROPIN" in found for found in message_markings(message))


def test_an_unreadable_attachment_is_named_as_the_user_named_it() -> None:
    """#127 review: an RFC 2047 file name was shown encoded in the refusal."""
    part: Message = message_from_bytes(
        b"Content-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="=?utf-8?b?cHLDqHMucGRm?="\r\n\r\n%PDF-1.4 broken'
    )
    with pytest.raises(UnreadableAttachment, match=r"^près\.pdf \("):
        attachment_text(part)


def test_an_office_file_is_read_only_up_to_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """#127 review: every part was inflated in full, so a small zip could expand to gigabytes."""
    monkeypatch.setattr(attachments_module, "_XML_BUDGET", 100)
    content: bytes = docx_with_text("CUI//SP-PROPIN " + "x" * 10_000)
    assert len(attachments_module.office_text(".docx", content)) <= 100
