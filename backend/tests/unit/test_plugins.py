from __future__ import annotations

from uuid import uuid4

from ares.application.code_interpreter import CodeInterpreter
from ares.domain.models import RunCreate, RunMode


def test_run_create_plugin_validation() -> None:
    # Deduplication and normalization
    run = RunCreate(
        conversation_id=uuid4(),
        query="Research quantum algorithms",
        mode=RunMode.QUICK,
        plugins=["SPEED", "speed", "accuracy", "invalid_plugin", "code"],
    )
    assert run.plugins == ["speed", "accuracy"]

    # Empty plugins
    run_empty = RunCreate(
        conversation_id=uuid4(),
        query="Research quantum algorithms",
        mode=RunMode.QUICK,
        plugins=[],
    )
    assert run_empty.plugins == []


def test_code_interpreter_is_disabled() -> None:
    interp = CodeInterpreter()
    assert not interp.is_available()
    result = interp.execute("print(15 * 12)")
    assert not result.success
    assert not result.stdout
    assert "disabled" in result.stderr


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
