from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from ares.ports.transcription import TranscriptionResult, TranscriptionSegment


class TranscriptionUnavailable(RuntimeError):
    pass


class TranscriptionCancelled(RuntimeError):
    pass


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


class FasterWhisperTranscriber:
    """Run faster-whisper in a constrained child process.

    The research/media worker keeps database credentials, so untrusted media is decoded
    and transcribed in a child with a scrubbed environment, resource limits and no shell.
    Production defaults to ``local_files_only`` so an upload cannot trigger a surprise
    model download. The model cache is provisioned separately by the operator/image.
    """

    def __init__(
        self,
        *,
        model_id: str = "small",
        model_revision: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        model_cache_dir: str = ".data/models/whisper",
        cpu_threads: int = 4,
        local_files_only: bool = True,
        timeout_seconds: float = 420.0,
        memory_mb: int = 4096,
        cpu_seconds: int = 420,
        beam_size: int = 5,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision or model_id
        self.device = device
        self.compute_type = compute_type
        self.model_cache_dir = str(Path(model_cache_dir).resolve())
        self.cpu_threads = max(1, cpu_threads)
        self.local_files_only = local_files_only
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.cpu_seconds = cpu_seconds
        self.beam_size = max(1, beam_size)
        self.runner = Path(__file__).resolve().parents[1] / "media" / "asr_runner.py"

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    @staticmethod
    def _kill(process: subprocess.Popen[str]) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()

    def transcribe(
        self,
        path: str | Path,
        *,
        language: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        if not self.available():
            raise TranscriptionUnavailable(
                "faster-whisper is not installed in the media worker profile"
            )
        input_path = Path(path).resolve()
        if not input_path.is_file():
            raise TranscriptionUnavailable("staged transcription input is missing")
        args = [
            sys.executable,
            "-I",
            str(self.runner),
            "--input",
            str(input_path),
            "--model",
            self.model_id,
            "--revision",
            self.model_revision,
            "--cache-dir",
            self.model_cache_dir,
            "--device",
            self.device,
            "--compute-type",
            self.compute_type,
            "--cpu-threads",
            str(self.cpu_threads),
            "--beam-size",
            str(self.beam_size),
        ]
        if language:
            args.extend(["--language", language])
        if not self.local_files_only:
            args.append("--allow-download")

        # No DB/provider credentials are inherited by the parser/ASR child.
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LC_ALL": "C.UTF-8",
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_OFFLINE": "1" if self.local_files_only else "0",
        }
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=(
                    _preexec_limits(memory_mb=self.memory_mb, cpu_seconds=self.cpu_seconds)
                    if os.name == "posix"
                    else None
                ),
            )
        except OSError as exc:
            raise TranscriptionUnavailable(f"could not start ASR subprocess: {exc}") from exc

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            if cancelled is not None:
                try:
                    stop_requested = cancelled()
                except Exception:
                    # Deletion/revocation can invalidate the durable ingestion lease
                    # while ASR is active. Always reap the isolated child before the
                    # fencing exception escapes.
                    self._kill(process)
                    process.communicate()
                    raise
                if stop_requested:
                    self._kill(process)
                    process.communicate()
                    raise TranscriptionCancelled("transcription cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill(process)
                process.communicate()
                raise TranscriptionUnavailable("transcription exceeded its wall-clock limit")
            try:
                stdout, stderr = process.communicate(timeout=min(0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0:
            detail = (stderr or stdout or "ASR subprocess failed").strip().splitlines()
            raise TranscriptionUnavailable(detail[-1][:800] if detail else "ASR subprocess failed")
        if len(stdout) > 8_000_000 or len(stderr) > 2_000_000:
            raise TranscriptionUnavailable("ASR subprocess produced excessive output")
        try:
            payload = json.loads(stdout)
            raw_segments = payload.get("segments") or []
            segments = tuple(
                TranscriptionSegment(
                    start_ms=max(0, int(item["start_ms"])),
                    end_ms=max(int(item["start_ms"]) + 1, int(item["end_ms"])),
                    text=str(item["text"]).strip(),
                    average_log_probability=(
                        float(item["average_log_probability"])
                        if item.get("average_log_probability") is not None
                        else None
                    ),
                    no_speech_probability=(
                        float(item["no_speech_probability"])
                        if item.get("no_speech_probability") is not None
                        else None
                    ),
                )
                for item in raw_segments
                if str(item.get("text") or "").strip()
            )
            return TranscriptionResult(
                language=str(payload["language"]) if payload.get("language") else None,
                language_probability=(
                    float(payload["language_probability"])
                    if payload.get("language_probability") is not None
                    else None
                ),
                duration_ms=max(0, int(payload.get("duration_ms") or 0)),
                model_revision=str(payload.get("model_revision") or self.model_revision),
                segments=segments,
                warnings=[str(item) for item in payload.get("warnings") or []],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TranscriptionUnavailable("ASR subprocess returned an invalid result") from exc

class FasterWhisperSubprocessTranscriber(FasterWhisperTranscriber):
    """Configuration-shaped wrapper used by the worker runtime."""

    def __init__(
        self,
        *,
        model_path: str,
        model_revision: str,
        compute_type: str = "int8",
        cpu_threads: int = 2,
        beam_size: int = 5,
        language: str | None = None,
        timeout_seconds: float = 360.0,
        subprocess_memory_mb: int = 4096,
        subprocess_cpu_seconds: int = 420,
    ) -> None:
        model = Path(model_path).expanduser().resolve()
        self.default_language = language
        super().__init__(
            model_id=str(model),
            model_revision=model_revision,
            device="cpu",
            compute_type=compute_type,
            model_cache_dir=str(model.parent),
            cpu_threads=cpu_threads,
            local_files_only=True,
            timeout_seconds=timeout_seconds,
            memory_mb=subprocess_memory_mb,
            cpu_seconds=subprocess_cpu_seconds,
            beam_size=beam_size,
        )

    def transcribe(
        self,
        path: str | Path,
        *,
        language: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        return super().transcribe(
            path,
            language=language or self.default_language,
            cancelled=cancelled,
        )
