from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
import re


@dataclass
class CodeExecutionResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_seconds: float
    code: str
    timed_out: bool = False


class CodeInterpreter:
    """Safe, isolated Python code execution engine for technical calculations and logic."""

    DEFAULT_TIMEOUT_SECONDS: float = 5.0
    MAX_OUTPUT_BYTES: int = 8192

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        return bool(sys.executable)

    def execute(self, code: str, timeout_seconds: float | None = None) -> CodeExecutionResult:
        """Execute a Python snippet in an isolated subprocess with strict timeouts."""
        timeout = timeout_seconds or self.timeout_seconds
        start_time = time.monotonic()

        # Sanitize environment: do not pass sensitive API keys or credentials
        safe_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONHASHSEED": "0",
            "PYTHONUNBUFFERED": "1",
            "LC_ALL": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
        }

        try:
            process = subprocess.run(
                [sys.executable, "-I", "-s", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )
            duration = time.monotonic() - start_time
            stdout = (process.stdout or "")[: self.MAX_OUTPUT_BYTES]
            stderr = (process.stderr or "")[: self.MAX_OUTPUT_BYTES]
            return CodeExecutionResult(
                success=(process.returncode == 0),
                stdout=stdout.strip(),
                stderr=stderr.strip(),
                exit_code=process.returncode,
                execution_time_seconds=round(duration, 3),
                code=code,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else str(exc.stdout or ""))[: self.MAX_OUTPUT_BYTES]
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else str(exc.stderr or ""))[: self.MAX_OUTPUT_BYTES]
            return CodeExecutionResult(
                success=False,
                stdout=stdout.strip(),
                stderr=f"Execution timed out after {timeout} seconds. {stderr}".strip(),
                exit_code=-1,
                execution_time_seconds=round(duration, 3),
                code=code,
                timed_out=True,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=f"Subprocess error: {type(exc).__name__}: {exc}",
                exit_code=-2,
                execution_time_seconds=round(duration, 3),
                code=code,
                timed_out=False,
            )

    @classmethod
    def detect_computational_intent(cls, text: str) -> bool:
        """Detect whether text requests math calculations, numerical analysis, or code execution."""
        lowered = text.lower()
        math_keywords = {
            "calculate",
            "compute",
            "eval",
            "evaluate",
            "solve",
            "equation",
            "formula",
            "derivative",
            "integral",
            "matrix",
            "fibonacci",
            "factorial",
            "standard deviation",
            "variance",
            "python script",
            "run code",
            "execute code",
        }
        if any(kw in lowered for kw in math_keywords):
            return True
        # Check for arithmetic operations like 24 * 12, (5 + 3) / 2
        if re.search(r"\b\d+[\s]*[\+\-\*\/\^%][\s]*\d+\b", text):
            return True
        return False

    @classmethod
    def extract_python_blocks(cls, markdown: str) -> list[str]:
        """Extract Python code blocks from markdown content."""
        pattern = r"```(?:python|py)?\n(.*?)```"
        matches = re.findall(pattern, markdown, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]
