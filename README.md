<div align="center">

# ARES
### Autonomous Research & Evidence System

[![Quality Gates](https://img.shields.io/badge/Quality%20Gates-10%2F10%20Passed-emerald.svg)](Makefile)
[![Tests](https://img.shields.io/badge/Tests-290%20Passed-brightgreen.svg)](backend/tests/)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-blue.svg)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.143-009688.svg)](backend/pyproject.toml)
[![Frontend](https://img.shields.io/badge/Frontend-React%2019%20%2B%20Vite%208-61dafb.svg)](apps/web/)
[![Database](https://img.shields.io/badge/Database-PostgreSQL%2018%20%2B%20pgvector-336791.svg)](infra/local/compose.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

<p align="center">
  <img src="ares_banner.jpg" alt="ARES - Autonomous Research & Evidence System" width="800" style="border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);" />
</p>

**ARES is a production-grade, evidence-grounded autonomous research engine. It orchestrates multi-source web and academic discovery, performs hybrid lexical and dense vector retrieval, maintains a 4-tier persistent cognitive memory hierarchy, and rigorously validates claims using deterministic and semantic verification.**

[Key Features](#-key-features) • [System Architecture](#-system-architecture) • [AI & Retrieval Theory](#-ai--retrieval-engineering-theory) • [Use Cases](#-use-cases) • [Quickstart Guide](#-quickstart-guide) • [Configuration](#-configuration--environment-variables) • [Quality Gates](#-quality-gates--testing) • [Security & Safety](#-security--trust-model)

---

</div>

## 🔬 System Overview

Unlike basic chat wrappers or fragile pipeline scripts that hallucinate citations, ARES implements a **staged, durable execution loop with lease-fenced background workers and claim-level truth verification**:

1. **Faceted Query Planning**: Deconstructs user research inquiries into orthogonal discovery facets, search intents, and target modalities.
2. **Multi-Source Discovery**: Fans out concurrent queries across web search ([SearXNG](https://github.com/searxng/searxng)), academic repositories ([OpenAlex](https://openalex.org), [CrossRef](https://www.crossref.org), [arXiv](https://arxiv.org)), and software ecosystems ([GitHub API](https://docs.github.com/en/rest)) with circuit-breaker protection.
3. **Safe Ingestion & Multimodal Extraction**: Ingests articles ([Trafilatura](https://trafilatura.readthedocs.io/)), PDFs ([pypdf](https://pypdf.readthedocs.io/)), and media assets ([Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) audio transcription and keyframe OCR) through SSRF-guarded fetchers.
4. **Hybrid RAG & Reciprocal Rank Fusion (RRF)**: Fuses PostgreSQL BM25 full-text search with 384-dimensional dense embeddings (`fastembed` BAAI/bge-small-en-v1.5) over `pgvector` HNSW indexes.
5. **4-Tier Cognitive Memory**: Manages Working Memory (active context), Episodic Memory (past run histories), Semantic Memory (verified facts & knowledge graph assertions), and Procedural Memory (retrieval strategies).
6. **Grounded Synthesis**: Context-bounded generation via Google Gemini or 100% private, local Ollama models (`qwen2.5:3b`, `qwen3:4b`), strictly restricted to admitted evidence passages.
7. **Two-Stage Claim Verification**: Decomposes synthesized narratives into atomic factual claims, validating quantities, units, and polarities against source evidence to label claims as `SUPPORTED`, `CONTRADICTED`, `CONFLICTING`, or `INSUFFICIENT_EVIDENCE`.
8. **Real-Time Visual Workspace**: Streams execution milestones to a React 19 visual canvas over Server-Sent Events (SSE) with interactive citation inspection, evidence drawer, and knowledge graphs.
9. **Model Context Protocol (MCP)**: Exposes standardized MCP endpoints for external AI agents to query evidence, inspect memory, and operate on structured data.

---

## 🏛 System Architecture

### Component Topology

```mermaid
flowchart TD
    subgraph ClientLayer ["Client Layer (Port 5173)"]
        WebUI["React 19 SPA (Vite 8 + TypeScript)"]
        SSEStream["SSE Event Consumer & State Sync"]
        CitationGraph["Interactive Citation & Evidence Drawer"]
    end

    subgraph ControlPlane ["API Control Plane (FastAPI - Port 8000)"]
        SecMiddleware["SecurityHeaders & RateLimiter"]
        AuthHandler["OIDC / Loopback Auth Guard"]
        Admission["Run Admission & Concurrency Caps"]
        MCPServer["Model Context Protocol (MCP) Server"]
    end

    subgraph MemoryHierarchy ["4-Tier Cognitive Memory Engine"]
        WorkingMem["Working Memory (Active Context & Budgets)"]
        EpisodicMem["Episodic Memory (Historical Runs & Journals)"]
        SemanticMem["Semantic Memory (Verified Facts & Triplets)"]
        ProceduralMem["Procedural Memory (Query & Retrieval Profiles)"]
    end

    subgraph StorageLayer ["Persistence & Vector Store"]
        PG[("PostgreSQL 18 + pgvector")]
        HNSW["HNSW Vector Indexes (384-dim Cosine)"]
        BM25["tsvector Full-Text Search"]
        RLS["Row-Level Security (Tenant Isolation)"]
        BlobStore["Content-Addressed Blob Storage (SHA-256)"]
    end

    subgraph WorkerExecution ["Durable Worker Loop (Lease-Fenced)"]
        Planner["1. Faceted Research Planner"]
        DiscoveryEngine["2. Multi-Source Search Coordinator"]
        Ingestor["3. SSRF-Safe Ingestion & Multimodal OCR"]
        Retriever["4. Hybrid Retriever & RRF Fusion"]
        Synthesizer["5. Grounded Synthesis Engine"]
        Verifier["6. Two-Stage Claim Verifier"]
    end

    subgraph ExternalEngines ["Engines & Model Providers"]
        SearXNG["SearXNG Meta-Search"]
        Academic["OpenAlex / CrossRef / arXiv"]
        LLM["Google Gemini / Local Ollama (Qwen)"]
        MediaTools["Faster-Whisper & PDF Parsers"]
    end

    WebUI -->|HTTP REST & SSE| SecMiddleware
    SecMiddleware --> AuthHandler --> Admission
    Admission -->|Enqueue Run| PG
    MCPServer <-->|Tool Queries| WorkingMem & SemanticMem

    WorkerExecution <-->|Monotonic Advisory Leases| PG
    Planner -->|Faceted Sub-queries| DiscoveryEngine
    DiscoveryEngine -->|Search Queries| SearXNG
    DiscoveryEngine -->|Academic Metadata| Academic
    DiscoveryEngine --> Ingestor

    Ingestor -->|Bounded Fetch| MediaTools
    Ingestor -->|Artifact Storage| BlobStore
    Ingestor -->|Generate Embeddings| HNSW

    Retriever <-->|BM25 + HNSW + RRF| PG
    Retriever --> Synthesizer
    Synthesizer <-->|Context-Bounded Prompting| LLM
    Synthesizer --> Verifier
    Verifier <-->|Assertion Validation| LLM
    Verifier -->|Record Run & Facts| EpisodicMem & SemanticMem
```

### End-to-End Research Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant API as FastAPI Control Plane
    participant DB as PostgreSQL (pgvector)
    participant Worker as Durable Worker
    participant Ext as Search & Academic APIs
    participant LLM as Gemini / Local Ollama

    User->>API: POST /api/runs (Query, Mode, Plugins)
    API->>API: Validate Rate Limits & Concurrency Caps
    API->>DB: Enqueue Run & Create Initial Milestone
    API-->>User: 202 Accepted (Run ID & SSE Stream URL)

    Worker->>DB: Acquire Advisory Lock & Lease Fencing Token
    Worker->>LLM: Deconstruct Query into Research Facets
    Worker->>Ext: Fan-out Search (SearXNG, OpenAlex, arXiv)
    Ext-->>Worker: Candidate Links & Paper Metadata

    Worker->>Worker: SSRF Verification & Safe Content Ingestion
    Worker->>Worker: Chunk Text & Generate 384-dim Embeddings
    Worker->>DB: Store Document Passages & pgvector Embeddings

    Worker->>DB: Hybrid Query (tsvector Full-Text + HNSW Vector Cosine)
    DB-->>Worker: Candidate Ranked Results
    Worker->>Worker: Reciprocal Rank Fusion (RRF k=60)

    Worker->>LLM: Grounded Synthesis (Admitted Passages Only)
    LLM-->>Worker: Draft Report with Citation Tags

    Worker->>Worker: Deterministic Quantity & Polarity Extraction
    Worker->>LLM: Semantic Verification on Ambiguous Claims
    Worker->>DB: Persist Final Report, Verified Facts & Episodes
    Worker-->>User: SSE Event: run.completed (Full Report & Evidence Graph)
```

---

## 🧠 AI & Retrieval Engineering Theory

### 1. Hybrid Retrieval & Reciprocal Rank Fusion (RRF)

Standard dense vector search frequently fails on domain-specific keywords, exact identifiers (e.g., patent numbers, molecular IDs, version tags), and out-of-vocabulary terms. Conversely, standard keyword search (BM25) struggles with conceptual paraphrasing and synonymy.

ARES bridges this semantic divide using **Hybrid RAG fused via Reciprocal Rank Fusion**:

$$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

Where:
- $M = \{\text{BM25 full-text}, \text{HNSW dense vector cosine}\}$
- $r_m(d)$ is the 1-based rank position of document $d$ within retrieval system $m$.
- $k$ is a smoothing constant set to $60$ (mitigating over-sensitivity to top outliers).

```
   User Research Query
            │
      ┌─────┴──────────────────────┐
      ▼                            ▼
PostgreSQL BM25            pgvector HNSW
(to_tsvector & tsquery)    (384-dim BGE Small)
      │                            │
      ▼                            ▼
 Lexical Top-K               Dense Top-K
      │                            │
      └─────────────┬──────────────┘
                    ▼
       Reciprocal Rank Fusion
        Score: 1/(60 + r_bm25) + 1/(60 + r_dense)
                    ▼
    Top-N Context-Bounded Packets
```

### 2. The 4-Tier Cognitive Memory Hierarchy

To prevent catastrophic forgetting across interactive sessions while maintaining strict context budgets, ARES implements a four-tiered persistent memory structure:

```
┌─────────────────────────────────────────────────────────────────┐
│                      4-Tier Memory System                       │
├───────────────────┬─────────────────────────────────────────────┤
│ 1. Working Memory │ In-flight research context, execution token  │
│                   │ budgets, and volatile scratchpad state.     │
├───────────────────┼─────────────────────────────────────────────┤
│ 2. Episodic       │ Chronological research run journals, run    │
│    Memory         │ outcomes, user queries, and key findings.   │
├───────────────────┼─────────────────────────────────────────────┤
│ 3. Semantic       │ Factual triplets (subject, predicate, fact),│
│    Memory         │ knowledge graph nodes, contradiction status.│
├───────────────────┼─────────────────────────────────────────────┤
│ 4. Procedural     │ Optimal discovery strategies, domain search │
│    Memory         │ templates, and adaptive retrieval profiles. │
└───────────────────┴─────────────────────────────────────────────┘
```

- **Semantic Memory Invariant**: Every factual triplet recorded in semantic memory tracks provenance (`evidence_source`, `confidence`), with transition states (`active`, `superseded`, `contradiction`) to resolve conflicting claims over time.
- **Model Context Protocol (MCP)**: Any external agent can query this memory fabric using `ares_query_memory` and `ares_search_evidence`.

### 3. Two-Stage Claim Verification Engine

Rather than trusting raw LLM generation, ARES implements a **two-stage verification pipeline** that audits every generated statement before rendering:

```mermaid
flowchart TD
    SynthesizedText["Synthesized Narrative"] --> Decompose["Atomic Claim Decomposition"]
    Decompose --> Stage1["Stage 1: Deterministic Engine"]
    
    subgraph S1 ["Deterministic Verification"]
        Quant["Regex Quantity Extraction (numbers + units)"]
        Polarity["Polarity & Negation Token Analysis"]
        Overlap["Jaccard Token Set Overlap"]
    end
    
    Stage1 --> S1
    S1 --> ConfCheck{"High Deterministic Confidence?"}
    
    ConfCheck -->|Yes| Verdict["Final Verdict (SUPPORTED / CONTRADICTED)"]
    ConfCheck -->|No / Ambiguous| Stage2["Stage 2: LLM Cross-Examination"]
    
    Stage2 --> Verdict
```

- **Deterministic Analysis**: Fast regex tokenization extracts numeric quantities (e.g., `45%`, `120 ms`, `$3.4M`), detects unit mismatches, and inspects negation words (`not`, `never`, `cannot`). If evidence contradicts the numeric value or polarity, the claim is flagged deterministically without spending LLM tokens.
- **Semantic Fallback**: When assertions contain qualitative inferences, ARES dispatches the exact claim and isolated source passages to an adversarial cross-examination prompt to generate a final confidence score.

---

## 🎯 Use Cases

| Domain | How ARES Solves It |
|---|---|
| **Academic & Scientific Research** | Fuses arXiv, OpenAlex, and CrossRef. Automatically cites peer-reviewed literature, cross-checks contradictory study outcomes, and builds interactive citation graphs. |
| **Deep Engineering & Architecture** | Ingests RFCs, whitepapers, GitHub codebases, and technical documentation. Produces reproducible trade-off evaluations and architecture comparison matrices. |
| **Autonomous Fact-Checking** | Audits complex assertions against primary sources, isolating unsupported claims and highlighting numeric inconsistencies or out-of-context quotes. |
| **Enterprise Document Intelligence** | Securely uploads and extracts proprietary PDFs, spreadsheets, and media transcripts. Answers questions with exact page-level and timestamp-level citations. |
| **Agentic Tool Integration (MCP)** | Plugs directly into external LLM agents (Claude Desktop, Cursor, Gemini CLI) via Model Context Protocol to serve as an evidence and research retrieval tool. |

---

## ⚡ Quickstart Guide

### System Prerequisites

- **Operating System**: macOS, Linux (Ubuntu 22.04+), or Windows (via WSL2)
- **Python**: `>=3.12, <3.16` (Python 3.12 or 3.13)
- **Package Manager**: [uv](https://astral.sh/uv) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js**: `>=20.0.0` (Node 22 LTS or 24 LTS) with `corepack` enabled
- **Docker**: Docker Engine & Docker Compose (for PostgreSQL and SearXNG)

---

### Step 1: Clone & Configure

```bash
# Clone the repository
git clone https://github.com/aman-bhaskar-codes/ARES.git
cd ARES

# Copy template environment configuration
cp .env.example .env
```

---

### Step 2: Choose Your Execution Mode

#### Option A: Zero-Config Demo Mode (Fastest — 60 Seconds)
*Uses pre-recorded evidence fixtures. Requires **zero API keys** and zero external services.*

1. Keep `.env` default (`ARES_MODE=demo`).
2. Install dependencies:
   ```bash
   uv sync --project backend --extra dev
   corepack enable
   pnpm install --frozen-lockfile
   ```
3. Start development stack:
   ```bash
   # Terminal 1: Infrastructure & DB Migrations
   make dev

   # Terminal 2: FastAPI Backend
   make api

   # Terminal 3: React 19 Frontend
   make web
   ```
4. Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)** in your browser!

---

#### Option B: 100% Private Local AI with Ollama
*Keeps all queries, documents, and research entirely on your machine.*

1. Install and start [Ollama](https://ollama.ai):
   ```bash
   ollama pull qwen3:4b
   ollama serve
   ```
2. Edit `.env`:
   ```dotenv
   ARES_MODE=local_live
   LOCAL_LLM_ENABLED=true
   LOCAL_LLM_URL=http://127.0.0.1:11434
   LOCAL_LLM_MODEL=qwen3:4b
   ```
3. Start the stack with `make dev`, `make api`, `make worker`, and `make web`.

---

#### Option C: Cloud Live Mode with Google Gemini
*High-speed multimodal synthesis powered by Gemini 2.5 Flash.*

1. Get an API key from [Google AI Studio](https://aistudio.google.com/).
2. Edit `.env`:
   ```dotenv
   ARES_MODE=local_live
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   GEMINI_RPM=15
   GEMINI_TPM=1000000
   ```
3. Start the stack with `make dev`, `make api`, `make worker`, and `make web`.

---

#### Option D: Docker Compose Full Stack
*Launches all services in isolated production-grade containers.*

```bash
docker compose -f infra/local/compose.yaml up -d
```

---

## ⚙ Configuration & Environment Variables

| Variable | Description | Default | Target Env |
|---|---|---|:---:|
| `ARES_MODE` | Execution profile (`demo`, `local_live`, `production`) | `demo` | All |
| `AUTH_MODE` | Authentication mode (`disabled` for local, `oidc` for prod) | `disabled` | Production |
| `DATABASE_URL` | PostgreSQL connection URL with pgvector extension | `postgresql+psycopg://ares:ares@127.0.0.1:5432/ares_dev` | All |
| `SEARXNG_URL` | Meta-search engine endpoint | `http://127.0.0.1:8080` | Local Live / Prod |
| `SEARXNG_SECRET` | Secret key for SearXNG private instance | Generated | Local Live / Prod |
| `GEMINI_API_KEY` | Google Gemini API key | `""` | Cloud Live |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` | Cloud Live |
| `LOCAL_LLM_ENABLED` | Enables local Ollama synthesis | `false` | Local Live |
| `LOCAL_LLM_URL` | Ollama service endpoint | `http://127.0.0.1:11434` | Local Live |
| `LOCAL_LLM_MODEL` | Local model tag | `qwen3:4b` | Local Live |
| `STRICT_FREE_MODE` | Blocks silent fallback to unbudgeted billable APIs | `true` | All |
| `RATE_LIMIT_ENABLED`| Per-client token-bucket rate limiting middleware | `true` (auto) | All |
| `PUBLIC_BASE_URL` | External base URL for API endpoints | `http://127.0.0.1:8000` | All |
| `FRONTEND_ORIGIN` | Allowed CORS origin for web client | `http://127.0.0.1:5173` | All |

---

## 🛠 Quality Gates & Testing

ARES enforces an automated **10-Gate Release Quality Standard** executed via `make check`. Every gate must pass 100% green before any release or commit:

```bash
make check
```

```
================================================================================
  ARES Quality Verification Pipeline (10/10 Gates)
================================================================================
 [1/10] Environment Doctor        : Environment dependencies & Python check
 [2/10] Dependency Lock Check     : uv.lock synchronization validation
 [3/10] Ruff Code Formatting      : Strict PEP 8, import sorting & linting
 [4/10] Mypy Static Typecheck     : Strict typing across core domain & ports
 [5/10] Secret Material Scanner   : Entropy & regex scanning for exposed keys
 [6/10] Backend Test Suite        : 290 unit & integration tests (pytest)
 [7/10] Offline Regression Eval   : Golden dataset citation & retrieval audit
 [8/10] Bytecode Compilation      : AST syntax validation on all modules
 [9/10] Database Migrations       : Empty & upgrade path verification
[10/10] Release Gate Proof        : SBOM, manifest, and contract validation
================================================================================
```

### Running Individual Checks

```bash
make lint           # Run Ruff linter across backend, tests, and scripts
make typecheck      # Run Mypy strict type checking
make test           # Run 290 backend unit tests
make security-scan  # Audit workspace for secrets and sensitive patterns
make openapi        # Export OpenAPI specification to apps/web/src/openapi.json
```

---

## 🛡 Security & Trust Model

- **Local Loopback Enforcement**: When `AUTH_MODE=disabled`, the control plane strictly refuses to bind to public IP interfaces, eliminating accidental network exposure.
- **SSRF Defense**: Outbound fetchers validate all resolved target IPs against private RFC 1918 and cloud metadata IP ranges (`169.254.169.254`), pinning DNS queries to prevent rebinding attacks.
- **Strict Content-Disposition (RFC 6266)**: Download endpoints sanitize file names with ASCII fallbacks and RFC 5987 percent-encoded UTF-8 strings, blocking CRLF and directory traversal exploits.
- **PostgreSQL Row-Level Security (RLS)**: Enforces tenant isolation natively in SQL queries via transaction variables (`app.current_tenant`).
- **Deterministic Billable Protection**: `STRICT_FREE_MODE=true` guarantees the engine will fail with an explicit diagnostic rather than secretly falling back to paid, metered APIs.

---

## 📄 License & Contributing

- **License**: Licensed under the [Apache License, Version 2.0](LICENSE).
- **Contributing**: Please review [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before opening pull requests.
- **Changelog**: Detailed release notes and milestone transitions are documented in [CHANGELOG.md](CHANGELOG.md).
