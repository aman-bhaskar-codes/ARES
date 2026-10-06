from __future__ import annotations

import httpx

from ares.adapters.openalex import OpenAlexAcademicProvider


def test_openalex_reconstructs_abstract_and_labels_metadata_only():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1/example",
                        "title": "A paper",
                        "publication_date": "2026-01-02",
                        "abstract_inverted_index": {"This": [0], "is": [1], "evidence": [2]},
                        "primary_location": {"landing_page_url": "https://example.org/paper"},
                        "best_oa_location": {
                            "pdf_url": "https://repository.example/paper.pdf",
                            "is_oa": True,
                        },
                        "type": "article",
                    }
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.openalex.org"
    )
    provider = OpenAlexAcademicProvider(client=client)
    results = provider.search_documents("topic", limit=3)
    assert len(results) == 1
    hit, document = results[0]
    assert hit.provider == "openalex"
    assert "This is evidence" in document.text
    assert document.extraction_method == "openalex-metadata-abstract"
    assert str(hit.full_text_url) == "https://repository.example/paper.pdf"
    assert hit.full_text_mime_type == "application/pdf"


def test_openalex_applies_run_timeout_to_http_request():
    observed: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(float(request.extensions["timeout"]["read"]))
        return httpx.Response(200, request=request, json={"results": []})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.openalex.org"
    )
    provider = OpenAlexAcademicProvider(client=client)
    provider.search_documents("topic", timeout_seconds=1.75)
    assert observed == [1.75]


def test_openalex_pushes_explicit_publication_window_to_provider() -> None:
    from datetime import UTC, datetime

    observed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.params.get("filter", ""))
        return httpx.Response(200, request=request, json={"results": []})

    provider = OpenAlexAcademicProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.openalex.org"
        )
    )
    provider.search_documents(
        "topic",
        published_after=datetime(2024, 1, 1, tzinfo=UTC),
        published_before=datetime(2024, 12, 31, tzinfo=UTC),
    )
    assert observed == ["from_publication_date:2024-01-01,to_publication_date:2024-12-31"]
