from __future__ import annotations

from uuid import uuid4
import pytest

from ares.domain.models import RunCreate, RunMode
from ares.application.code_interpreter import CodeInterpreter, CodeExecutionResult


def test_run_create_plugin_validation() -> None:
    # Deduplication and normalization
    run = RunCreate(
        conversation_id=uuid4(),
        query="Research quantum algorithms",
        mode=RunMode.QUICK,
        plugins=["SPEED", "speed", "accuracy", "invalid_plugin", "code"],
    )
    assert run.plugins == ["speed", "accuracy", "code"]

    # Empty plugins
    run_empty = RunCreate(
        conversation_id=uuid4(),
        query="Research quantum algorithms",
        mode=RunMode.QUICK,
        plugins=[],
    )
    assert run_empty.plugins == []


def test_code_interpreter_execution_success() -> None:
    interp = CodeInterpreter(timeout_seconds=5.0)
    res = interp.execute("print(15 * 12 + 6)")
    assert res.success is True
    assert res.stdout == "186"
    assert res.exit_code == 0
    assert res.timed_out is False


def test_code_interpreter_math_module() -> None:
    interp = CodeInterpreter(timeout_seconds=5.0)
    res = interp.execute("import math; print(int(math.sqrt(1024)))")
    assert res.success is True
    assert res.stdout == "32"


def test_code_interpreter_timeout() -> None:
    interp = CodeInterpreter(timeout_seconds=0.5)
    res = interp.execute("import time; time.sleep(2.0)")
    assert res.success is False
    assert res.timed_out is True
    assert "timed out" in res.stderr.lower()


def test_code_interpreter_syntax_error() -> None:
    interp = CodeInterpreter(timeout_seconds=2.0)
    res = interp.execute("def invalid(: pass")
    assert res.success is False
    assert res.exit_code != 0
    assert "SyntaxError" in res.stderr


def test_code_interpreter_computational_intent() -> None:
    assert CodeInterpreter.detect_computational_intent("Calculate 25 * 40") is True
    assert CodeInterpreter.detect_computational_intent("Solve equation for x") is True
    assert CodeInterpreter.detect_computational_intent("Compute standard deviation") is True
    assert CodeInterpreter.detect_computational_intent("100 / 4 + 5") is True
    assert CodeInterpreter.detect_computational_intent("What is the history of quantum physics?") is False


def test_code_interpreter_extract_python_blocks() -> None:
    md = """Here is the calculation:
```python
x = 10
print(x * 2)
```
And another block:
```py
print('done')
```
"""
    blocks = CodeInterpreter.extract_python_blocks(md)
    assert len(blocks) == 2
    assert "print(x * 2)" in blocks[0]
    assert "print('done')" in blocks[1]
