# ARES V2 release architecture

ARES V2 is an additive continuation of the M06 application through M11. The release keeps React/Vite, FastAPI, PostgreSQL/pgvector, the durable research/media workers, SearXNG/provider adapters and the existing evidence contracts.

```text
Browser
  │
  ├── React/Vite workspace
  │     ├── answer / sources / comparison / activity
  │     ├── PDF/media evidence navigation
  │     └── lazy chart + bounded evidence graph renderers
  │
  ▼
FastAPI API ─────── authorized original/rendition bytes
  │
  ├── run + ingestion admission
  ├── snapshots/SSE
  ├── evidence/quality/exports
  └── read-only visualization API + server CSV export
  │
  ▼
PostgreSQL + pgvector
  ├── workspace / identity / RLS
  ├── runs / jobs / checkpoints / durable events
  ├── sources / evidence / claims / facets / relations
  ├── assets / extractions / segments / media metadata
  └── visualization datasets/specs/lineage (0012)
  │
  ├───────────────┬───────────────────┐
  ▼               ▼                   ▼
Research worker   Media worker        Browser sidecar (optional)
  │               │                   │
  │               ├─ Docling/OCR      └─ constrained public read rendering
  │               ├─ FFmpeg/ASR
  │               └─ local embeddings
  │
  └─ discovery → retrieval → checking → synthesis → visual artifact derivation
```

## Release invariants

1. A rendered externally checkable claim resolves to persisted authorized evidence, or is labeled analysis/hypothesis.
2. A visualization datapoint resolves through the same run evidence used by the answer.
3. No raw model output is executed as JavaScript, HTML, SQL, Python, chart expressions or browser actions.
4. Parsing, OCR, ASR and frame extraction stay outside API request handlers.
5. Optional modality/browser/visualization failure degrades locally; text research remains available.
6. User deletion removes retrieval visibility immediately and derivative cleanup follows the documented retention policy.
7. Readiness means the required backing schema/runtime exists; a feature flag alone is not readiness.

## M06 → M11 migration sequence

| Revision | Milestone | Purpose |
|---|---|---|
| 0007 | M07 | execution deadlines, checkpoints, assessments, resource leases |
| 0008 | M08 | durable assets, extraction versions, ingestion jobs, evidence segments |
| 0009 | M08 | retrieval profiles, lexical/indexing state |
| 0010 | M09 | media tracks/frames/time-based evidence metadata |
| 0011 | M10 | facets, evidence-edge semantics, origin grouping, bounded cache |
| 0012 | M11 | validated visualization datasets/specs/lineage/export metadata |

Destructive cleanup is deliberately outside V2. Upgrade uses expand/backfill/switch/contract discipline and keeps old saved runs readable.
