from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class NotFoundError(LookupError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class StaleLeaseError(RuntimeError):
    pass


class QuotaExceededError(RuntimeError):
    pass


class RunAdmissionError(RuntimeError):
    pass


class RunBudgetExceededError(RuntimeError):
    pass


class RunAuthorizationError(RuntimeError):
    pass


class ResourceCapacityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JobLease:
    run_id: UUID
    token: UUID
    leased_until: datetime
    attempt: int


@dataclass(frozen=True, slots=True)
class ResourceLease:
    run_id: UUID
    resource_key: str
    slot: int
    token: UUID
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class IngestionLease:
    ingestion_id: UUID
    asset_id: UUID
    token: UUID
    leased_until: datetime
    attempt: int


@dataclass(frozen=True, slots=True)
class IngestionPublication:
    document_id: UUID
    extraction_version_id: UUID
