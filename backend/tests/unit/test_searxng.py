from __future__ import annotations

from ares.adapters.searxng import SearXNGSearchProvider
from ares.domain.research import SearchRequest


def test_searxng_adapter_maps_json_contract() -> None:
    captured = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Official docs",
                        "url": "https://example.com/docs",
                        "content": "Primary documentation",
                        "engine": "duckduckgo",
                        "publishedDate": "2026-10-01T00:00:00Z",
                    }
                ]
            }

    class Client:
        def get(self, url, *, params):
            captured.update({"url": url, "params": params})
            return Response()

        def close(self):
            return None

    hits = SearXNGSearchProvider("http://127.0.0.1:8080", client=Client()).search(
        SearchRequest(query="ARES", limit=5, time_range="month")
    )
    assert len(hits) == 1
    assert hits[0].title == "Official docs"
    assert hits[0].provider == "searxng"
    assert hits[0].source_kind == "web"
    assert captured["params"]["format"] == "json"
    assert captured["params"]["time_range"] == "month"


def test_empty_results_with_unresponsive_engines_are_an_outage():
    import httpx
    import pytest
    from ares.ports.errors import SearchProviderError
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'results': [], 'unresponsive_engines': [['brave', 'too many requests']]})))
    with pytest.raises(SearchProviderError):
        SearXNGSearchProvider('http://localhost:8080', client=client).search(SearchRequest(query='qubit', limit=5))
