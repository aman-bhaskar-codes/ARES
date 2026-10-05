# Milestone 08 Release Report — Documents, images, tables and local indexing

**Candidate:** ARES `0.8.0` / schema `0009`  
**Baseline:** supplied M07 final archive; M08 is an additive continuation, not a rewrite.  
**Date:** 4 October 2026

## Implemented scope

M08 introduces a durable asset envelope around the existing document/RAG model. V1 text/PDF routes keep their synchronous compatibility semantics; `/api/v2/assets` creates a persisted asset plus ingestion job and returns `202`. Ingestion leasing, cancellation, retry, event sequencing and worker-time membership reauthorization reuse M07 fencing conventions.

The persisted lineage is `AssetVersion -> ExtractionVersion -> EvidenceSegment -> compatibility UserDocument/DocumentChunk`. Segments carry validated typed locators for text, normalized page regions and table cells. CSV ingestion preserves headers, spans, raw text and normalized scalar values. Existing research evidence may point to a segment and resolve back to the authenticated original asset.

Simple text PDFs keep the bounded pypdf path. Scans/images use an optional Docling/RapidOCR profile in a separate subprocess; no database/API credentials are copied into that process and production media workers have no egress network. Optional model caches must be provisioned before requests. Missing optional processing degrades/partials the ingestion rather than taking down text research.

Corpus embedding creation no longer occurs on the research query path. The ingestion worker can use local FastEmbed/ONNX, records semantic readiness, and preserves lexical usability if semantic indexing fails. PostgreSQL lexical retrieval uses bounded `websearch_to_tsquery('simple')` candidates with a GIN expression index; SQLite remains a deterministic test/demo fallback, not a performance reference.

## UI integration

The existing React workspace is extended rather than replaced: drag/drop admission, upload limits, durable stage/readiness cards, cancel/retry, and role-aware mutation controls are integrated into the document panel. Evidence inspection lazy-loads PDF.js, overlays normalized page regions, highlights table cells and exposes image evidence with a text alternative and authenticated original-source action. PDF.js is pinned to `6.3.289` in the frontend lock contract.

## Validation executed in this sandbox

- full backend suite: **122 passed / 6 skipped**; all skips require `ARES_TEST_POSTGRES_URL`;
- M08 focused integration suite: **6 passed** including async admission, byte ranges, MIME rejection, table/segment lineage, background embeddings, lexical-preserving semantic failure, cancel/retry and cross-workspace hiding;
- migration compatibility: **PASS** for empty -> `0009`, `0007` -> `0009`, and representative `0006` -> `0009`;
- Python compileall / AST import paths: **PASS**;
- deterministic secret-shaped-material scan: **PASS** across 223 candidate source paths;
- OpenAPI regenerated as ARES `0.8.0`; V2 asset/ingestion/segment/table endpoints are present and frontend generated contracts were refreshed;
- frontend source was statically reviewed, but a fresh `pnpm install --frozen-lockfile`, Vitest, TypeScript project build and Vite production build could not be run in this sandbox because the dependency tree is not installed and package-manager network installation is unavailable.

## Promotion gates still external

Do not label M08 production-complete until target CI runs PostgreSQL/pgvector/FORCE-RLS using the intended API/worker roles, fresh pnpm frozen install/typecheck/test/build, production media/core container builds, real Docling/RapidOCR/FastEmbed model provisioning, licensed OCR/table fixture evaluation, and live OIDC/provider smoke tests. The optional media dependency file pins direct packages but its transitive environment must be captured/verified by the target image/SBOM gate before release.

The M08 plan calls for at least 30 licensed document/image fixtures and independently annotated region/cell measurements. Those external-quality fixtures are not fabricated in this archive; OCR error, table-cell accuracy and locator alignment remain a release-evaluation gate rather than a claimed metric.

## Rollback

Disable `ASYNC_INGESTION_ENABLED`, `RICH_PARSER_ENABLED`, `OCR_ENABLED` and `LOCAL_EMBEDDINGS_ENABLED` independently. Preserve migrations `0008`/`0009` and completed immutable extraction data; old V1 document readers and pypdf/text ingestion continue to work. Do not destructively downgrade shared production data merely to disable the optional rich path.

## M09 entry condition

Begin audio/video work only after the external PostgreSQL/RLS, frozen frontend build, media-image/model provisioning and licensed OCR/table evaluation gates above pass. M09 should reuse M08 asset/extraction/segment/ingestion contracts instead of creating a separate media database or authorization path.
