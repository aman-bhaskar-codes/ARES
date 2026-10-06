from ares.application.engine import _prioritize_exact_identifiers, _query_identifiers
from ares.domain.models import FetchedDocument, SearchHit


def _row(identifier: str, rank: int):
    hit = SearchHit(
        title=identifier,
        url="https://example.com/source",
        rank=rank,
        provider="test",
        source_kind="academic",
        canonical_identifier=identifier,
    )
    doc = FetchedDocument(
        title=identifier,
        url="https://example.com/source",
        final_url="https://example.com/source",
        text="Evidence text " * 20,
        content_hash=f"hash-{rank}",
        extraction_method="test",
        source_kind="academic",
        canonical_identifier=identifier,
    )
    return hit, doc


def test_extracts_supported_exact_identifiers():
    identifiers = _query_identifiers(
        "Compare DOI 10.1000/ABC.12 and arXiv:2401.01234v2 with github.com/pgvector/pgvector"
    )
    assert "doi:10.1000/abc.12" in identifiers
    assert "arxiv:2401.01234v2" in identifiers
    assert "github:pgvector/pgvector" in identifiers


def test_exact_identifier_outranks_fuzzy_provider_rank():
    rows = [_row("doi:10.2000/not-it", 1), _row("doi:10.1000/target", 9)]
    ranked = _prioritize_exact_identifiers("Read 10.1000/target", rows)
    assert ranked[0][1].canonical_identifier == "doi:10.1000/target"
