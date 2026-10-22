# Changelog

All notable changes to the **ARES (Autonomous Research & Evidence System)** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.12.0] - 2026-10-21

### Added
- **Security Headers Middleware**: Implemented `SecurityHeadersMiddleware` injecting `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, strict Content-Security-Policy (CSP), and conditional HSTS.
- **Per-Client Rate Limiting**: Added `RateLimitMiddleware` providing configurable token-bucket rate limiting for write operations, file uploads, and research run creation.
- **Local Loopback Enforcement**: Restricted `AUTH_MODE=disabled` strictly to local loopback interfaces (`127.0.0.1`, `localhost`, `::1`), requiring explicit `ALLOW_INSECURE_REMOTE_DISABLED_AUTH=true` override for remote testing.
- **Interactive Command Guide**: Added `make help` with categorized CLI targets for local development, background workers, and quality gates.
- **Community Governance**: Added `CONTRIBUTING.md`, `CODEOWNERS`, and comprehensive `CHANGELOG.md`.

### Changed
- **RFC 6266 Filename Sanitization**: Hardened download response headers with sanitized ASCII and RFC 5987 UTF-8 encoded filename parameters, preventing path traversal and header injection.
- **Dependency Pinning**: Pinned exact package versions for `fastembed` (`0.8.1`) and `playwright` (`1.63.0`), synchronized and validated against `backend/uv.lock`.
- **Makefile Optimization**: Removed redundant nested `uv run` invocations across build, audit, and diagnostic scripts.
- **Asset Optimization**: Losslessly compressed project imagery (`ares_banner.jpg` optimized from 797KB to 208KB).

### Fixed
- **Release Verification Script**: Added guard verifying directory existence before executing Playwright end-to-end tests in headless validation environments.
- **SQL Parameterization Commentary**: Added explicit security documentation for PostgreSQL dynamic bind variable generation in semantic retrieval adapters.

---

## [0.11.0] - 2026-10-17

### Added
- **M11 Evidence-Linked Visual Research Workspace**: Interactive React 19 interface with live SSE research logs, citation inspector, and synthesis canvas.
- **M10 Hybrid Retrieval & Semantic Grounding**: Integrated PostgreSQL `tsvector` full-text search with `pgvector` HNSW cosine distance semantic search.
- **Multi-Source Discovery Engine**: Coordinated real-time web discovery across SearXNG, OpenAlex, CrossRef, arXiv, and GitHub API.
- **Local LLM Support**: Added support for local Ollama instances (`qwen3:4b`) as alternative to cloud-hosted Gemini models.

---

## [0.9.0] - 2026-10-08

### Added
- **M09 Multimodal Evidence Processing**: Provisioned background workers for Whisper audio transcription (`small-multilingual`), OCR keyframe processing, and bounded video evidence extraction.
- **M08 Rich Parsing Pipeline**: Durable document ingestion supporting PDF, CSV, and plain text with chunk-level attribution.

---

## [0.6.0] - 2026-10-05

### Added
- **M06 Security & Multi-Tenancy**: Row-Level Security (RLS) policies in PostgreSQL, OIDC authentication provider, tenant isolation, and CSRF double-submit cookie validation.
- **M01-M05 Durable Research Engine**: Multi-step state machine with deterministic replay, task queue, and SSE streaming event logs.
