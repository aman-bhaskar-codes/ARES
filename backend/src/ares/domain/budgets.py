from __future__ import annotations

from dataclasses import dataclass

from typing import Literal

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
    RunMode.QUICK: RunBudget(1, 4, 5, 6, 2, 12_000, 3_000, 120),
    RunMode.RESEARCH: RunBudget(3, 10, 12, 20, 3, 40_000, 8_000, 300),
}


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    billing_class: Literal["local", "public_free", "gemini_paid"]
    allowed_operations: set[str]
    shared_quota_key: str
    concurrency: int
    requests_per_minute: int | None
    tokens_per_minute: int | None
    max_daily_spend_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_usd_per_1k: float
    output_usd_per_1k: float


MODEL_PRICES = {
    "gemini-3.8-flash": ModelPrice(0.0001, 0.0002),
    "gemini-3.8-pro": ModelPrice(0.0002, 0.0004),
}


def calculate_provider_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = MODEL_PRICES.get(model, ModelPrice(0.0005, 0.0015))
    return (input_tokens / 1000.0) * price.input_usd_per_1k + (output_tokens / 1000.0) * price.output_usd_per_1k
