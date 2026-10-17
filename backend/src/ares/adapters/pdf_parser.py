from __future__ import annotations

import logging
import multiprocessing as mp
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from queue import Empty
from typing import Any


class PdfParseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedPdf:
    text: str
    page_map: list[dict[str, int]]
    page_count: int
    status: str
    warnings: list[str]
    parser_version: str
    page_types: dict[int, str] = field(default_factory=dict)
    scanned_pages: list[int] = field(default_factory=list)


def _apply_resource_limits(memory_bytes: int, cpu_seconds: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, ValueError, OSError):
        # Windows and some container runtimes do not expose POSIX resource limits.
        pass


def _parse_worker(
    payload: bytes | str,
    result_queue: Any,
    *,
    max_pages: int,
    max_text_chars: int,
    memory_bytes: int,
    cpu_seconds: int,
) -> None:
    try:
        _apply_resource_limits(memory_bytes, cpu_seconds)
        from pypdf import PdfReader
        from pypdf import __version__ as pypdf_version

        reader = PdfReader(BytesIO(payload) if isinstance(payload, bytes) else payload, strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:  # pypdf raises several encryption-specific errors
                logging.getLogger(__name__).warning("pdf_parser: recovery boundary (%s)", type(exc).__name__)
                raise PdfParseError("encrypted PDF could not be opened without a password") from exc
            if not unlocked:
                raise PdfParseError("password-protected PDFs are not supported")
        page_count = len(reader.pages)
        if page_count == 0:
            raise PdfParseError("PDF contains no pages")
        if page_count > max_pages:
            raise PdfParseError(f"PDF exceeds the {max_pages}-page limit")

        parts: list[str] = []
        page_map: list[dict[str, int]] = []
        page_types: dict[int, str] = {}
        warnings: list[str] = []
        empty_pages = 0
        cursor = 0
        for index, page in enumerate(reader.pages, start=1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception as exc:
                logging.getLogger(__name__).warning("pdf_parser: recovery boundary (%s)", type(exc).__name__)
                page_text = ""
                warnings.append(f"Page {index} could not be extracted ({type(exc).__name__}).")

            has_images = False
            try:
                images_attr = getattr(page, "images", None)
                if images_attr is not None:
                    has_images = len(images_attr) > 0
            except Exception:
                has_images = False

            # Classify page: text length >= 40 chars indicates high-fidelity digital text
            if len(page_text) >= 40:
                page_types[index] = "digital"
            elif has_images or not page_text:
                page_types[index] = "scanned"
            else:
                page_types[index] = "digital"

            if not page_text:
                empty_pages += 1
            if parts:
                parts.append("\n\n")
                cursor += 2
            start = cursor
            parts.append(page_text)
            cursor += len(page_text)
            page_map.append({"page": index, "char_start": start, "char_end": cursor})
            if cursor > max_text_chars:
                raise PdfParseError(
                    f"extracted PDF text exceeds the {max_text_chars:,}-character limit"
                )

        # Page offsets refer to this exact concatenation, including blank-page separators.
        text = "".join(parts)
        scanned_pages = [idx for idx, ptype in page_types.items() if ptype == "scanned"]
        meaningful_pages = page_count - empty_pages
        if len(scanned_pages) == page_count or not text or meaningful_pages == 0:
            status = "needs_ocr"
            warnings.append("No usable text layer was detected; OCR is required before research.")
        elif scanned_pages:
            status = "mixed"
            warnings.append(
                f"{len(scanned_pages)} of {page_count} pages are scanned or contain raster images requiring OCR."
            )
        elif empty_pages:
            status = "partial"
            warnings.append(f"{empty_pages} of {page_count} pages had no extractable text.")
        else:
            status = "ready"
        result_queue.put(
            {
                "ok": True,
                "text": text,
                "page_map": page_map,
                "page_count": page_count,
                "status": status,
                "warnings": warnings,
                "page_types": page_types,
                "scanned_pages": scanned_pages,
                "parser_version": f"pypdf-{pypdf_version}",
            }
        )
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class BoundedPdfParser:
    """Parse untrusted PDFs in a separate process with hard size/page/time ceilings."""

    def __init__(
        self,
        *,
        max_bytes: int = 20 * 1024 * 1024,
        max_pages: int = 200,
        max_text_chars: int = 2_000_000,
        timeout_seconds: float = 25.0,
        memory_bytes: int = 512 * 1024 * 1024,
    ):
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.max_text_chars = max_text_chars
        self.timeout_seconds = timeout_seconds
        self.memory_bytes = memory_bytes

    def parse(self, payload: bytes) -> ParsedPdf:
        if not payload.startswith(b"%PDF-"):
            raise PdfParseError("file signature is not a PDF")
        if len(payload) > self.max_bytes:
            raise PdfParseError(f"PDF exceeds the {self.max_bytes // (1024 * 1024)} MB limit")
        return self._parse_payload(payload)

    def parse_file(self, path: str | Path) -> ParsedPdf:
        source = Path(path)
        with source.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise PdfParseError("file signature is not a PDF")
        if source.stat().st_size > self.max_bytes:
            raise PdfParseError("PDF exceeds the configured upload limit")
        return self._parse_payload(str(source.resolve()))

    def _parse_payload(self, payload: bytes | str) -> ParsedPdf:
        context = mp.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_parse_worker,
            args=(payload, result_queue),
            kwargs={
                "max_pages": self.max_pages,
                "max_text_chars": self.max_text_chars,
                "memory_bytes": self.memory_bytes,
                "cpu_seconds": max(2, int(self.timeout_seconds)),
            },
            daemon=True,
        )
        try:
            process.start()
            # Drain the result before joining: Queue's child feeder cannot exit while a
            # text-heavy result is blocked in the OS pipe waiting for this reader.
            try:
                result = result_queue.get(timeout=self.timeout_seconds)
            except Empty as exc:
                if process.exitcode is not None:
                    raise PdfParseError(
                        f"PDF parser exited without a result (exit={process.exitcode})"
                    ) from exc
                raise PdfParseError("PDF parsing exceeded its time limit") from exc
        finally:
            if process.pid is not None:
                process.join(0.2)
                if process.is_alive():
                    process.terminate()
                    process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join(1)
                if not process.is_alive():
                    process.close()
            result_queue.close()
        if not result.get("ok"):
            raise PdfParseError(str(result.get("error", "PDF parsing failed")))
        return ParsedPdf(
            text=str(result["text"]),
            page_map=list(result["page_map"]),
            page_count=int(result["page_count"]),
            status=str(result["status"]),
            warnings=list(result["warnings"]),
            parser_version=str(result["parser_version"]),
            page_types=dict(result.get("page_types", {})),
            scanned_pages=list(result.get("scanned_pages", [])),
        )
