from __future__ import annotations

import base64
import httpx

from ares.adapters.github_software import GitHubSoftwareProvider


def test_github_adapter_reads_metadata_release_and_bounded_readme():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(200, json={"items": [{
                "full_name": "org/repo", "html_url": "https://github.com/org/repo",
                "description": "A useful library", "license": {"spdx_id": "MIT"},
                "default_branch": "main", "topics": ["ai", "search"],
            }]})
        if request.url.path == "/repos/org/repo/releases/latest":
            return httpx.Response(200, json={"tag_name": "v1.2.3", "published_at": "2026-09-30T00:00:00Z"})
        if request.url.path == "/repos/org/repo/readme":
            return httpx.Response(200, json={"content": base64.b64encode(b"README text").decode()})
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    provider = GitHubSoftwareProvider(client=client)
    results = provider.search_documents("repo", limit=1)
    assert len(results) == 1
    hit, doc = results[0]
    assert hit.provider == "github"
    assert "Latest release tag: v1.2.3" in doc.text
    assert "README text" in doc.text
    assert doc.extraction_method == "github-rest-metadata-readme"


def test_github_adapter_applies_run_timeout_to_all_requests():
    observed: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(float(request.extensions["timeout"]["read"]))
        if request.url.path == "/search/repositories":
            return httpx.Response(200, request=request, json={"items": [{
                "full_name": "org/repo", "html_url": "https://github.com/org/repo",
                "description": "A useful library", "license": {"spdx_id": "MIT"},
                "default_branch": "main", "topics": [],
            }]})
        if request.url.path == "/repos/org/repo/releases/latest":
            return httpx.Response(404, request=request, json={})
        if request.url.path == "/repos/org/repo/readme":
            return httpx.Response(404, request=request, json={})
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    provider = GitHubSoftwareProvider(client=client)
    provider.search_documents("repo", limit=1, timeout_seconds=3.5)
    assert observed == [3.5, 3.5, 3.5]


def test_github_filters_known_release_date_against_run_window() -> None:
    from datetime import UTC, datetime

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(200, request=request, json={"items": [{
                "full_name": "org/repo", "html_url": "https://github.com/org/repo",
                "description": "A useful library", "license": {"spdx_id": "MIT"},
                "default_branch": "main", "topics": [],
            }]})
        if request.url.path == "/repos/org/repo/releases/latest":
            return httpx.Response(200, request=request, json={"tag_name": "v1", "published_at": "2026-09-30T00:00:00Z"})
        if request.url.path == "/repos/org/repo/readme":
            return httpx.Response(404, request=request, json={})
        raise AssertionError(request.url)

    provider = GitHubSoftwareProvider(client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"))
    assert provider.search_documents("repo", limit=1, published_before=datetime(2026, 9, 1, tzinfo=UTC)) == []
