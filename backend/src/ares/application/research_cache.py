from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from ares.application.repository import Repository
from ares.application.run_context import RunContext

T = TypeVar("T")
CACHE_POLICY_VERSION = "m10-v1"


def stable_cache_key(namespace: str, payload: dict[str, object]) -> str:
    """Return a deterministic cache key without embedding tenant identity.

    Tenant isolation is enforced by Repository using the run workspace. Keeping workspace
    identity out of this digest lets the cache schema make that boundary explicit and avoids
    accidental cross-tenant cache reuse if a key is logged or inspected.
    """
    body = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    return hashlib.sha256(f"{namespace}\n{CACHE_POLICY_VERSION}\n{body}".encode()).hexdigest()


def dump_models(values: list[BaseModel]) -> list[dict[str, object]]:
    return [value.model_dump(mode="json") for value in values]


@dataclass(frozen=True, slots=True)
class CacheLookup:
    payload: dict[str, object]
    created_at: datetime
    expires_at: datetime
    retrieved_at: datetime | None

    @property
    def age_seconds(self) -> float:
        return max(0.0, (datetime.now(UTC) - self.created_at).total_seconds())


class RunResearchCache:
    """Run-authorized, workspace-scoped research cache facade.

    The repository owns isolation and expiry. This facade adds deterministic keys, durable
    cache events, and request coalescing using the existing fleet-visible resource leases.
    No database transaction is held while ``compute`` performs network work.
    """

    def __init__(self, repository: Repository, *, enabled: bool = True):
        self.repository = repository
        self.enabled = enabled

    def get(
        self,
        context: RunContext,
        *,
        namespace: str,
        key_payload: dict[str, object],
    ) -> CacheLookup | None:
        if not self.enabled:
            return None
        key = stable_cache_key(namespace, key_payload)
        row = self.repository.get_research_cache(
            context.lease.run_id,
            namespace=namespace,
            cache_key=key,
            policy_version=CACHE_POLICY_VERSION,
            lease_token=context.lease.token,
        )
        if row is None:
            return None
        return CacheLookup(
            payload=dict(row["payload"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            retrieved_at=row.get("retrieved_at"),
        )

    def put(
        self,
        context: RunContext,
        *,
        namespace: str,
        key_payload: dict[str, object],
        payload: dict[str, object],
        ttl_seconds: int,
        retrieved_at: datetime | None = None,
    ) -> None:
        if not self.enabled:
            return
        key = stable_cache_key(namespace, key_payload)
        self.repository.put_research_cache(
            context.lease.run_id,
            namespace=namespace,
            cache_key=key,
            policy_version=CACHE_POLICY_VERSION,
            payload=payload,
            ttl_seconds=ttl_seconds,
            retrieved_at=retrieved_at,
            lease_token=context.lease.token,
        )

    def get_or_compute(
        self,
        context: RunContext,
        *,
        namespace: str,
        key_payload: dict[str, object],
        ttl_seconds: int,
        compute: Callable[[], tuple[dict[str, object], datetime | None]],
        acquire_slot: Callable[[str], Any],
    ) -> tuple[dict[str, object], bool, datetime | None]:
        hit = self.get(context, namespace=namespace, key_payload=key_payload)
        if hit is not None:
            return hit.payload, True, hit.retrieved_at
        if not self.enabled:
            payload, retrieved_at = compute()
            return payload, False, retrieved_at

        key = stable_cache_key(namespace, key_payload)
        # Fleet-visible single-flight. Recheck after acquiring because another worker may have
        # populated the cache while this worker waited. ``acquire_slot`` must release on exit.
        with acquire_slot(f"cachefill:{namespace}:{key[:24]}"):
            hit = self.get(context, namespace=namespace, key_payload=key_payload)
            if hit is not None:
                return hit.payload, True, hit.retrieved_at
            payload, retrieved_at = compute()
            self.put(
                context,
                namespace=namespace,
                key_payload=key_payload,
                payload=payload,
                ttl_seconds=ttl_seconds,
                retrieved_at=retrieved_at,
            )
            return payload, False, retrieved_at
