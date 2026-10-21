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
    for _page_id, content_id, text in zip(page_ids, content_ids, texts, strict=True):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> /MediaBox [0 0 612 792] /Contents {content_id} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

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
    assert result.text[first["char_start"] : first["char_end"]] == "Page one evidence."
    assert result.text[second["char_start"] : second["char_end"]] == "Page two limitation."


def test_pdf_file_parser_matches_byte_parser_without_parent_read_bytes(tmp_path):
    path = tmp_path / 'document.pdf'
    path.write_bytes(_pdf_with_pages(['Research evidence from the file parser.']))
    result = BoundedPdfParser().parse_file(path)
    assert 'Research evidence' in result.text


def test_pdf_upload_uses_file_parser_and_unicode_download_stream(tmp_path, monkeypatch):
    from ares.api.app import create_app
    from ares.api.settings import Settings
    from fastapi.testclient import TestClient
    app = create_app(Settings(_env_file=None, database_url=f'sqlite+pysqlite:///{tmp_path / "upload.db"}',
        blob_root=str(tmp_path / 'blobs')))
    client = TestClient(app)
    def forbidden(*args, **kwargs):
        raise AssertionError('whole-file byte path must not be used')
    monkeypatch.setattr(app.state.pdf_parser, 'parse', forbidden)
    raw = _pdf_with_pages(['Grounded research evidence from a PDF upload.'])
    uploaded = client.post('/api/v1/documents/pdf', files={'file': ('अनुसंधान.pdf', raw, 'application/pdf')})
    assert uploaded.status_code == 201
    assert uploaded.json()['byte_count'] == len(raw)
    admitted = client.post('/api/v2/assets', files={'file': ('अनुसंधान.pdf', raw, 'application/pdf')})
    assert admitted.status_code == 202
    monkeypatch.setattr(app.state.blobs, 'get_bytes', forbidden)
    downloaded = client.get('/api/v2/assets/' + admitted.json()['asset']['id'] + '/content')
    assert downloaded.status_code == 200
    assert downloaded.content == raw
    assert "filename*=UTF-8''" in downloaded.headers['Content-Disposition']


def test_text_heavy_pdf_result_is_drained_before_worker_exit(tmp_path):
    """A parsed result larger than the IPC pipe must not deadlock worker shutdown."""
    text = 'PDF source evidence must remain searchable and preserve page citations. ' * 120
    path = tmp_path / 'text-heavy.pdf'
    path.write_bytes(_pdf_with_pages([text + str(index) for index in range(20)]))
    result = BoundedPdfParser(timeout_seconds=5).parse_file(path)
    assert result.status == 'ready'
    assert result.page_count == 20
    assert len(result.text) > 128 * 1024
    assert len(result.page_map) == 20


def test_blank_cover_does_not_shift_extracted_page_offsets():
    text = 'Usable digital text follows the blank cover page and must preserve exact citations.'
    result = BoundedPdfParser().parse(_pdf_with_pages(['', text, '']))
    page = result.page_map[1]
    assert result.text[page['char_start']:page['char_end']] == text
    assert all(page['char_end'] <= len(result.text) for page in result.page_map)


def test_mixed_pdf_upload_preserves_searchable_pages(tmp_path):
    from uuid import UUID

    from ares.api.app import create_app
    from ares.api.settings import Settings
    from fastapi.testclient import TestClient

    app = create_app(Settings(_env_file=None, database_url=f'sqlite+pysqlite:///{tmp_path / "mixed.db"}', blob_root=str(tmp_path / 'blobs')))
    client = TestClient(app, raise_server_exceptions=False)
    text = 'Usable digital research evidence remains searchable even when another page requires OCR.'
    uploaded = client.post('/api/v1/documents/pdf', files={'file': ('mixed.pdf', _pdf_with_pages(['', text]), 'application/pdf')})
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    assert document['status'] == 'partial'
    assert document['lexical_ready']
    assert document['page_count'] == 2
    assert document['warnings']
    chunks = app.state.repository.get_document_chunks([UUID(document['id'])])
    assert any('Usable digital research evidence' in chunk.text for chunk in chunks)
    stored = app.state.repository.get_documents([UUID(document['id'])])[0]
    assert all(stored.text[chunk.char_start:chunk.char_end] == chunk.text for chunk in chunks)
    assert all(chunk.page_start == 2 for chunk in chunks)


def _blocked_pdf_worker(*args, **kwargs):
    import time
    time.sleep(30)


def test_parser_timeout_reaps_worker(monkeypatch):
    import multiprocessing as mp

    import ares.adapters.pdf_parser as pdf_parser
    import pytest
    before = {process.pid for process in mp.active_children()}
    monkeypatch.setattr(pdf_parser, '_parse_worker', _blocked_pdf_worker)
    with pytest.raises(pdf_parser.PdfParseError, match='time limit'):
        BoundedPdfParser(timeout_seconds=0.1).parse(_pdf_with_pages(['Blocked parser.']))
    assert {process.pid for process in mp.active_children()} == before
