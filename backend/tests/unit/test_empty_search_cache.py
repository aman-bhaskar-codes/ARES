from datetime import UTC, datetime
from types import SimpleNamespace

from ares.application.research_cache import RunResearchCache


def test_empty_search_cache_is_retried_after_engine_recovery():
    now = datetime.now(UTC)
    repository = SimpleNamespace(
        get_research_cache=lambda *args, **kwargs: {
            "payload": {"hits": []},
            "created_at": now,
            "expires_at": now,
            "retrieved_at": now,
        }
    )
    context = SimpleNamespace(lease=SimpleNamespace(run_id="run", token="token"))
    assert (
        RunResearchCache(repository).get(
            context, namespace="web.search", key_payload={"query": "qubit"}
        )
        is None
    )
