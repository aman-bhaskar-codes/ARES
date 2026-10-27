from __future__ import annotations

import re
from dataclasses import dataclass


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
    """Disabled compatibility interface; never executes generated code on the worker."""

    DEFAULT_TIMEOUT_SECONDS: float = 5.0
    MAX_OUTPUT_BYTES: int = 8192

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        return False

    def execute(self, code: str, timeout_seconds: float | None = None) -> CodeExecutionResult:
        """Fail closed until a separately isolated execution service is available."""
        return CodeExecutionResult(
            success=False,
            stdout="",
            stderr="Code execution is disabled: an isolated runner has not been configured.",
            exit_code=-2,
            execution_time_seconds=0.0,
            code=code,
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
