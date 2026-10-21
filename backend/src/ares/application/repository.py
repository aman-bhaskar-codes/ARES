# ruff: noqa: F401
from __future__ import annotations

import hashlib
import json

from ares.adapters.persistence.artifacts import SqlArtifactRepository
from ares.adapters.persistence.ingestion import SqlIngestionRepository
from ares.adapters.persistence.jobs import SqlJobRepository
from ares.adapters.persistence.memory import SqlMemoryRepository
from ares.adapters.persistence.retrieval import SqlRetrievalRepository
from ares.adapters.persistence.views import SqlViewRepository
from ares.domain.models import (
    RunCreate,
)
from ares.ports.repositories import (
    IdempotencyConflictError as IdempotencyConflictError,
)  # noqa: F401
from ares.ports.repositories import (
    IngestionLease as IngestionLease,
)
from ares.ports.repositories import (
    IngestionPublication as IngestionPublication,
)
from ares.ports.repositories import (
    JobLease as JobLease,
)
from ares.ports.repositories import (
    NotFoundError as NotFoundError,
)
from ares.ports.repositories import (
    QuotaExceededError as QuotaExceededError,
)
from ares.ports.repositories import (
    ResourceCapacityError as ResourceCapacityError,
)
from ares.ports.repositories import (
    ResourceLease as ResourceLease,
)
from ares.ports.repositories import (
    RunAdmissionError as RunAdmissionError,
)
from ares.ports.repositories import (
    RunAuthorizationError as RunAuthorizationError,
)
from ares.ports.repositories import (
    RunBudgetExceededError as RunBudgetExceededError,
)
from ares.ports.repositories import (
    StaleLeaseError as StaleLeaseError,
)


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class Repository(
    SqlViewRepository,
    SqlArtifactRepository,
    SqlRetrievalRepository,
    SqlIngestionRepository,
    SqlJobRepository,
    SqlMemoryRepository,
):
    pass
