from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
import wave
from array import array
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import UUID

from ares.domain.assets import (
    ExtractionSegmentDraft,
    MediaFrameDraft,
    MediaTrackDraft,
    RichExtractionResult,
    TimeRangeLocator,
)
from ares.ports.transcription import TranscriptionProvider, TranscriptionResult


AUDIO_MIME_TYPES = {"audio/wav", "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg"}
VIDEO_MIME_TYPES = {"video/mp4", "video/webm"}
MEDIA_MIME_TYPES = AUDIO_MIME_TYPES | VIDEO_MIME_TYPES


class MediaProcessingError(ValueError):
    pass


class MediaProcessingUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaIngestionResult:
    extraction: RichExtractionResult
    duration_ms: int
    width: int | None
    height: int | None
    tracks: list[MediaTrackDraft] = field(default_factory=list)
    frames: list[MediaFrameDraft] = field(default_factory=list)
    media_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Probe:
    duration_ms: int | None
    tracks: list[MediaTrackDraft]
    width: int | None
    height: int | None
    has_audio: bool
    has_video: bool


def _preexec_limits(*, memory_mb: int, cpu_seconds: int):
    def apply() -> None:
        os.setsid()
        try:
            import resource

            memory = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
            resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ImportError, OSError, ValueError):
            pass

    return apply


class FFmpegMediaProcessor:
    """Bounded local media normalization and PTS-backed frame sampling.

    Only staged local bytes are accepted. Subprocesses receive an explicit file/pipe
    protocol allowlist, no shell, a scrubbed environment, bounded resources, and a
    cancellation callback. Video timing is taken from decoded presentation timestamps.
    """

    _PTS = re.compile(r"\bpts_time:([-+0-9.eE]+)")

    def __init__(
        self,
        transcriber: TranscriptionProvider | None,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        max_audio_duration_seconds: int = 600,
        max_video_duration_seconds: int = 300,
        max_video_source_pixels: int = 12_000_000,
        max_selected_frames: int = 60,
        baseline_frames: int = 31,
        scene_threshold: float = 0.35,
        timeout_seconds: float = 420.0,
        subprocess_memory_mb: int = 3072,
        subprocess_cpu_seconds: int = 420,
    ) -> None:
        self.transcriber = transcriber
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.max_audio_duration_seconds = max_audio_duration_seconds
        self.max_video_duration_seconds = max_video_duration_seconds
        self.max_video_source_pixels = max_video_source_pixels
        self.max_selected_frames = max(2, max_selected_frames)
        self.baseline_frames = max(2, min(self.max_selected_frames, baseline_frames))
        self.scene_threshold = scene_threshold
        self.timeout_seconds = timeout_seconds
        self.subprocess_memory_mb = subprocess_memory_mb
        self.subprocess_cpu_seconds = subprocess_cpu_seconds

    def available(self) -> bool:
        return bool(shutil.which(self.ffmpeg_binary) and shutil.which(self.ffprobe_binary))

    def extract(
        self,
        raw: bytes,
        *,
        mime_type: str,
        name: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> MediaIngestionResult:
        del name  # filename never reaches ffmpeg arguments; staged suffix is controlled here.
        if mime_type not in MEDIA_MIME_TYPES:
            raise MediaProcessingError(f"unsupported media type {mime_type}")
        if cancelled is not None and cancelled():
            raise MediaProcessingError("media processing cancelled")
        suffix = {
            "audio/wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
        }[mime_type]
        origin = UUID(bytes=hashlib.sha256(raw).digest()[:16])
        with tempfile.TemporaryDirectory(prefix="ares-media-") as directory:
            root = Path(directory)
            source = root / f"input{suffix}"
            source.write_bytes(raw)
            probe = self._probe(source, cancelled=cancelled)
            if mime_type in AUDIO_MIME_TYPES:
                return self._extract_audio(source, probe, origin=origin, cancelled=cancelled)
            return self._extract_video(source, probe, root=root, origin=origin, cancelled=cancelled)

    @staticmethod
    def _kill(process: subprocess.Popen[str]) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()

    def _run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        log_limit: int = 2_000_000,
        allow_no_output: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LC_ALL": "C.UTF-8",
            "AV_LOG_FORCE_NOCOLOR": "1",
        }
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            preexec_fn=(
                _preexec_limits(
                    memory_mb=self.subprocess_memory_mb,
                    cpu_seconds=self.subprocess_cpu_seconds,
                )
                if os.name == "posix"
                else None
            ),
        )
        deadline = time.monotonic() + (timeout or self.timeout_seconds)
        while True:
            if cancelled is not None:
                try:
                    stop_requested = cancelled()
                except Exception:
                    # A deleted/revoked ingestion invalidates the lease while a local
                    # parser may still be running. Kill the subprocess before surfacing
                    # the fencing error so no orphan decoder survives the request.
                    self._kill(process)
                    process.communicate()
                    raise
                if stop_requested:
                    self._kill(process)
                    process.communicate()
                    raise MediaProcessingError("media processing cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill(process)
                process.communicate()
                raise MediaProcessingUnavailable("media subprocess exceeded its wall-clock limit")
            try:
                stdout, stderr = process.communicate(timeout=min(0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if len(stdout) > log_limit or len(stderr) > log_limit:
            raise MediaProcessingError("media subprocess produced excessive diagnostic output")
        completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if completed.returncode != 0:
            no_selected_frames = (
                allow_no_output
                and "No filtered frames for output stream" in stderr
                and "Nothing was written into output file" in stderr
            )
            if not no_selected_frames:
                detail = (stderr or stdout).strip().splitlines()[-1:] or ["unknown media error"]
                raise MediaProcessingError(f"media subprocess failed: {detail[0][:500]}")
        return completed

    @staticmethod
    def _to_ms(value: object) -> int | None:
        if value in {None, "", "N/A"}:
            return None
        try:
            seconds = float(str(value))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return int(round(seconds * 1000))

    def _probe(self, path: Path, *, cancelled: Callable[[], bool] | None) -> _Probe:
        result = self._run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration:stream=index,codec_type,codec_name,duration,sample_rate,channels,width,height,avg_frame_rate:stream_tags=language",
                "-of",
                "json",
                str(path),
            ],
            timeout=min(30.0, self.timeout_seconds),
            cancelled=cancelled,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise MediaProcessingError("ffprobe returned invalid JSON") from exc
        tracks: list[MediaTrackDraft] = []
        widths: list[int] = []
        heights: list[int] = []
        for stream in payload.get("streams", []):
            track_type = stream.get("codec_type")
            if track_type not in {"audio", "video"}:
                continue
            width = int(stream["width"]) if stream.get("width") else None
            height = int(stream["height"]) if stream.get("height") else None
            if width and height:
                widths.append(width)
                heights.append(height)
            try:
                sample_rate = (
                    int(stream["sample_rate"])
                    if stream.get("sample_rate") not in {None, "", "N/A"}
                    else None
                )
            except (TypeError, ValueError):
                sample_rate = None
            try:
                channels = (
                    int(stream["channels"])
                    if stream.get("channels") not in {None, "", "N/A"}
                    else None
                )
            except (TypeError, ValueError):
                channels = None
            tags = stream.get("tags") or {}
            tracks.append(
                MediaTrackDraft(
                    track_type=track_type,
                    stream_index=int(stream.get("index", 0)),
                    codec_name=str(stream.get("codec_name")) if stream.get("codec_name") else None,
                    language=str(tags.get("language")) if tags.get("language") else None,
                    duration_ms=self._to_ms(stream.get("duration")),
                    sample_rate=sample_rate,
                    channels=channels,
                    width=width,
                    height=height,
                    average_frame_rate=(
                        str(stream.get("avg_frame_rate"))
                        if track_type == "video" and stream.get("avg_frame_rate")
                        else None
                    ),
                )
            )
        if not tracks:
            raise MediaProcessingError("media contains no supported audio or video track")
        duration_ms = self._to_ms((payload.get("format") or {}).get("duration"))
        return _Probe(
            duration_ms=duration_ms,
            tracks=tracks,
            width=max(widths) if widths else None,
            height=max(heights) if heights else None,
            has_audio=any(item.track_type == "audio" for item in tracks),
            has_video=any(item.track_type == "video" for item in tracks),
        )

    def _normalize_audio(
        self,
        source: Path,
        output: Path,
        *,
        duration_limit_seconds: int,
        cancelled: Callable[[], bool] | None,
    ) -> int:
        self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-t",
                str(duration_limit_seconds + 1),
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-threads",
                "1",
                "-y",
                str(output),
            ],
            cancelled=cancelled,
        )
        try:
            with wave.open(str(output), "rb") as reader:
                if reader.getframerate() <= 0:
                    raise MediaProcessingError("normalized audio has an invalid sample rate")
                duration_ms = int(round(reader.getnframes() * 1000 / reader.getframerate()))
        except wave.Error as exc:
            raise MediaProcessingError("normalized audio could not be validated") from exc
        if duration_ms > duration_limit_seconds * 1000:
            raise MediaProcessingError(
                f"decoded audio exceeds the {duration_limit_seconds // 60}-minute duration limit"
            )
        return duration_ms

    @staticmethod
    def _waveform_peaks(wav: Path, *, bins: int = 120) -> list[float]:
        """Return a bounded normalized peak envelope from authoritative PCM."""
        try:
            with wave.open(str(wav), "rb") as reader:
                if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
                    return []
                total_frames = reader.getnframes()
                if total_frames <= 0:
                    return []
                target_bins = max(1, min(bins, total_frames))
                frames_per_bin = max(1, math.ceil(total_frames / target_bins))
                peaks: list[float] = []
                while len(peaks) < target_bins:
                    payload = reader.readframes(frames_per_bin)
                    if not payload:
                        break
                    samples = array("h")
                    samples.frombytes(payload)
                    if sys.byteorder != "little":
                        samples.byteswap()
                    peak = max((abs(value) for value in samples), default=0)
                    peaks.append(round(min(1.0, peak / 32768.0), 4))
                return peaks
        except (OSError, wave.Error, ValueError):
            return []

    def _transcribe(
        self,
        wav: Path,
        *,
        duration_ms: int,
        cancelled: Callable[[], bool] | None,
    ) -> TranscriptionResult | None:
        if self.transcriber is None:
            return None
        result = self.transcriber.transcribe(wav, cancelled=cancelled)
        if result.duration_ms and abs(result.duration_ms - duration_ms) > max(
            2_000, int(duration_ms * 0.05)
        ):
            result.warnings.append(
                "ASR-reported duration differed from decoded PCM duration; decoded PCM duration is authoritative."
            )
        return result

    @staticmethod
    def _transcript_extraction(
        transcription: TranscriptionResult | None,
        *,
        duration_ms: int,
        track: str,
        origin_group_id: UUID,
        warnings: list[str],
    ) -> RichExtractionResult:
        lines: list[str] = []
        segments: list[ExtractionSegmentDraft] = []
        if transcription is not None:
            for item in transcription.segments:
                text = item.text.strip()
                if not text:
                    continue
                lines.append(text)
                segments.append(
                    ExtractionSegmentDraft(
                        modality="audio",
                        text=text,
                        locator=TimeRangeLocator(
                            start_ms=max(0, item.start_ms),
                            end_ms=min(duration_ms, max(item.start_ms + 1, item.end_ms)),
                            track="audio" if track == "audio" else "video",
                        ),
                        derivation_kind="asr_transcript",
                        language=transcription.language,
                        origin_group_id=origin_group_id,
                    )
                )
            warnings.extend(transcription.warnings)
        if transcription is None:
            warnings.append(
                "Local transcription is unavailable; media was admitted without transcript evidence."
            )
        elif not segments:
            warnings.append(
                "No speech segments were published; silence/no-speech checks produced no transcript evidence."
            )
        text = "\n".join(lines)
        output_payload = {
            "duration_ms": duration_ms,
            "track": track,
            "language": transcription.language if transcription else None,
            "model": transcription.model_revision if transcription else None,
            "segments": [segment.model_dump(mode="json") for segment in segments],
            "warnings": warnings,
        }
        return RichExtractionResult(
            parser_id="faster-whisper" if transcription else "media-no-asr",
            parser_revision="1.2.1" if transcription else "m09",
            model_revision=transcription.model_revision if transcription else None,
            text=text,
            segments=segments,
            warnings=list(dict.fromkeys(warnings)),
            output_hash=hashlib.sha256(
                json.dumps(output_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )

    def _extract_audio(
        self,
        source: Path,
        probe: _Probe,
        *,
        origin: UUID,
        cancelled: Callable[[], bool] | None,
    ) -> MediaIngestionResult:
        if not probe.has_audio:
            raise MediaProcessingError("audio upload contains no decodable audio track")
        if (
            probe.duration_ms is not None
            and probe.duration_ms > (self.max_audio_duration_seconds + 1) * 1000
        ):
            raise MediaProcessingError(
                f"audio exceeds the {self.max_audio_duration_seconds // 60}-minute duration limit"
            )
        wav = source.with_name("normalized.wav")
        duration_ms = self._normalize_audio(
            source,
            wav,
            duration_limit_seconds=self.max_audio_duration_seconds,
            cancelled=cancelled,
        )
        waveform_peaks = self._waveform_peaks(wav)
        transcription = self._transcribe(wav, duration_ms=duration_ms, cancelled=cancelled)
        warnings: list[str] = []
        extraction = self._transcript_extraction(
            transcription,
            duration_ms=duration_ms,
            track="audio",
            origin_group_id=origin,
            warnings=warnings,
        )
        return MediaIngestionResult(
            extraction=extraction,
            duration_ms=duration_ms,
            width=None,
            height=None,
            tracks=probe.tracks,
            media_metadata={
                "kind": "audio",
                "decoded_duration_ms": duration_ms,
                "transcript_segments": len(extraction.segments),
                "waveform_peaks": waveform_peaks,
                "asr_model": transcription.model_revision if transcription else None,
            },
        )

    def _has_frame_beyond_limit(
        self,
        source: Path,
        *,
        cancelled: Callable[[], bool] | None,
    ) -> bool:
        boundary = self.max_video_duration_seconds + 0.001
        result = self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "info",
                "-protocol_whitelist",
                "file,pipe",
                "-t",
                str(self.max_video_duration_seconds + 1),
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                f"select='gte(t\\,{boundary:.3f})',showinfo",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            log_limit=2_000_000,
            cancelled=cancelled,
        )
        return any(
            float(match.group(1)) > self.max_video_duration_seconds
            for match in self._PTS.finditer(result.stderr)
        )

    def _sample_frames(
        self,
        source: Path,
        *,
        root: Path,
        width: int,
        height: int,
        duration_ms: int | None,
        cancelled: Callable[[], bool] | None,
    ) -> tuple[list[MediaFrameDraft], list[int]]:
        if width * height > self.max_video_source_pixels:
            raise MediaProcessingError(
                f"decoded video dimensions exceed the {self.max_video_source_pixels:,}-pixel source limit"
            )
        if self._has_frame_beyond_limit(source, cancelled=cancelled):
            raise MediaProcessingError(
                f"decoded video exceeds the {self.max_video_duration_seconds // 60}-minute duration limit"
            )
        frame_root = root / "frames"
        frame_root.mkdir()
        max_scan_seconds = self.max_video_duration_seconds + 1
        known_seconds = (duration_ms / 1000) if duration_ms is not None else None
        sampling_span = min(
            float(self.max_video_duration_seconds),
            max(1.0, known_seconds)
            if known_seconds is not None
            else float(self.max_video_duration_seconds),
        )
        interval = sampling_span / max(1, self.baseline_frames - 1)
        periodic = self._extract_frame_set(
            source,
            output_pattern=frame_root / "periodic-%03d.jpg",
            select_expression=f"isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval:.6f})",
            limit=self.baseline_frames,
            source_kind="periodic",
            max_scan_seconds=max_scan_seconds,
            cancelled=cancelled,
        )
        remaining = max(0, self.max_selected_frames - len(periodic))
        scene: list[MediaFrameDraft] = []
        if remaining:
            scene = self._extract_frame_set(
                source,
                output_pattern=frame_root / "scene-%03d.jpg",
                select_expression=f"gt(scene\\,{self.scene_threshold:.4f})",
                limit=remaining,
                source_kind="scene",
                max_scan_seconds=self.max_video_duration_seconds,
                allow_no_output=True,
                cancelled=cancelled,
            )
        combined = self._deduplicate_frames([*periodic, *scene])[: self.max_selected_frames]
        sampled_times = sorted({frame.presentation_time_ms for frame in [*periodic, *scene]})
        return combined, sampled_times

    def _extract_frame_set(
        self,
        source: Path,
        *,
        output_pattern: Path,
        select_expression: str,
        limit: int,
        source_kind: str,
        max_scan_seconds: int,
        allow_no_output: bool = False,
        cancelled: Callable[[], bool] | None,
    ) -> list[MediaFrameDraft]:
        if limit <= 0:
            return []
        result = self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "info",
                "-protocol_whitelist",
                "file,pipe",
                "-t",
                str(max_scan_seconds),
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                f"select='{select_expression}',scale=1280:720:force_original_aspect_ratio=decrease,showinfo",
                "-fps_mode",
                "vfr",
                "-frames:v",
                str(limit),
                "-q:v",
                "3",
                "-threads",
                "1",
                "-y",
                str(output_pattern),
            ],
            log_limit=4_000_000,
            allow_no_output=allow_no_output,
            cancelled=cancelled,
        )
        times = [float(match.group(1)) for match in self._PTS.finditer(result.stderr)]
        files = sorted(output_pattern.parent.glob(output_pattern.name.replace("%03d", "*")))
        if len(times) != len(files):
            if len(times) < len(files):
                raise MediaProcessingError(
                    "could not resolve presentation timestamps for sampled frames"
                )
            times = times[-len(files) :] if files else []
        frames: list[MediaFrameDraft] = []
        for timestamp, path in zip(times, files, strict=True):
            raw = path.read_bytes()
            try:
                from PIL import Image

                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    frame_width, frame_height = image.size
                    grayscale = image.convert("L").resize((8, 8))
                    pixels = list(grayscale.get_flattened_data())
                    mean = sum(pixels) / max(1, len(pixels))
                    bits = 0
                    for value in pixels:
                        bits = (bits << 1) | int(value >= mean)
                    perceptual_hash = f"{bits:016x}"
            except Exception as exc:
                raise MediaProcessingError("sampled frame could not be validated") from exc
            frames.append(
                MediaFrameDraft(
                    presentation_time_ms=max(0, int(round(timestamp * 1000))),
                    source_kind=source_kind,
                    width=frame_width,
                    height=frame_height,
                    content_hash=hashlib.sha256(raw).hexdigest(),
                    perceptual_hash=perceptual_hash,
                    jpeg_bytes=raw,
                )
            )
        return frames

    @staticmethod
    def _hamming(left: str | None, right: str | None) -> int:
        if not left or not right:
            return 64
        try:
            return (int(left, 16) ^ int(right, 16)).bit_count()
        except ValueError:
            return 64

    def _deduplicate_frames(self, frames: list[MediaFrameDraft]) -> list[MediaFrameDraft]:
        ordered = sorted(
            frames,
            key=lambda item: (item.presentation_time_ms, item.source_kind != "periodic"),
        )
        retained: list[MediaFrameDraft] = []
        for frame in ordered:
            duplicate = False
            for previous in retained:
                close_in_time = (
                    abs(previous.presentation_time_ms - frame.presentation_time_ms) <= 500
                )
                visually_same = self._hamming(previous.perceptual_hash, frame.perceptual_hash) <= 3
                if close_in_time or (frame.source_kind == "scene" and visually_same):
                    duplicate = True
                    break
            if not duplicate:
                retained.append(frame)
        return retained

    def _extract_video(
        self,
        source: Path,
        probe: _Probe,
        *,
        root: Path,
        origin: UUID,
        cancelled: Callable[[], bool] | None,
    ) -> MediaIngestionResult:
        if not probe.has_video:
            raise MediaProcessingError("video upload contains no decodable video track")
        if probe.width is None or probe.height is None:
            raise MediaProcessingError("video dimensions are unavailable")
        if (
            probe.duration_ms is not None
            and probe.duration_ms > (self.max_video_duration_seconds + 1) * 1000
        ):
            raise MediaProcessingError(
                f"video exceeds the {self.max_video_duration_seconds // 60}-minute duration limit"
            )
        frames, sampled_times = self._sample_frames(
            source,
            root=root,
            width=probe.width,
            height=probe.height,
            duration_ms=probe.duration_ms,
            cancelled=cancelled,
        )
        duration_ms = probe.duration_ms or (max(sampled_times) if sampled_times else 0)
        duration_ms = min(duration_ms, self.max_video_duration_seconds * 1000)
        transcription: TranscriptionResult | None = None
        waveform_peaks: list[float] = []
        warnings: list[str] = []
        if probe.has_audio:
            wav = root / "normalized.wav"
            audio_duration_ms = self._normalize_audio(
                source,
                wav,
                duration_limit_seconds=self.max_video_duration_seconds,
                cancelled=cancelled,
            )
            waveform_peaks = self._waveform_peaks(wav)
            transcription = self._transcribe(
                wav, duration_ms=audio_duration_ms, cancelled=cancelled
            )
            duration_ms = max(
                duration_ms,
                min(audio_duration_ms, self.max_video_duration_seconds * 1000),
            )
        else:
            warnings.append("Video has no audio track; transcript evidence is unavailable.")
        extraction = self._transcript_extraction(
            transcription,
            duration_ms=max(1, duration_ms),
            track="video",
            origin_group_id=origin,
            warnings=warnings,
        )
        coverage_warning = "Visual evidence is sampled, not exhaustive. Events between sampled frames may be missed."
        return MediaIngestionResult(
            extraction=extraction,
            duration_ms=max(1, duration_ms),
            width=probe.width,
            height=probe.height,
            tracks=probe.tracks,
            frames=frames,
            media_metadata={
                "kind": "video",
                "decoded_duration_ms": max(1, duration_ms),
                "sampling_strategy": "periodic+scene-v1",
                "sampled_times_ms": sampled_times,
                "retained_frame_count": len(frames),
                "visual_coverage_warning": coverage_warning,
                "transcript_segments": len(extraction.segments),
                "waveform_peaks": waveform_peaks,
                "asr_model": transcription.model_revision if transcription else None,
            },
        )
