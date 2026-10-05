from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ares.domain.assets import RichExtractionResult


class DoclingParseError(RuntimeError):
    pass


def _limit_child(memory_bytes: int, cpu_seconds: int) -> None:
    """Best-effort POSIX resource ceiling; container limits remain the outer boundary."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (96, 96))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except (ImportError, OSError, ValueError):
        # Windows/dev hosts rely on the process timeout and outer container profile.
        return


class DoclingSubprocessParser:
    """Run Docling/RapidOCR out-of-process with no application credentials.

    The child receives one staged local input path, one output path and a narrowly
    sanitized environment. Docling remote services are disabled in the runner and
    production media workers live on the internal data network, so parser/model code
    cannot inherit API keys or make arbitrary internet requests.
    """

    def __init__(
        self,
        *,
        max_bytes: int = 20 * 1024 * 1024,
        max_pages: int = 100,
        timeout_seconds: float = 120.0,
        memory_bytes: int = 3 * 1024 * 1024 * 1024,
        language: str = "iso:en",
        model_cache_dir: str = ".data/models/docling",
        max_output_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.memory_bytes = memory_bytes
        self.language = language
        self.model_cache_dir = Path(model_cache_dir).resolve()
        self.max_output_bytes = max_output_bytes
        self.runner = Path(__file__).resolve().parents[1] / "media" / "docling_runner.py"

    def parse(self, *, raw: bytes, mime_type: str, name: str) -> RichExtractionResult:
        if len(raw) > self.max_bytes:
            raise DoclingParseError("asset exceeds rich-parser byte limit")
        suffix = {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(mime_type)
        if suffix is None:
            raise DoclingParseError("Docling parser received an unsupported MIME type")
        if not self.model_cache_dir.exists():
            raise DoclingParseError(
                "Docling model artifacts are not provisioned; populate the configured model cache before enabling rich parsing"
            )

        with tempfile.TemporaryDirectory(prefix="ares-docling-") as directory:
            workdir = Path(directory)
            input_path = workdir / f"input{suffix}"
            output_path = workdir / "result.json"
            input_path.write_bytes(raw)

            # Never inherit the API/DB/provider environment. PATH is only retained so
            # native libraries invoked by the Python runtime can resolve normally.
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(workdir),
                "TMPDIR": str(workdir),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "DOCLING_ENABLE_REMOTE_SERVICES": "false",
                "NO_PROXY": "*",
                "no_proxy": "*",
            }
            command = [
                sys.executable,
                "-I",
                str(self.runner),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--mime",
                mime_type,
                "--max-pages",
                str(self.max_pages),
                "--max-bytes",
                str(self.max_bytes),
                "--language",
                self.language,
                "--artifacts-path",
                str(self.model_cache_dir),
            ]
            preexec = (
                (lambda: _limit_child(self.memory_bytes, max(5, int(self.timeout_seconds))))
                if os.name == "posix"
                else None
            )
            try:
                completed = subprocess.run(
                    command,
                    cwd=workdir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=self.timeout_seconds + 5,
                    preexec_fn=preexec,
                    text=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise DoclingParseError("Docling extraction exceeded its wall-clock limit") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "parser exited unsuccessfully").strip()
                raise DoclingParseError(f"Docling extraction failed: {detail[-1200:]}")
            try:
                size = output_path.stat().st_size
            except FileNotFoundError as exc:
                raise DoclingParseError("Docling parser did not publish an output file") from exc
            if size <= 0 or size > self.max_output_bytes:
                raise DoclingParseError("Docling parser output exceeded its publication boundary")
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                return RichExtractionResult.model_validate(payload)
            except Exception as exc:
                raise DoclingParseError("Docling parser returned invalid structured output") from exc


IsolatedDoclingParser = DoclingSubprocessParser
