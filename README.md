<div align="center">

# ARES

**Autonomous Research & Evidence System**

A research workspace for exploring questions, working with documents, and tracing answers back to their sources.

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)](apps/web/package.json)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

<img src="ares_banner.jpg" alt="ARES — Autonomous Research & Evidence System" width="800" />

[Getting started](#getting-started) · [Model providers](#model-providers) · [Architecture](#architecture) · [Development](#development) · [Security](#security-and-release-status)

</div>

## Overview

ARES brings source discovery, document retrieval, and cited answer generation into one interface. A FastAPI control plane coordinates persistent research runs and background workers; the React workspace displays answers, source evidence, and execution activity.

Use the keyless demo to explore the interface, or configure live research with Google Gemini or a local Qwen model through Ollama.

> **Release status:** ARES is an actively developed research application. Start with the local demo or a configured live provider. The release hardening pass disables generated-code execution and strengthens packaging and database provisioning. Local checks do not certify a public deployment; see [Security and release status](#security-and-release-status).

## What you can do

- **Research a question:** discover web and academic sources through SearXNG, OpenAlex, Crossref, and arXiv adapters.
- **Work with documents:** upload files, extract supported content, and retrieve passages for research. Scanned PDFs and richer media require optional parsing capabilities.
- **Choose a writer:** switch between Gemini and local Qwen in the model menu. Ask for a brief answer or a detailed explanation; ARES adapts its writing instructions while retaining source citations. Smaller local models may produce shorter answers after evidence checks.
- **Inspect the evidence:** follow citations, review source passages, and inspect research activity and visualizations.
- **Resume research:** persist conversations, run events, assets, and research memory.
- **Connect other agents:** use the project's Model Context Protocol integration to access research capabilities.

Capabilities depend on the execution mode, enabled settings, provisioned models, and external service availability. Demo results use fixtures rather than live research.

## Getting started

### Requirements

- Python **3.12 or newer**, within the range declared in [backend/pyproject.toml](backend/pyproject.toml).
- [uv](https://docs.astral.sh/uv/) for backend dependencies.
- Node.js **20.19 or newer**, compatible with the locked frontend toolchain.
- pnpm **9.12.3**, declared in [package.json](package.json); use Corepack where available.
- Docker Compose for local PostgreSQL and SearXNG when needed. The SQLite demo does not require Docker.

### 1. Install dependencies

```bash
git clone https://github.com/aman-bhaskar-codes/ARES.git
cd ARES
cp .env.example .env

uv sync --project backend --extra dev --frozen
corepack enable
pnpm install --frozen-lockfile
```

### 2. Initialize the demo database

The supplied `.env.example` selects `ARES_MODE=demo` and a local SQLite database. Keep these defaults for the first run. No cloud credentials are required.

```bash
make migrate
```

### 3. Start the application

Run each command in a separate terminal from the repository root. `make worker` defaults to the combined profile so uploaded files and research runs are both processed:

```bash
# Terminal 1 — API
make api
```

```bash
# Terminal 2 — research and document-ingestion worker
make worker
```

```bash
# Terminal 3 — frontend
make web
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) while the backend is running. Use the URL printed by Vite if the default frontend port is occupied.

## Model providers

Live research uses `ARES_MODE=local_live`. Restart the API and worker after changing `.env`.

### Qwen through Ollama

Install [Ollama](https://ollama.com/), start its service, and download the model:

```bash
ollama pull qwen3:4b
```

Set these values in `.env`:

```dotenv
ARES_MODE=local_live
LOCAL_LLM_ENABLED=true
LOCAL_LLM_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=qwen3:4b
```

Local inference keeps model generation on your machine. **Live web and academic discovery still contact external services**; enabling cloud providers or cloud processing can send data to those providers.

### Google Gemini

Create a key in [Google AI Studio](https://aistudio.google.com/) and set `ARES_MODE=local_live` and `GEMINI_API_KEY` in `.env`. Set `GEMINI_MODEL` to a model available to your account; the template includes the project's configured model name.

Also set **all three** quota controls to values appropriate for your account:

| Setting | Meaning |
| --- | --- |
| `GEMINI_RPM` | Requests per minute |
| `GEMINI_TPM` | Tokens per minute |
| `GEMINI_RPD` | Requests per day |

Do not copy another account's quota assumptions. Strict-free mode requires explicit quotas; it does not determine your provider's pricing or guarantee that usage is free. Keep credentials out of commits and shared screenshots.

### Search and PostgreSQL

Start the local infrastructure when using live web search or PostgreSQL:

```bash
make infra
```

This starts PostgreSQL and SearXNG, **not** the API, worker, or frontend. To use the supplied PostgreSQL container, change `.env` before applying migrations:

```dotenv
DATABASE_URL=postgresql+psycopg://ares:ares@127.0.0.1:5432/ares
SEARXNG_URL=http://127.0.0.1:8080
```

```bash
make migrate
```

These credentials are for local development only. Changing the database URL selects a different database; it does not transfer existing SQLite conversations or files.

## Architecture

```mermaid
flowchart LR
    UI[React workspace] -->|REST and SSE| API[FastAPI control plane]
    API --> DB[(Run and document storage)]
    DB <--> Worker[Background research worker]
    Worker --> Discovery[Web and academic discovery]
    Discovery --> Retrieval[Extraction and retrieval]
    Retrieval --> Writer[Gemini or Ollama]
    Writer --> Evidence[Claim checks and cited answer]
    Evidence --> DB
    Worker <--> Blobs[Asset storage]
```

Research runs move through discovery, extraction, retrieval, synthesis, and claim checking. Events are persisted for replay and streamed to the interface. PostgreSQL supports vector retrieval when the required embedding capabilities are configured; local lexical and demo paths provide simpler alternatives.

Claim checks are evidence-assessment signals, **not guarantees of truth**. Semantic checking is optional and disabled in the example configuration. Citations and retrieved excerpts should be inspected, particularly when a run reports insufficient evidence or falls back after a provider failure.

For implementation details, see [Architecture](docs/ARCHITECTURE.md), [Evaluation methodology](docs/evaluation/METHODOLOGY.md), and [Recorded hardening results](docs/evaluation/HARDENING_RESULTS.md).

## Configuration

[.env.example](.env.example) is the starting point for local configuration. [Backend settings](backend/src/ares/api/settings.py) define validation rules and defaults; values in your `.env` override those defaults.

| Setting | Purpose |
| --- | --- |
| `ARES_MODE` | `demo` for fixtures; `local_live` for live providers |
| `DEPLOYMENT_ENVIRONMENT` | Deployment context: `local` or `production` |
| `AUTH_MODE` | Local disabled-auth mode or configured OIDC authentication |
| `DATABASE_URL` / `BLOB_ROOT` | Database connection and asset storage location |
| `LOCAL_LLM_ENABLED` / `LOCAL_LLM_MODEL` | Local Ollama writer configuration |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Cloud writer credentials and model |
| `STRICT_FREE_MODE` | Provider admission and budget restrictions |
| `SEMANTIC_CHECKER_ENABLED` | Optional model-assisted claim assessment |
| `MAX_UPLOAD_BYTES` / `MAX_PDF_PAGES` | Upload and PDF processing limits |

OCR, rich parsing, embeddings, audio, and video have additional dependencies and provisioning requirements. Enable them only after reviewing the corresponding settings and worker requirements.

## Development

Run focused checks from the repository root:

```bash
make lint
make typecheck
make test
make security-scan

pnpm --filter @ares/web typecheck
pnpm --filter @ares/web test
pnpm --filter @ares/web build
```

`make check` aggregates additional checks, migrations, schema generation, and release verification. Some targets generate or update files. Skipped browser checks are explicitly reported as preflight only. A successful aggregate command alone is not production qualification. Run `make verify-m11-release` with a running app and the required `ARES_E2E_*` fixture identifiers for the existing three-browser gate.

The 27 October 2026 hardening pass recorded **299 passing backend tests, 8 skipped backend tests, and 28 passing frontend tests**, plus static checks and a successful frontend build. The seven PostgreSQL-specific tests were also run separately and passed. Real document-grounded queries completed with both Gemini and Qwen, and browser checks covered answer rendering, PDF upload, and direct chat deletion. These are a dated local baseline, not a live CI badge or public-hosting certification. Deterministic offline evaluations do not establish general real-provider answer quality.

## Security and release status

ARES includes controls for authentication, request limits, outbound fetching, upload processing, and database tenant isolation. Their effectiveness depends on deployment configuration and enabled capabilities.

The release hardening changes include:

- **Code execution disabled:** generated Python is never executed on the worker. The Code tool is removed from run admission and the composer until an isolated runner exists.
- **Tracked-file packaging:** source archives use Git's tracked-file inventory and exclude private environment files, keys, backups, runtime data, and symlinks.
- **Database provisioning:** the bootstrap normalizes the SQLAlchemy URL for `psql` and grants runtime roles access to the newer schema tables.
- **Accurate release metadata:** version and migration head are derived from source. Missing browser evidence fails the full gate; skipped checks are explicitly preflight only.
- **Security dependency updates:** the lockfile updates certifi, OpenTelemetry API, Pillow, fastembed, pypdf, and filelock. Recheck advisories when preparing each release.

Keep development services on loopback. Public hosting requires configured authentication, reviewed secrets and network exposure, tested migrations, and fresh end-to-end verification. See [SECURITY.md](SECURITY.md) for reporting guidance.

## Contributing and license

Bug reports and focused contributions are welcome. Include reproduction steps, relevant configuration with secrets removed, and expected versus actual behavior.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request and [CHANGELOG.md](CHANGELOG.md) for recorded changes. ARES is licensed under the [Apache License 2.0](LICENSE).
