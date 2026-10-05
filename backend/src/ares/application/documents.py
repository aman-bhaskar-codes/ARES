from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from ares.adapters.pdf_parser import BoundedPdfParser
from ares.application.rag import RAGConfig, chunk_document
from ares.domain.models import DocumentStatus, DocumentTextCreate, DocumentView, FetchedDocument
from ares.ports.storage import BlobStore


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    locator: str
    segment_index: int | None = None


def pages_for_range(page_map: list[dict[str, int]], start: int, end: int) -> tuple[int | None, int | None]:
    pages = [
        int(item["page"])
        for item in page_map
        if int(item["char_end"]) >= start and int(item["char_start"]) <= end
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def build_document_chunks(
    *, name: str, text: str, page_map: list[dict[str, int]], max_chunks: int = 500
) -> list[PreparedChunk]:
    if not text.strip():
        return []
    synthetic_url = f"https://ares.local/ingestion/{uuid4()}"
    doc = FetchedDocument(
        title=name,
        url=synthetic_url,
        final_url=synthetic_url,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extraction_method="ingestion-chunker",
        source_kind="document",
        page_map=page_map,
    )
    candidates = chunk_document(doc, RAGConfig(target_chars=1_250, overlap_chars=160, min_chunk_chars=160))
    prepared: list[PreparedChunk] = []
    for index, candidate in enumerate(candidates[:max_chunks], start=1):
        page_start, page_end = pages_for_range(page_map, candidate.char_start, candidate.char_end)
        if page_start is None:
            locator = f"passage {index}"
        elif page_start == page_end:
            locator = f"p. {page_start} · passage {index}"
        else:
            locator = f"pp. {page_start}–{page_end} · passage {index}"
        prepared.append(
            PreparedChunk(
                chunk_index=index,
                text=candidate.text,
                char_start=candidate.char_start,
                char_end=candidate.char_end,
                page_start=page_start,
                page_end=page_end,
                locator=locator,
            )
        )
    return prepared


class DocumentIngestService:
    def __init__(self, repository, blobs: BlobStore, pdf_parser: BoundedPdfParser):
        self.repository = repository
        self.blobs = blobs
        self.pdf_parser = pdf_parser

    def ingest_text(self, payload: DocumentTextCreate) -> DocumentView:
        raw = payload.text.encode("utf-8")
        blob_key = self.blobs.put_bytes("documents", raw)
        chunks = build_document_chunks(name=payload.name, text=payload.text, page_map=[])
        try:
            return self.repository.create_user_document(
                name=payload.name.strip(),
                mime_type=payload.mime_type,
                text=payload.text,
                raw_bytes=raw,
                blob_key=blob_key,
                status=DocumentStatus.READY,
                page_count=None,
                page_map=[],
                warnings=[],
                parser_version="plain-text-v1",
                chunks=chunks,
            )
        except Exception:
            if not self.repository.is_blob_referenced(blob_key):
                self.blobs.delete(blob_key)
            raise

    def ingest_pdf(self, *, name: str, raw: bytes) -> DocumentView:
        parsed = self.pdf_parser.parse(raw)
        blob_key = self.blobs.put_bytes("documents", raw)
        status = DocumentStatus(parsed.status)
        chunks = (
            build_document_chunks(name=name, text=parsed.text, page_map=parsed.page_map)
            if status in {DocumentStatus.READY, DocumentStatus.PARTIAL}
            else []
        )
        try:
            return self.repository.create_user_document(
                name=name.strip(),
                mime_type="application/pdf",
                text=parsed.text,
                raw_bytes=raw,
                blob_key=blob_key,
                status=status,
                page_count=parsed.page_count,
                page_map=parsed.page_map,
                warnings=parsed.warnings,
                parser_version=parsed.parser_version,
                chunks=chunks,
            )
        except Exception:
            if not self.repository.is_blob_referenced(blob_key):
                self.blobs.delete(blob_key)
            raise


__all__ = ["BoundedPdfParser", "DocumentIngestService", "PdfParseError", "PreparedChunk", "build_document_chunks"]
