# Contributing to ARES

Thank you for your interest in contributing to **ARES (Autonomous Research & Evidence System)**! ARES is built with an uncompromising commitment to grounded synthesis, verifiable citations, deterministic replay, and multi-tenant security.

---

## Code of Conduct & Development Philosophy

1. **Grounded Over Generative**: ARES never invents citations, hallucinated sources, or ungrounded claims. All synthesis must link directly to persisted, immutable evidence records.
2. **Deterministic & Reproducible**: Workspaces, runs, and evaluations must be reproducible. No hidden state or ambient external calls without trace logs.
3. **Security First**: Input sanitization, strict boundary validation, least-privilege database roles, SSRF mitigations, and per-client rate limiting are non-negotiable.

---

## Development Prerequisites

- **Python**: `>=3.12, <3.16` (Python 3.12 or 3.13 recommended)
- **uv**: Fast Python package and environment manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js**: `>=20` (Node 24 LTS recommended) with `corepack` enabled (`corepack enable`)
- **pnpm**: Package manager for frontend (`corepack prepare pnpm@latest --activate`)
- **Docker**: For local infrastructure services (PostgreSQL 18 with pgvector, SearXNG)

---

## Local Development Setup

### 1. Clone Repository & Configure Environment

```bash
git clone https://github.com/aman-bhaskar-codes/ARES.git
cd ARES
cp .env.example .env
```

Review `.env`. By default, ARES runs in **keyless demo mode** (`ARES_MODE=demo`), requiring no cloud API keys. To enable live research with Gemini, provide your `GEMINI_API_KEY` and set `ARES_MODE=local_live`.

### 2. Verify Prerequisites

```bash
make doctor
```

### 3. Start Local Infrastructure & Apply Migrations

```bash
make infra      # Starts PostgreSQL (pgvector) and SearXNG containers
make migrate    # Applies Alembic database migrations to HEAD
```

### 4. Run Application Services

In separate terminal panes or windows:

```bash
make api       # FastAPI backend with reload at http://127.0.0.1:8000
make worker    # Durable asynchronous research background worker
make web       # Vite + React frontend at http://127.0.0.1:3000
```

---

## Quality Gates & Verification

Before opening a pull request, all 10 quality gates must pass cleanly:

```bash
make check
```

You can also run individual verification steps:

- **Run Test Suite**: `make test`
- **Run Linter**: `make lint` (Ruff formatting & static checks)
- **Run Type Checker**: `make typecheck` (Mypy on domain and ports)
- **Run Secret Scanner**: `make security-scan`
- **Verify Dependencies**: `make lock-check`
- **Generate OpenAPI Schema**: `make openapi`

---

## Commit Guidelines

We enforce the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat:` New features or user-facing capabilities
- `fix:` Bug fixes or security patches
- `docs:` Documentation improvements
- `refactor:` Code refactoring without behavior change
- `chore:` Dependency updates, tooling, or build configuration
- `ci:` Continuous integration workflow modifications

---

## Pull Request Process

1. Fork the repository and create your branch from `v3-development` (e.g., `feat/my-feature`).
2. Ensure all tests and `make check` pass locally.
3. Never commit `.env` files, API keys, or binary caches.
4. Keep PRs focused with clear descriptions of rationale and testing steps.
