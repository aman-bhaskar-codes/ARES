from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ares.domain.models import FetchedDocument, SearchHit


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_time_range: bool = False
    supports_full_text: bool = False
    supports_exact_id: bool = False


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    source_kind: Literal["web", "academic", "software", "document"]
    capabilities: ProviderCapabilities
    cost_class: Literal["free", "paid"]
    timeout_seconds: float
    rate_limit_rpm: int | None
    cache_ttl_seconds: int
    enabled: bool = True
    health_state: Literal["healthy", "degraded", "down"] = "healthy"


class DiscoveryProvider(Protocol):
    @property
    def metadata(self) -> ProviderMetadata: ...

    def search_documents(
        self,
        query: str,
        limit: int,
        *,
        timeout_seconds: float | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument | None]]: ...


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, DiscoveryProvider] = {}

    def register(self, provider: DiscoveryProvider) -> None:
        if not provider.metadata.enabled:
            return
        self._providers[provider.metadata.name] = provider

    def get_providers_by_kind(self, source_kind: str) -> list[DiscoveryProvider]:
        return [
            p
            for p in self._providers.values()
            if p.metadata.source_kind == source_kind and p.metadata.health_state != "down"
        ]

    def get_provider(self, name: str) -> DiscoveryProvider | None:
        return self._providers.get(name)

    def all_providers(self) -> list[DiscoveryProvider]:
        return list(self._providers.values())
