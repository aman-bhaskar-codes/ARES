from __future__ import annotations

import argparse
import json
import re
import resource
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from ares.adapters.faster_whisper import FasterWhisperSubprocessTranscriber
from ares.application.media_ingestion import FFmpegMediaProcessor


def normalize_words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [token for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)?", normalized, flags=re.UNICODE) if token]


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, source in enumerate(left, start=1):
        current = [i]
        for j, target in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (0 if source == target else 1),
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float | None:
    ref = normalize_words(reference)
    if not ref:
        return None
    hyp = normalize_words(hypothesis)
    return edit_distance(ref, hyp) / len(ref)


def timestamp_mae_ms(reference: list[dict[str, Any]], observed: list[Any]) -> float | None:
    pairs = min(len(reference), len(observed))
    if pairs == 0:
        return None
    errors: list[float] = []
    for index in range(pairs):
        expected = reference[index]
        segment = observed[index]
        if "start_ms" in expected:
            errors.append(abs(float(expected["start_ms"]) - float(segment.locator.start_ms)))
        if "end_ms" in expected:
            errors.append(abs(float(expected["end_ms"]) - float(segment.locator.end_ms)))
    return mean(errors) if errors else None


@dataclass
class CaseResult:
    id: str
    path: str
    mime_type: str
    condition: str | None
    language: str | None
    success: bool
    error: str | None
    duration_ms: int | None
    elapsed_seconds: float
    real_time_factor: float | None
    word_error_rate: float | None
    timestamp_mae_ms: float | None
    frame_count: int
    sampled_times_ms: list[int]
    warnings: list[str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ARES M09 local audio/video evidence processing.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report", default="evals/reports/media_latest.json")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--max-audio-seconds", type=int, default=600)
    parser.add_argument("--max-video-seconds", type=int, default=300)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("media evaluation manifest must contain a non-empty 'cases' list")

    transcriber = FasterWhisperSubprocessTranscriber(
        model_path=args.model_path,
        model_revision=args.model_revision,
        cpu_threads=args.cpu_threads,
        beam_size=args.beam_size,
    )
    processor = FFmpegMediaProcessor(
        transcriber,
        max_audio_duration_seconds=args.max_audio_seconds,
        max_video_duration_seconds=args.max_video_seconds,
    )
    if not processor.available():
        raise SystemExit("ffmpeg/ffprobe are required for media evaluation")

    results: list[CaseResult] = []
    for raw_case in cases:
        case_id = str(raw_case.get("id") or "").strip()
        relative = str(raw_case.get("path") or "").strip()
        mime_type = str(raw_case.get("mime_type") or "").strip()
        if not case_id or not relative or not mime_type:
            raise SystemExit("every case requires id, path, and mime_type")
        if not str(raw_case.get("license_note") or "").strip():
            raise SystemExit(f"case {case_id!r} is missing license_note")
        path = (manifest_path.parent / relative).resolve()
        try:
            path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise SystemExit(f"case {case_id!r} escapes the manifest directory") from exc
        started = time.monotonic()
        try:
            media = processor.extract(path.read_bytes(), mime_type=mime_type, name=path.name)
            elapsed = time.monotonic() - started
            transcript = " ".join(
                (segment.text or "").strip()
                for segment in media.extraction.segments
                if segment.locator.kind == "time_range" and (segment.text or "").strip()
            )
            reference_text = raw_case.get("reference_text")
            reference_segments = raw_case.get("reference_segments") or []
            rtf = elapsed / max(0.001, media.duration_ms / 1000)
            sampled = media.media_metadata.get("sampled_times_ms") or []
            wer = word_error_rate(str(reference_text), transcript) if reference_text else None
            timestamp_error = (
                timestamp_mae_ms(reference_segments, media.extraction.segments)
                if reference_segments
                else None
            )
            results.append(
                CaseResult(
                    id=case_id,
                    path=relative,
                    mime_type=mime_type,
                    condition=raw_case.get("condition"),
                    language=raw_case.get("language"),
                    success=True,
                    error=None,
                    duration_ms=media.duration_ms,
                    elapsed_seconds=round(elapsed, 4),
                    real_time_factor=round(rtf, 4),
                    word_error_rate=round(wer, 4) if wer is not None else None,
                    timestamp_mae_ms=(
                        round(timestamp_error, 2) if timestamp_error is not None else None
                    ),
                    frame_count=len(media.frames),
                    sampled_times_ms=[int(value) for value in sampled],
                    warnings=list(media.extraction.warnings),
                )
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            results.append(
                CaseResult(
                    id=case_id,
                    path=relative,
                    mime_type=mime_type,
                    condition=raw_case.get("condition"),
                    language=raw_case.get("language"),
                    success=False,
                    error=f"{type(exc).__name__}: {str(exc)[:600]}",
                    duration_ms=None,
                    elapsed_seconds=round(elapsed, 4),
                    real_time_factor=None,
                    word_error_rate=None,
                    timestamp_mae_ms=None,
                    frame_count=0,
                    sampled_times_ms=[],
                    warnings=[],
                )
            )

    successful = [item for item in results if item.success]
    wers = [item.word_error_rate for item in successful if item.word_error_rate is not None]
    rtfs = [item.real_time_factor for item in successful if item.real_time_factor is not None]
    timestamp_errors = [
        item.timestamp_mae_ms for item in successful if item.timestamp_mae_ms is not None
    ]
    report = {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "model_path": str(Path(args.model_path).expanduser().resolve()),
        "model_revision": args.model_revision,
        "cases": [asdict(item) for item in results],
        "summary": {
            "total": len(results),
            "successful": len(successful),
            "failed": len(results) - len(successful),
            "mean_wer": round(mean(wers), 4) if wers else None,
            "mean_real_time_factor": round(mean(rtfs), 4) if rtfs else None,
            "mean_timestamp_mae_ms": round(mean(timestamp_errors), 2) if timestamp_errors else None,
            "peak_child_rss_kib": int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
        },
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report_path)
    if report["summary"]["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
