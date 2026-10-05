from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from ares.domain.models import FetchedDocument

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_ARXIV_VERSION = re.compile(r"^(arxiv:\d{4}\.\d{4,5})v\d+$", re.IGNORECASE)


def normalize_canonical_identifier(value: str) -> str:
    """Normalize stable scholarly/software identifiers without changing source versions.

    The stored canonical identifier remains untouched. This normalization is only for source
    *origin* grouping: arXiv revisions of one preprint are one origin, DOI spellings collapse to
    one origin, and GitHub repository case does not create fake independence.
    """
    identifier = value.strip().casefold()
    if identifier.startswith("https://doi.org/"):
        identifier = "doi:" + identifier.removeprefix("https://doi.org/")
    if identifier.startswith("http://doi.org/"):
        identifier = "doi:" + identifier.removeprefix("http://doi.org/")
    match = _ARXIV_VERSION.match(identifier)
    if match:
        identifier = match.group(1)
    return identifier


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(text)]


def _copy_signature(text: str) -> str | None:
    """Return a conservative near-copy signature for sufficiently long public text.

    Two independently salted MinHash minima over 5-token shingles make exact collisions between
    unrelated pages extremely unlikely, while still grouping many lightly wrapped/reformatted
    copies of the same article. This is intentionally used for independence accounting only; it
    is not used to delete sources or assert that two publications are legally/semantically the
    same work.
    """
    tokens = _tokens(text)
    if len(tokens) < 80:
        return None
    # Bound CPU and reduce footer/navigation influence. The research fetcher already caps stored
    # text, but origin grouping should have its own small deterministic bound.
    tokens = tokens[:2500]
    shingles = {" ".join(tokens[index:index + 5]) for index in range(0, len(tokens) - 4)}
    if len(shingles) < 40:
        return None
    minima: list[str] = []
    for salt in (b"ares-origin-a\0", b"ares-origin-b\0"):
        minimum = min(
            hashlib.blake2b(salt + shingle.encode("utf-8"), digest_size=8).digest()
            for shingle in shingles
        )
        minima.append(minimum.hex())
    return ":".join(minima)


def source_origin_identity(document: FetchedDocument) -> str:
    """Produce a deterministic identity used only to count independent source origins."""
    if document.canonical_identifier:
        return f"id:{normalize_canonical_identifier(document.canonical_identifier)}"
    signature = _copy_signature(document.text)
    if signature:
        return f"copy:{signature}"
    return f"sha256:{document.content_hash.casefold()}"


def source_origin_group(document: FetchedDocument) -> UUID:
    return uuid5(NAMESPACE_URL, f"ares:source-origin:{source_origin_identity(document)}")
