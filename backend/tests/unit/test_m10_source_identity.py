from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from ares.application.source_identity import (
    normalize_canonical_identifier,
    source_origin_group,
    source_origin_identity,
)
from ares.domain.models import FetchedDocument


def _doc(text: str, *, canonical: str | None = None) -> FetchedDocument:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return FetchedDocument(
        title="Fixture",
        url="https://example.org/a",
        final_url="https://example.org/a",
        text=text,
        content_hash=digest,
        fetched_at=datetime.now(UTC),
        extraction_method="fixture",
        byte_count=len(text.encode()),
        canonical_identifier=canonical,
    )


def test_origin_normalizes_doi_and_arxiv_versions() -> None:
    assert normalize_canonical_identifier("https://doi.org/10.1000/ABC") == "doi:10.1000/abc"
    assert normalize_canonical_identifier("arxiv:2401.12345v3") == "arxiv:2401.12345"
    assert source_origin_group(_doc("x" * 200, canonical="arxiv:2401.12345v1")) == source_origin_group(
        _doc("y" * 200, canonical="arxiv:2401.12345v4")
    )


def test_near_copy_signature_groups_lightly_wrapped_article() -> None:
    body = " ".join(
        f"research evidence token {index} describes reproducible measurements and limitations"
        for index in range(160)
    )
    wrapped = "navigation menu account preferences " + body + " copyright footer links"
    first = _doc(body)
    second = _doc(wrapped)
    assert source_origin_identity(first).startswith("copy:")
    assert source_origin_group(first) == source_origin_group(second)


def test_unrelated_long_text_does_not_share_origin() -> None:
    first = _doc(" ".join(f"alpha transport network measurement {i}" for i in range(180)))
    second = _doc(" ".join(f"biology genome protein sequence {i}" for i in range(180)))
    assert source_origin_group(first) != source_origin_group(second)
