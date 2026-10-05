from __future__ import annotations

import httpx

from ares.adapters.arxiv import ArxivAcademicProvider


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/2609.01234v2</id>
    <updated>2026-09-12T00:00:00Z</updated>
    <published>2026-09-10T00:00:00Z</published>
    <title>Evidence-first research systems</title>
    <summary>We study traceable evidence pipelines.</summary>
    <author><name>Ada Researcher</name></author>
    <arxiv:primary_category term="cs.AI"/>
    <link href="https://arxiv.org/pdf/2609.01234v2" type="application/pdf"/>
  </entry>
</feed>"""


def test_arxiv_preserves_preprint_version_and_abstract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/query"
        return httpx.Response(200, request=request, text=ATOM)

    client = httpx.Client(base_url="https://export.arxiv.org", transport=httpx.MockTransport(handler))
    provider = ArxivAcademicProvider(client=client, min_interval_seconds=0)
    results = provider.search_documents("evidence research", limit=2)
    assert len(results) == 1
    hit, document = results[0]
    assert hit.canonical_identifier == "arxiv:2609.01234v2"
    assert document.canonical_identifier == "arxiv:2609.01234v2"
    assert document.source_kind == "academic"
    assert "Permitted PDF URL" in document.text
    assert "traceable evidence pipelines" in document.text
    assert str(hit.full_text_url) == "https://arxiv.org/pdf/2609.01234v2"
    assert hit.full_text_mime_type == "application/pdf"


def test_arxiv_applies_run_timeout_to_http_request() -> None:
    observed: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(float(request.extensions["timeout"]["read"]))
        return httpx.Response(200, request=request, text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    client = httpx.Client(base_url="https://export.arxiv.org", transport=httpx.MockTransport(handler))
    provider = ArxivAcademicProvider(client=client, min_interval_seconds=0)
    provider.search_documents("topic", timeout_seconds=2.5)
    assert observed == [2.5]


def test_arxiv_filters_known_publication_date_but_keeps_contract_local() -> None:
    from datetime import UTC, datetime

    client = httpx.Client(
        base_url="https://export.arxiv.org",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request, text=ATOM)),
    )
    provider = ArxivAcademicProvider(client=client, min_interval_seconds=0)
    assert provider.search_documents("topic", published_after=datetime(2026, 9, 11, tzinfo=UTC)) == []
