from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from ares.adapters.pdf_parser import ParsedPdf
from ares.adapters.vlm_ocr import VlmOcrFallback
from ares.application.table_operations import TableOperationsTool, table_view_to_dataset
from ares.domain.assets import TableCellView, TableView
from ares.domain.tools import ToolContext
from ares.media.ocr_preprocessing import (
    deskew_image,
    detect_skew_angle,
    preprocess_ocr_image,
)
from PIL import Image, ImageDraw


def _create_sample_pdf(num_pages: int = 2, *, add_text: bool = True) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=300, height=300)
        # Blank or with basic stream
    from io import BytesIO

    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_page_classification_digital_vs_scanned() -> None:
    # Test ParsedPdf data structure holds page_types and scanned_pages
    parsed = ParsedPdf(
        text="Sample extracted text covering research facts.",
        page_map=[
            {"page": 1, "char_start": 0, "char_end": 45},
            {"page": 2, "char_start": 45, "char_end": 45},
        ],
        page_count=2,
        status="mixed",
        warnings=["1 of 2 pages are scanned or contain raster images requiring OCR."],
        parser_version="pypdf-test",
        page_types={1: "digital", 2: "scanned"},
        scanned_pages=[2],
    )
    assert parsed.page_types[1] == "digital"
    assert parsed.page_types[2] == "scanned"
    assert parsed.scanned_pages == [2]
    assert parsed.status == "mixed"


def test_ocr_preprocessing_deskew_and_denoise() -> None:
    # Create an image with horizontal black text lines on white background
    img = Image.new("L", (200, 200), color=255)
    draw = ImageDraw.Draw(img)
    # Draw horizontal bars
    for y in range(20, 180, 20):
        draw.line([(20, y), (180, y)], fill=0, width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    clean_bytes = buf.getvalue()

    # Preprocess clean image
    processed = preprocess_ocr_image(clean_bytes, deskew=True, denoise=True)
    assert isinstance(processed, bytes)
    assert len(processed) > 0

    # Create a rotated/skewed image
    rotated = img.rotate(5, fillcolor=255)
    rot_buf = io.BytesIO()
    rotated.save(rot_buf, format="PNG")
    rotated_bytes = rot_buf.getvalue()

    detected_angle = detect_skew_angle(rotated, max_angle=10.0, step=1.0)
    assert isinstance(detected_angle, float)

    deskewed = deskew_image(rotated_bytes, max_angle=10.0)
    assert isinstance(deskewed, bytes)
    assert len(deskewed) > 0


def test_vlm_ocr_fallback_selection() -> None:
    vlm = VlmOcrFallback(
        provider="ollama",
        confidence_threshold=0.60,
    )
    # Low confidence triggers fallback
    assert vlm.should_fallback(page_confidence=0.45, text="unclear text") is True
    # Empty text triggers fallback
    assert vlm.should_fallback(page_confidence=0.99, text="   ") is True
    # High confidence does not trigger fallback
    assert vlm.should_fallback(page_confidence=0.85, text="High quality OCR text") is False


def test_vlm_ocr_fallback_transcription_mocked() -> None:
    vlm = VlmOcrFallback(
        provider="ollama",
        ollama_base_url="http://mock-ollama:11434",
    )

    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Transcribed text from low-confidence scanned document."
        }
        mock_post.return_value = mock_response

        dummy_img = b"fake-png-bytes"
        result = vlm.transcribe_page_image(dummy_img, page_no=1)

        assert result is not None
        assert "Transcribed text" in result.text
        assert result.confidence == 0.88
        assert result.provider == "ollama"


def test_table_view_to_dataset_and_operations() -> None:
    # Create TableView with revenue and cost columns
    cells = [
        # Row 0: Headers
        TableCellView(row=0, column=0, raw_text="quarter", is_header=True),
        TableCellView(row=0, column=1, raw_text="revenue", is_header=True),
        # Row 1
        TableCellView(row=1, column=0, raw_text="Q1", normalized_value="Q1"),
        TableCellView(row=1, column=1, raw_text="100", normalized_value=100.0),
        # Row 2
        TableCellView(row=2, column=0, raw_text="Q2", normalized_value="Q2"),
        TableCellView(row=2, column=1, raw_text="150", normalized_value=150.0),
    ]
    from uuid import uuid4

    table = TableView(
        id=uuid4(),
        extraction_version_id=uuid4(),
        table_key="table-1",
        rows=3,
        columns=2,
        cells=cells,
    )

    dataset = table_view_to_dataset(table)
    assert len(dataset) == 2
    assert dataset[0] == {"quarter": "Q1", "revenue": 100.0}
    assert dataset[1] == {"quarter": "Q2", "revenue": 150.0}

    # Run TableOperationsTool on the extracted dataset
    from datetime import UTC, datetime

    tool = TableOperationsTool()
    context = ToolContext(
        workspace_id=uuid4(),
        run_id=uuid4(),
        lease_token=uuid4(),
        deadline=datetime.now(UTC),
        policy_version="v1",
        remaining_budgets={},
        permitted_asset_ids=[],
        permitted_source_ids=[],
    )
    result = tool.execute(
        context,
        inputs={
            "dataset": dataset,
            "operation": "filter",
            "params": {"column": "revenue", "operator": "greater_than", "value": 120.0},
        },
    )
    assert result.error_category is None
    filtered = result.payload["results"]
    assert len(filtered) == 1
    assert filtered[0]["quarter"] == "Q2"
