# Incremental typing coverage

CI now invokes strict mypy on domain, ports, application and API. The explicit module overrides in root pyproject.toml track legacy annotation debt; they must shrink as those modules are changed. API routers and dependency injection are checked without an override. Adapters remain outside the expanded gate. This is incremental coverage, not a claim of complete backend type safety.

Current deferred modules:

- `ares.api.bootstrap`
- `ares.api.event_stream`
- `ares.api.ingestion_stream`
- `ares.application.asset_ingestion`
- `ares.application.auth`
- `ares.application.checkpoints`
- `ares.application.decisions`
- `ares.application.documents`
- `ares.application.engine`
- `ares.application.exports`
- `ares.application.gemini_planner`
- `ares.application.media_ingestion`
- `ares.application.model_routing`
- `ares.application.observability`
- `ares.application.persistent_rag`
- `ares.application.report_builder`
- `ares.application.research_cache`
- `ares.application.research_stages.discovery`
- `ares.application.research_stages.synthesis`
- `ares.application.runtime`
- `ares.application.table_operations`
- `ares.application.tool_adapters`
- `ares.application.tool_executor`
- `ares.application.visualizations`
- `ares.application.watchlist_manager`
