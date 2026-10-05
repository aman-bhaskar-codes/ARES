from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded local faster-whisper runner")
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--language", default="")
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise SystemExit("staged transcription input is missing")
    cache_dir = Path(args.cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.WARNING)
    from faster_whisper import WhisperModel

    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=str(cache_dir),
        cpu_threads=max(1, args.cpu_threads),
        num_workers=1,
        local_files_only=not args.allow_download,
    )
    segments_iter, info = model.transcribe(
        str(input_path),
        language=args.language or None,
        beam_size=max(1, args.beam_size),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        word_timestamps=False,
    )
    segments = []
    for segment in segments_iter:
        text = str(segment.text or "").strip()
        no_speech = getattr(segment, "no_speech_prob", None)
        if not text or (no_speech is not None and float(no_speech) >= 0.95):
            continue
        start_ms = max(0, int(round(float(segment.start) * 1000)))
        end_ms = max(start_ms + 1, int(round(float(segment.end) * 1000)))
        segments.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "no_speech_probability": float(no_speech) if no_speech is not None else None,
                "average_log_probability": (
                    float(segment.avg_logprob) if segment.avg_logprob is not None else None
                ),
            }
        )
    duration_seconds = float(getattr(info, "duration", 0.0) or 0.0)
    payload = {
        "language": getattr(info, "language", None),
        "language_probability": (
            float(getattr(info, "language_probability", 0.0))
            if getattr(info, "language_probability", None) is not None
            else None
        ),
        "model_revision": args.revision,
        "duration_ms": max(0, int(round(duration_seconds * 1000))),
        "segments": segments,
        "warnings": [] if segments else ["No speech was confidently transcribed from this media."],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
