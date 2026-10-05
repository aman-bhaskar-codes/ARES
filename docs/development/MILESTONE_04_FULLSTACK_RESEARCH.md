# Milestone 04 — Full-stack research workspace and page-aware RAG

## Scope completed in source

M4 connects the research intelligence built in M2/M3 to a complete researcher-facing workflow. It adds bounded PDF ingestion and page maps, persisted chunks/embeddings, exact pgvector retrieval, Crossref and arXiv scholarly adapters, deterministic exports, richer provenance, production lifecycle handling, and the React controls needed to use these capabilities.

### Runtime invariants

1. Reusable document identity is separate from run-scoped source identity.
2. Citation evidence points to an immutable document/source version and exact normalized span; PDF evidence also carries page range.
3. Retrieved source text and uploaded document text remain untrusted data.
4. Embeddings are indexed by model ID and dimensions and are never mixed across identities.
5. Vector retrieval is optional; lexical retrieval remains available if embedding quota/provider fails.
6. Strict-free live mode never enables a metered Jev path or paid fallback implicitly.
7. No approximate vector index is enabled without a measured retrieval/latency justification.

## Combined M2–M4 manual gate

Run these after unpacking the M4 release package.

### 1. Reinstall from lockfiles

```bash
uv sync --project backend --extra dev
corepack enable pnpm
pnpm install --frozen-lockfile
```

The M4 backend lock includes `pypdf==6.19.0` and `python-multipart==0.0.32`; `uv lock --project backend --check --offline` passes in the build workspace.

### 2. Start infrastructure

```bash
make infra
```

Expected local services:

- PostgreSQL 18 with pgvector extension support
- SearXNG bound to loopback

### 3. Migrate

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini current
```

Required revision:

```text
0005 (head)
```

### 4. Run backend + PostgreSQL gates

```bash
PYTHONPATH=backend/src uv run --project backend pytest backend/tests -q
export ARES_TEST_POSTGRES_URL="$DATABASE_URL"
PYTHONPATH=backend/src uv run --project backend pytest \
  backend/tests/integration/test_postgres_concurrency.py \
  backend/tests/integration/test_postgres_pgvector.py -q
```

The pgvector test must confirm both the installed `vector` extension and exact cosine ranking. The quota test must admit exactly one of two simultaneous RPM=1 reservations.

### 5. Run frontend gates

```bash
pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

### 6. Start the three application processes

API:

```bash
PYTHONPATH=backend/src uv run --project backend \
  uvicorn ares.api.app:app --reload
```

Worker:

```bash
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

Web:

```bash
pnpm --filter @ares/web dev
```

### 7. Document acceptance

Upload:

- one text PDF with at least three pages;
- one Markdown/text document;
- optionally one scanned PDF.

Verify:

- ready PDF reports page count;
- evidence from the PDF opens with the correct page/page range;
- the same uploaded document can be used in two different runs without source-ID collision;
- a scanned PDF is labelled `needs_ocr`, not treated as successfully read;
- deleting a document removes its derived chunks/embeddings while preserving unrelated records.

### 8. Retrieval acceptance

With Gemini embeddings enabled and explicit embedding quotas configured, ask a document-specific question twice. The first run may create missing chunk embeddings; the second should reuse persisted embeddings. Inspect PostgreSQL to confirm the exact vector sidecar contains the selected model/dimension identity.

Then disable embeddings and repeat. ARES must still answer through lexical retrieval or disclose insufficient evidence; it must not fail solely because semantic retrieval is disabled.

### 9. Multi-source research acceptance

Run one Research-mode query with:

```text
web + academic + software
```

Verify evidence metadata distinguishes broad web, scholarly metadata/abstract evidence, and GitHub software evidence. Academic metadata must not be presented as a full-text paper read.

### 10. Export acceptance

After a completed/partial run, create both Markdown and JSON exports from the UI. Re-download the artifacts and confirm their evidence IDs, source URLs, content hashes and support states match the finalized run.

### 11. Failure acceptance

- stop SearXNG and confirm web discovery reports unavailability rather than fabricating citations;
- exhaust configured Gemini quota and confirm no paid fallback;
- press Stop while retrieval is active and confirm no new tool work is admitted afterward;
- terminate the worker and confirm it stops admission, completes/drains the accepted job within its process behavior, closes adapters and disposes its DB engine.

## M4 known boundaries

- OCR execution is not implemented; only reliable detection/state is present.
- Browser rendering fallback remains deferred.
- Crossref/arXiv adapters operate over public metadata/abstract surfaces and do not bypass publisher access controls.
- pgvector uses exact search; approximate indexes are deferred until evaluation demonstrates a need.
- Multi-user identity/RLS and public deployment remain later milestones.
