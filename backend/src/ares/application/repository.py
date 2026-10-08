# ruff: noqa: F401
from __future__ import annotations

import hashlib
import json


from ares.domain.models import (
    RunCreate,
)

from ares.ports.repositories import (
    NotFoundError,
    IdempotencyConflictError,
    StaleLeaseError,
    QuotaExceededError,
    RunAdmissionError,
    RunBudgetExceededError,
    RunAuthorizationError,
    ResourceCapacityError,
    JobLease,
    ResourceLease,
    IngestionLease,
    IngestionPublication,
) # noqa: F401
from ares.adapters.persistence.views import SqlViewRepository
from ares.adapters.persistence.artifacts import SqlArtifactRepository
from ares.adapters.persistence.retrieval import SqlRetrievalRepository
from ares.adapters.persistence.ingestion import SqlIngestionRepository
from ares.adapters.persistence.jobs import SqlJobRepository


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class Repository(
    SqlViewRepository,
    SqlArtifactRepository,
    SqlRetrievalRepository,
    SqlIngestionRepository,
    SqlJobRepository,
):
    pass
