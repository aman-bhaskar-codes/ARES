from __future__ import annotations


def test_academic_pdf_fetch_uses_bounded_parser_and_preserves_page_map(monkeypatch):
    from ares.adapters.pdf_parser import ParsedPdf, BoundedPdfParser
    from ares.adapters.safe_fetch import SafeHttpFetcher

    fetcher = SafeHttpFetcher()
    monkeypatch.setattr(
        fetcher,
        "_fetch_response",
        lambda *args, **kwargs: (
            "https://example.org/paper.pdf",
            {"content-type": "application/pdf"},
            b"%PDF-1.7 fixture bytes",
        ),
    )
    monkeypatch.setattr(
        BoundedPdfParser,
        "parse",
        lambda self, payload: ParsedPdf(
            text="Full paper evidence " * 20,
            page_map=[{"page": 1, "char_start": 0, "char_end": 200}],
            page_count=1,
            status="ready",
            warnings=[],
            parser_version="fixture-1",
        ),
    )
    document = fetcher.fetch_pdf("https://example.org/paper.pdf")
    assert document.mime_type == "application/pdf"
    assert document.extraction_method == "academic-pdf:fixture-1"
    assert document.page_map[0]["page"] == 1
