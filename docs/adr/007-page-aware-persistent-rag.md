# ADR 007 — Page-aware persistent document RAG with exact vector search first

**Status:** accepted for Milestone 4  
**Date:** 2026-10-03

## Context

Milestone 3 could retrieve text/Markdown documents but did not preserve PDF page provenance or durable vector indexes. Reusing a document across runs also exposed an identity bug: the reusable document UUID had been used as a run-scoped source primary key, which could collide on later runs.

## Decision

ARES separates reusable `user_documents` from per-run `sources`. Every research run creates a run-scoped source identity that points back to the reusable document through a canonical `ares:document:<uuid>` identifier.

PDFs are parsed in a bounded subprocess. Parsed text retains a normalized page map, and evidence stores page ranges plus normalized character offsets. Image-only/scanned PDFs become `needs_ocr`; M4 does not pretend OCR occurred.

Document chunks are persisted once. Embeddings are versioned by chunk, model ID and dimension. PostgreSQL uses the `vector` extension and an exact cosine-search sidecar; SQLite retains JSON vectors for deterministic tests/demo. Retrieval fuses lexical and semantic ranks with reciprocal-rank fusion.

No HNSW or IVFFlat index is created in M4. Approximate search is a performance optimization that requires measured recall/latency evidence first.

## Consequences

- Saved reports can resolve citations to the same parsed document version and page range.
- Reusing one document across many runs no longer collides with run source identity.
- Re-embedding with a new model/dimension creates a separate index identity instead of mixing vectors.
- Semantic quota failure degrades to lexical retrieval rather than making document research unavailable.
- Scanned PDFs are visible as an unsupported/OCR-needed state until a later OCR adapter is explicitly built.
