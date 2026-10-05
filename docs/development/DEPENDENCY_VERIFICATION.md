# Dependency/provider verification snapshot — 2026-10-02

This file records the external checks used for the V1 foundation. A current version is not automatically a compatible version; the unresolved lockfile/clean-install gate remains explicit.

| Concern | Verified snapshot | Decision |
|---|---:|---|
| FastAPI | 0.142.2 | Pin direct dependency. |
| google-genai | 2.26.0 | Pin official SDK. The blueprint's 2.28.0 observation could not be reproduced from the public release source and is not used. |
| Gemini model API | Gemini 3.8 Flash supports structured output; current Interactions API documentation covers structured responses and cancellation/background interactions | Keep SDK behind `LLMProvider`; ARES still owns citations and quota policy. |
| Vite | 8.3.2 | Pin; Node 22.16 in this environment satisfies Vite 8's documented Node requirement. |
| React / React DOM | 19.3.0 | Pin. |
| TypeScript | 7.0.2 | Pin in frontend manifest; build awaits registry-enabled install. |
| SQLAlchemy | 2.1.2 | Pin; production store remains PostgreSQL. |
| Alembic | 1.20.0 | Pin; initial migration tested against SQLite here, real PostgreSQL remains an execution gate. |
| Pydantic | 2.13.5 | Pin. |
| pydantic-settings | 2.15.0 | Pin. |
| psycopg | 3.3.6 | Pin binary extra for local V1 developer setup. |
| Uvicorn | 0.54.0 | Pin standard extra. |
| Trafilatura | 2.2.0 | Pin. |
| pnpm | 12.8.1 | Pin package manager metadata; lockfile still required. |
| Vitest | 5.0.3 | Pin; frontend test execution awaits install. |
| openapi-typescript | 7.13.0 | Pin; `backend/openapi.json` is already generated, TS generation awaits install. |
| SearXNG | JSON `/search` contract documented when JSON format is enabled | Use a private/local instance; no dependency on public instances. |

Primary references checked:

- https://github.com/googleapis/python-genai/releases
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/interactions
- https://pypi.org/project/fastapi/
- https://www.npmjs.com/package/vite
- https://www.npmjs.com/package/react
- https://www.npmjs.com/package/typescript
- https://pypi.org/project/SQLAlchemy/
- https://pypi.org/project/alembic/
- https://pypi.org/project/pydantic/
- https://pypi.org/project/pydantic-settings/
- https://pypi.org/project/psycopg/
- https://pypi.org/project/uvicorn/
- https://pypi.org/project/trafilatura/
- https://www.npmjs.com/package/pnpm
- https://www.npmjs.com/package/vitest
- https://www.npmjs.com/package/openapi-typescript
- https://docs.searxng.org/dev/search_api.html

## Milestone 04 additions — 2026-10-03

| Concern | Verified snapshot | Decision |
|---|---|---|
| pgvector | Official project publishes PostgreSQL 18 container images; exact search is supported before HNSW/IVFFlat | Use pgvector-enabled PostgreSQL 18 locally/CI. Start with exact cosine search; add approximate index only after benchmark. |
| pypdf | 6.19.0 observed 2026-09-16 | Pin for text-layer PDF extraction; treat scanned PDFs as OCR-needed. |
| python-multipart | 0.0.32 observed 2026-06-04 | Pin because FastAPI multipart `UploadFile` requires multipart parsing support. |
| Crossref REST | Public REST API, no signup required; polite identification/caching recommended | Metadata/abstract adapter only; no inference of publisher full-text access. |
| arXiv API | Public scholarly metadata/preprint endpoint with conservative request pacing | Serialized/paced metadata + abstract adapter; preserve arXiv version ID. |

The M4 backend lock was updated from the verified PyPI release metadata (including wheel/sdist hashes) and `uv lock --project backend --check --offline` passes.
