# ADR 005 — Ranked web evidence and versioned provenance

- Status: accepted for Milestone 02
- Date: 2026-10-03

## Context

The Milestone 01 live skeleton synthesized from whole fetched pages and persisted only one opening passage per source. That is not a defensible RAG or citation architecture: relevant evidence may occur deep in a page, verbose pages can dominate context, and a source URL alone does not preserve the exact version cited.

## Decision

ARES Milestone 02 uses a deterministic retrieval pipeline before synthesis:

1. bounded query planning and SearXNG discovery;
2. URL canonicalization and safe fetching;
3. paragraph/sentence-aware chunking with exact normalized character offsets;
4. lexical relevance scoring with optional semantic-fusion port;
5. diversity selection with a per-source passage ceiling;
6. immutable `document_versions` storing fetched text/hash/method/MIME/bytes;
7. evidence rows linked to the document version and exact offsets;
8. Gemini sees only the selected evidence packets and can cite only server-issued evidence IDs.

Semantic embeddings are deliberately optional in Milestone 02. Basic web research must remain usable without spending a second provider quota. Milestone 03 can enable a local or explicitly budgeted embedding adapter without changing the evidence contract.

## Consequences

- citation identity is independent of later page changes;
- synthesis context is smaller and more relevant;
- retrieval can be evaluated separately from generation;
- future document, academic and software adapters reuse the same `EvidencePacket` boundary;
- lexical-only retrieval can miss paraphrases, so semantic fusion is a measured Milestone 03 enhancement rather than an implicit dependency.
