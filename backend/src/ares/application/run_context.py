from __future__ import annotations
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from threading import Lock
from ares.application.repository import JobLease, Repository
from ares.domain.budgets import RunBudget
from ares.domain.models import DateWindow, RunSnapshot


class RunDeadlineExceeded(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class RunContext:
    repository: Repository
    lease: JobLease
    run: RunSnapshot
    budget: RunBudget
    started_monotonic: float = field(default_factory=monotonic)
    _usage_lock: Lock = field(default_factory=Lock, repr=False)

    @classmethod
    def create(cls, repository: Repository, lease: JobLease, budget: RunBudget) -> "RunContext":
        run = repository.initialize_run_execution_contract(
            lease.run_id, wall_clock_seconds=budget.wall_clock_seconds, lease_token=lease.token
        )
        return cls(repository, lease, run, budget)

    @property
    def date_window(self) -> DateWindow | None:
        return self.run.date_window

    def remaining_seconds(self) -> float:
        local_remaining = max(
            0.0, float(self.budget.wall_clock_seconds) - (monotonic() - self.started_monotonic)
        )
        deadline = self.run.deadline_at
        if deadline is None:
            return local_remaining
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        persisted_remaining = max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        # The persisted UTC deadline survives worker restarts; the monotonic budget
        # prevents wall-clock adjustments inside one worker from extending a run.
        return min(local_remaining, persisted_remaining)

    def check(self) -> None:
        if self.repository.is_cancel_requested(self.lease.run_id, lease_token=self.lease.token):
            raise RunCancelled("run cancellation requested")
        if self.remaining_seconds() <= 0:
            raise RunDeadlineExceeded("run wall-clock deadline exhausted")

    def clamp_timeout(self, requested: float) -> float:
        self.check()
        return max(0.05, min(float(requested), self.remaining_seconds()))

    def consume(self, **delta: int) -> dict[str, int]:
        # M10 discovery runs independent providers concurrently. Serialize the local snapshot
        # update while the repository remains the authoritative atomic ledger across workers.
        with self._usage_lock:
            self.check()
            limits = {
                "waves": self.budget.max_waves,
                "llm_calls": self.budget.max_llm_calls,
                "search_requests": self.budget.max_search_requests,
                "documents": self.budget.max_documents,
                "model_input_tokens": self.budget.model_input_tokens,
                "model_output_tokens": self.budget.model_output_tokens,
            }
            ledger = self.repository.consume_run_usage(
                self.lease.run_id, delta=delta, limits=limits, lease_token=self.lease.token
            )
            self.run = self.run.model_copy(update={"usage_ledger": ledger})
            return ledger
