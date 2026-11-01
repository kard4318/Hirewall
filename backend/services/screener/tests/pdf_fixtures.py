"""A tiny standard-library PDF writer for tests and the attack set. Latin text only, Helvetica, one page."""


def _escape(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def minimal_pdf(
    lines: list[str], *, hidden: str | None = None, tiny: str | None = None, off_page: str | None = None,
    catalog_extra: bytes = b"", extra_objects: list[bytes] | None = None,
) -> bytes:
    """One page of black 11 pt text, plus optional white, 2 pt or off-page text."""
    stream = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
    stream += [f"({_escape(line)}) Tj T*" for line in lines]
    stream.append("ET")
    if hidden:
        stream += ["BT", "1 1 1 rg", "/F1 11 Tf", "50 60 Td", f"({_escape(hidden)}) Tj", "ET"]
    if tiny:
        stream += ["BT", "0 0 0 rg", "/F1 2 Tf", "50 50 Td", f"({_escape(tiny)}) Tj", "ET"]
    if off_page:
        stream += ["BT", "0 0 0 rg", "/F1 11 Tf", "900 900 Td", f"({_escape(off_page)}) Tj", "ET"]
    content = "\n".join(stream).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R " + catalog_extra + b">>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    objects += extra_objects or []
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    output += b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(output)
