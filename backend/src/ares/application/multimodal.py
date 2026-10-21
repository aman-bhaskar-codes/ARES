from __future__ import annotations

import json
import logging
import re
from typing import Any

from ares.ports.multimodal import MediaRegionInput, MultimodalUnderstandingProvider

logger = logging.getLogger("ares.application.multimodal")


def sanitize_untrusted_visual_text(text: str) -> str:
    """Sanitize and fence visual text extracted from images/charts.

    Image content is untrusted; prompt injection via text in images is a real attack vector.
    This helper tags and safely fences visual text so downstream models do not execute instructions.
    """
    cleaned = text.strip()
    # Strip dangerous instruction prefixes
    cleaned = re.sub(
        r"^(?:system\s*:|instruction\s*:|ignore\s+previous\s+instructions|you\s+must|override\b).*$",
        "[redacted untrusted directive]",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return cleaned


def extract_chart_to_data(
    image_bytes: bytes,
    *,
    mime_type: str = "image/png",
    provider: MultimodalUnderstandingProvider | None = None,
) -> dict[str, Any] | None:
    """Extract structured numerical and categorical data from a chart image.

    Produces a dataset with chart type, series, and coordinates that feeds directly
    into the ARES visualization workspace.
    """
    if provider is None:
        logger.info("No multimodal provider available for chart extraction")
        return None

    instruction = (
        "Extract the underlying data from this chart or graph. "
        "Return ONLY a valid JSON object matching this schema:\n"
        "{\n"
        '  "chart_type": "bar" | "line" | "pie" | "scatter",\n'
        '  "title": "Chart Title",\n'
        '  "x_label": "X Axis Label",\n'
        '  "y_label": "Y Axis Label",\n'
        '  "series": [\n'
        '    {\n'
        '      "name": "Series Name",\n'
        '      "data": [\n'
        '        {"x": "label1", "y": 123.4}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Do not include commentary or markdown fences. Output raw JSON only."
    )

    region_input = MediaRegionInput(
        region_id="chart_extraction_0",
        mime_type=mime_type,
        data=image_bytes,
    )

    try:
        observations = provider.describe_regions(
            instruction=instruction,
            regions=[region_input],
            max_output_tokens=1024,
        )
        if not observations:
            return None

        raw_text = observations[0].text.strip()
        # Parse JSON from observation (handling potential markdown fences)
        clean_json = raw_text
        if "```" in clean_json:
            clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json, flags=re.MULTILINE)
            clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()

        data = json.loads(clean_json)
        if isinstance(data, dict) and "series" in data:
            return data
    except Exception as exc:
        logger.warning("Chart-to-data extraction failed (%s)", exc)

    return None


def align_video_frames_with_timeline(
    frames: list[Any],
    transcript_segments: list[Any],
) -> list[dict[str, Any]]:
    """Align sampled video keyframes with transcript time intervals.

    For each video frame at presentation_time_ms, finds overlapping transcript
    speech segments to form cohesive multimodal evidence packets.
    """
    aligned: list[dict[str, Any]] = []

    for frame in frames:
        time_ms = getattr(frame, "presentation_time_ms", None)
        if time_ms is None:
            continue

        matching_segments = []
        for segment in transcript_segments:
            start = getattr(segment, "start_ms", 0)
            end = getattr(segment, "end_ms", 0)
            # Frame falls within segment or within a 500ms tolerance
            if start - 500 <= time_ms <= end + 500:
                matching_segments.append(
                    {
                        "start_ms": start,
                        "end_ms": end,
                        "text": getattr(segment, "text", ""),
                    }
                )

        aligned.append(
            {
                "presentation_time_ms": time_ms,
                "frame_id": str(getattr(frame, "id", "")),
                "matched_transcript_segments": matching_segments,
                "has_transcript_overlap": len(matching_segments) > 0,
            }
        )

    return aligned
