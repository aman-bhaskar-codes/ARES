# Milestone 3 — Research intelligence and multi-source RAG

## Implemented
- Jev adapter using the documented `/v1/systemone` typed decision API.
- Jev-backed route, coverage and claim-support decisions with deterministic fail-closed fallback.
- Bounded Research-mode recovery wave driven by missing coverage facets.
- OpenAlex academic metadata/abstract retrieval with explicit abstract-only provenance.
- Read-only GitHub repository/release/license/README research adapter.
- Text/Markdown document ingestion and document-scoped RAG.
- Optional Gemini Embedding 2 semantic retrieval behind an explicit feature flag.
- Reciprocal Rank Fusion for lexical + semantic retrieval, followed by source-diversity selection.
- Persisted claim support states: supported, partially supported, conflicting, insufficient evidence.
- Frozen routing evaluation harness with optional live Jev evaluation.

## Explicit boundaries
- PDF/OCR parsing is not yet enabled; text and Markdown are the document ingestion formats in this milestone.
- OpenAlex abstract/metadata evidence is never presented as full-paper reading.
- Jev is a metered service and is disabled unless explicitly configured.
- Gemini embeddings are optional; the cited-search path remains operational with lexical retrieval alone.
- GitHub adapter reads public metadata and README content only; ARES never executes repository code.

## Manual live checks
1. Run migrations to `0004 (head)`.
2. Configure `JEV_ENABLED=true` and `JEV_API_KEY` only if you intend to consume TypeSafe credits.
3. Run `PYTHONPATH=backend/src python evals/run_decisions.py --provider jev` to measure routing on frozen cases.
4. Test web + academic query with `source_scope=["web","academic"]`.
5. Test software query with `source_scope=["software","web"]`.
6. POST `/api/v1/documents/text`, then create a run with `source_scope=["documents"]` and that returned `document_id`.
7. If semantic retrieval is desired, set `GEMINI_EMBEDDINGS_ENABLED=true` and verify quota/cost policy before testing.

## Next milestone recommendation
Milestone 4 should focus on polished product completion and deep document intelligence: PDF parsing/page maps, pgvector persisted embeddings, Crossref/arXiv enrichment, exports, UI source-scope controls/document upload, and end-to-end evaluation reports.
