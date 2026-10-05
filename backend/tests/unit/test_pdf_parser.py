from __future__ import annotations

from ares.adapters.pdf_parser import BoundedPdfParser


def _pdf_with_pages(texts: list[str]) -> bytes:
    # Small deterministic PDF generator for parser tests; no reportlab dependency.
    objects: list[bytes] = []
    page_ids = []
    content_ids = []
    next_id = 4
    for _ in texts:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(texts)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, content_id, text in zip(page_ids, content_ids, texts, strict=True):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> /MediaBox [0 0 612 792] /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_id} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_pdf_parser_preserves_page_map() -> None:
    parser = BoundedPdfParser(timeout_seconds=10)
    result = parser.parse(_pdf_with_pages(["Page one evidence.", "Page two limitation."]))
    assert result.status == "ready"
    assert result.page_count == 2
    assert len(result.page_map) == 2
    first = result.page_map[0]
    second = result.page_map[1]
    assert result.text[first["char_start"]:first["char_end"]] == "Page one evidence."
    assert result.text[second["char_start"]:second["char_end"]] == "Page two limitation."
