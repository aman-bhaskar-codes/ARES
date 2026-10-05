from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "load_smoke.py"
    spec = importlib.util.spec_from_file_location("ares_load_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_percentile_uses_nearest_rank_and_handles_empty() -> None:
    module = _load_module()
    assert module.percentile([], 0.95) == 0.0
    assert module.percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_submission_model_can_represent_http_202_admission() -> None:
    module = _load_module()
    submission = module.Submission("run-1", 202, 12.5, admitted_at=10.0)
    assert submission.run_id == "run-1"
    assert 200 <= submission.status_code < 300
    assert submission.admitted_at == 10.0
