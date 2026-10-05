from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _normalized_bbox(bbox, page) -> list[float] | None:
    if bbox is None or page is None or getattr(page, "size", None) is None:
        return None
    try:
        normalized = bbox.to_top_left_origin(page_height=page.size.height).normalized(page.size)
        values = [float(normalized.l), float(normalized.t), float(normalized.r), float(normalized.b)]
        values = [min(1.0, max(0.0, value)) for value in values]
        if values[2] <= values[0] or values[3] <= values[1]:
            return None
        return values
    except Exception:
        return None


def _page_for(doc, page_no: int):
    pages = getattr(doc, "pages", {})
    if isinstance(pages, dict):
        return pages.get(page_no) or pages.get(str(page_no))
    try:
        return pages[page_no]
    except Exception:
        return None


def _locator_from_prov(doc, prov) -> dict[str, object] | None:
    page_no = int(getattr(prov, "page_no", 0) or 0)
    if page_no < 1:
        return None
    page = _page_for(doc, page_no)
    bbox = _normalized_bbox(getattr(prov, "bbox", None), page)
    if bbox is None:
        return None
    return {
        "kind": "page_region",
        "page": page_no,
        "bbox": bbox,
        "coordinate_space": "normalized_top_left",
        "rotation_degrees": 0,
    }


def run(
    input_path: Path,
    output_path: Path,
    *,
    mime_type: str,
    max_pages: int,
    max_bytes: int,
    language: str,
    artifacts_path: Path,
) -> None:
    from docling.datamodel.base_models import InputFormat  # type: ignore[import-not-found]
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions  # type: ignore[import-not-found]
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption  # type: ignore[import-not-found]
    from docling_core.types.doc import TableItem  # type: ignore[import-not-found]
    import docling  # type: ignore[import-not-found]

    if mime_type == "application/pdf":
        input_format = InputFormat.PDF
    elif mime_type in {"image/png", "image/jpeg", "image/webp"}:
        input_format = InputFormat.IMAGE
    else:
        raise ValueError(f"Docling runner does not accept {mime_type}")

    ocr_options = RapidOcrOptions(lang=[language] if language else ["iso:en"])
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr_options,
        enable_remote_services=False,
        allow_external_plugins=False,
        artifacts_path=artifacts_path,
    )
    converter = DocumentConverter(
        allowed_formats=[input_format],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        },
    )
    result = converter.convert(input_path, max_num_pages=max_pages, max_file_size=max_bytes)
    doc = result.document

    segments: list[dict[str, object]] = []
    tables: list[dict[str, object]] = []
    reading_parts: list[tuple[int, str]] = []
    for item, _level in doc.iterate_items(traverse_pictures=False):
        if isinstance(item, TableItem):
            table_index = len(tables) + 1
            table_key = f"table-{table_index}"
            prov = item.prov[0] if getattr(item, "prov", None) else None
            page_no = int(getattr(prov, "page_no", 0) or 0) or None
            table_locator = _locator_from_prov(doc, prov) if prov is not None else None
            cells: list[dict[str, object]] = []
            max_row = 0
            max_col = 0
            for cell in item.data.table_cells:
                row = int(cell.start_row_offset_idx)
                col = int(cell.start_col_offset_idx)
                row_span = max(1, int(getattr(cell, "row_span", 1) or 1))
                col_span = max(1, int(getattr(cell, "col_span", 1) or 1))
                max_row = max(max_row, int(cell.end_row_offset_idx), row + row_span)
                max_col = max(max_col, int(cell.end_col_offset_idx), col + col_span)
                cell_locator: dict[str, object] = {
                    "kind": "table_cells",
                    "table_id": table_key,
                    "rows": [row],
                    "columns": [col],
                }
                if page_no is not None:
                    cell_locator["page"] = page_no
                text = str(getattr(cell, "text", "") or "")
                cells.append(
                    {
                        "row": row,
                        "column": col,
                        "row_span": row_span,
                        "column_span": col_span,
                        "raw_text": text,
                        "normalized_value": None,
                        "unit": None,
                        "is_header": bool(getattr(cell, "column_header", False) or getattr(cell, "row_header", False)),
                        "locator": cell_locator,
                    }
                )
                segments.append(
                    {
                        "modality": "table_cell",
                        "text": text,
                        "locator": cell_locator,
                        "derivation_kind": "ocr_or_layout_extracted",
                        "confidence": None,
                        "language": language or None,
                        "table_key": table_key,
                        "table_row": row,
                        "table_column": col,
                    }
                )
            tables.append(
                {
                    "table_key": table_key,
                    "page": page_no,
                    "locator": table_locator,
                    "rows": max_row,
                    "columns": max_col,
                    "cells": cells,
                }
            )
            rendered = item.export_to_markdown(doc=doc).strip()
            if rendered:
                reading_parts.append((page_no or 1, rendered))
            continue

        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        prov = item.prov[0] if getattr(item, "prov", None) else None
        locator = _locator_from_prov(doc, prov) if prov is not None else None
        if locator is None:
            # Rich OCR output without source geometry is not safe to expose as a
            # page-region citation. Keep it searchable only through the aggregate
            # compatibility document.
            continue
        segments.append(
            {
                "modality": "text",
                "text": text,
                "locator": locator,
                "derivation_kind": "ocr_or_layout_extracted",
                "confidence": None,
                "language": language or None,
            }
        )
        reading_parts.append((int(locator["page"]), text))

    # Build a stable compatibility text view while preserving page offsets. Precise
    # citations use the segment page-region locators above, not these aggregate offsets.
    reading_parts.sort(key=lambda item: item[0])
    text_parts: list[str] = []
    page_map: list[dict[str, int]] = []
    cursor = 0
    current_page: int | None = None
    page_start = 0
    for page_no, text in reading_parts:
        if current_page is None:
            current_page = page_no
            page_start = cursor
        elif page_no != current_page:
            page_map.append({"page": current_page, "char_start": page_start, "char_end": cursor})
            current_page = page_no
            page_start = cursor
        if text_parts:
            text_parts.append("\n\n")
            cursor += 2
        text_parts.append(text)
        cursor += len(text)
    if current_page is not None:
        page_map.append({"page": current_page, "char_start": page_start, "char_end": cursor})
    full_text = "".join(text_parts).strip()
    page_count = len(getattr(doc, "pages", {}) or {}) or (max((p for p, _ in reading_parts), default=1))
    payload_for_hash = {"text": full_text, "segments": segments, "tables": tables, "page_map": page_map}
    output_hash = hashlib.sha256(
        json.dumps(payload_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output = {
        "parser_id": "docling",
        "parser_revision": getattr(docling, "__version__", "unknown"),
        "model_revision": None,
        "text": full_text,
        "page_count": page_count,
        "page_map": page_map,
        "segments": segments,
        "tables": tables,
        "warnings": [] if full_text or tables else ["Docling produced no searchable text or table cells."],
        "output_hash": output_hash,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mime", required=True)
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--language", default="iso:en")
    parser.add_argument("--artifacts-path", required=True)
    args = parser.parse_args()
    run(
        Path(args.input),
        Path(args.output),
        mime_type=args.mime,
        max_pages=args.max_pages,
        max_bytes=args.max_bytes,
        language=args.language,
        artifacts_path=Path(args.artifacts_path),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
