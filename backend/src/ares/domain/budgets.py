from __future__ import annotations

from dataclasses import dataclass

from ares.domain.models import RunMode

BUDGET_VERSION = "m07-v1"


@dataclass(frozen=True, slots=True)
class RunBudget:
    max_waves: int
    max_llm_calls: int
    max_search_requests: int
    max_documents: int
    per_run_http_concurrency: int
    model_input_tokens: int
    model_output_tokens: int
    wall_clock_seconds: int


BUDGETS = {
    RunMode.QUICK: RunBudget(1, 4, 3, 6, 2, 12_000, 3_000, 120),
    RunMode.RESEARCH: RunBudget(3, 10, 8, 20, 3, 40_000, 8_000, 300),
}
