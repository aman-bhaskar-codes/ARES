from __future__ import annotations

import httpx

from ares.adapters.crossref import CrossrefAcademicProvider


def test_crossref_normalizes_doi_and_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mailto"] == "researcher@example.com"
        return httpx.Response(
            200,
            request=request,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/ABC",
                            "title": ["Evidence systems"],
                            "author": [{"given": "Ada", "family": "Lovelace"}],
                            "container-title": ["Research Systems"],
                            "published": {"date-parts": [[2026, 9, 1]]},
                            "abstract": "<jats:p>Direct evidence matters.</jats:p>",
                            "type": "journal-article",
                            "subject": ["Computer Science"],
                        }
                    ]
                }
            },
        )

    client = httpx.Client(
        base_url="https://api.crossref.org", transport=httpx.MockTransport(handler)
    )
    provider = CrossrefAcademicProvider(mailto="researcher@example.com", client=client)
    results = provider.search_documents("evidence systems", limit=3)
    assert len(results) == 1
    hit, document = results[0]
    assert hit.canonical_identifier == "doi:10.1000/abc"
    assert document.canonical_identifier == "doi:10.1000/abc"
    assert document.source_kind == "academic"
    assert "Direct evidence matters." in document.text
    assert document.published_at is not None


def test_crossref_applies_run_timeout_to_http_request() -> None:
    observed: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(float(request.extensions["timeout"]["read"]))
        return httpx.Response(200, request=request, json={"message": {"items": []}})

    client = httpx.Client(
        base_url="https://api.crossref.org", transport=httpx.MockTransport(handler)
    )
    provider = CrossrefAcademicProvider(client=client)
    provider.search_documents("topic", limit=10, timeout_seconds=2.25)
    assert observed == [2.25]


def test_crossref_pushes_explicit_publication_window_to_provider() -> None:
    from datetime import UTC, datetime

    observed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.params.get("filter", ""))
        return httpx.Response(200, request=request, json={"message": {"items": []}})

    provider = CrossrefAcademicProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.crossref.org"
        )
    )
    provider.search_documents(
        "topic",
        limit=10,
        published_after=datetime(2024, 1, 1, tzinfo=UTC),
        published_before=datetime(2024, 12, 31, tzinfo=UTC),
    )
    assert observed == ["from-pub-date:2024-01-01,until-pub-date:2024-12-31"]
