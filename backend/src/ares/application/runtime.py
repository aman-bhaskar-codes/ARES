from __future__ import annotations

from ares.adapters.arxiv import ArxivAcademicProvider
from ares.adapters.crossref import CrossrefAcademicProvider
from ares.adapters.gemini import GeminiLLMProvider
from ares.adapters.gemini_semantic import GeminiSemanticClaimChecker
from ares.adapters.gemini_embeddings import GeminiEmbeddingProvider
from ares.adapters.local_embeddings import LocalFastEmbedProvider
from ares.adapters.github_software import GitHubSoftwareProvider
from ares.adapters.jev import JevConfig, JevDecisionProvider
from ares.adapters.openalex import OpenAlexAcademicProvider
from ares.adapters.safe_fetch import SafeHttpFetcher
from ares.adapters.browser_fetch import BrowserFallbackFetcher, BrowserFetcher
from ares.adapters.searxng import SearXNGSearchProvider
from ares.api.settings import Settings
from ares.application.engine import DemoResearchEngine, ResearchEngine
from ares.application.persistent_rag import PersistentDocumentRAG
from ares.application.providers import ProviderRegistry
from ares.application.rag import HybridRAGRetriever
from ares.application.repository import Repository


def build_embedding_runtime(settings: Settings):
    """Return the configured embedding provider and immutable index identity.

    Local embeddings take precedence when explicitly enabled. A deployment must not
    mix local and Gemini vectors under one profile even when their dimensions happen
    to match.
    """
    if settings.local_embeddings_enabled:
        provider = LocalFastEmbedProvider(
            model=settings.local_embedding_model,
            cache_dir=settings.local_embedding_cache_dir,
            threads=settings.local_embedding_threads,
            batch_size=settings.local_embedding_batch_size,
        )
        return provider, settings.local_embedding_model, settings.local_embedding_dimensions
    if settings.gemini_embeddings_enabled:
        provider = GeminiEmbeddingProvider(
            settings.gemini_api_key,
            model=settings.gemini_embedding_model,
            dimensions=settings.gemini_embedding_dimensions,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
        return provider, settings.gemini_embedding_model, settings.gemini_embedding_dimensions
    return None, "", settings.local_embedding_dimensions


from ares.adapters.local_reranker import LocalCrossEncoderReranker

def _build_research_runtime(settings: Settings, repository: Repository, *, embedding_runtime=None):
    """Compose external adapters once at the worker process boundary."""
    if settings.ares_mode == "demo":
        return DemoResearchEngine(repository)

    settings.validate_live_mode()
    decisions = None
    if settings.jev_enabled:
        decisions = JevDecisionProvider(
            JevConfig(
                api_key=settings.jev_api_key,
                model=settings.jev_model,
                base_url=settings.jev_base_url,
                timeout_seconds=settings.provider_http_timeout_seconds,
            )
        )

    embedder, embedding_model_id, embedding_dimensions = (
        embedding_runtime if embedding_runtime is not None else build_embedding_runtime(settings)
    )

    registry = ProviderRegistry()
    registry.register(
        SearXNGSearchProvider(
            settings.searxng_url, timeout_seconds=settings.provider_http_timeout_seconds
        )
    )
    registry.register(OpenAlexAcademicProvider(settings.openalex_api_key))
    registry.register(CrossrefAcademicProvider(mailto=settings.crossref_mailto))
    registry.register(
        ArxivAcademicProvider(min_interval_seconds=settings.arxiv_min_interval_seconds)
    )
    registry.register(GitHubSoftwareProvider(settings.github_read_token))
    
    profile_id = None
    if embedding_model_id:
        profile = repository.get_retrieval_profile_by_model(embedding_model_id)
        if profile:
            profile_id = profile["id"]

    persistent_documents = PersistentDocumentRAG(
        repository,
        embedder=embedder,
        profile_id=profile_id,
        model_id=embedding_model_id,
        dimensions=embedding_dimensions,
        rpm=settings.gemini_embedding_rpm or 1,
        tpm=settings.gemini_embedding_tpm or 1,
        rpd=settings.gemini_embedding_rpd or 1,
    )
    semantic_checker = None
    if settings.semantic_checker_enabled:
        semantic_checker = GeminiSemanticClaimChecker(
            settings.gemini_api_key,
            settings.semantic_checker_model,
            thinking_level=settings.gemini_thinking_level,
            timeout_seconds=settings.semantic_checker_timeout_seconds,
        )

    safe_source_fetcher = SafeHttpFetcher()
    source_fetcher = safe_source_fetcher
    if settings.browser_enabled:
        source_fetcher = BrowserFallbackFetcher(
            safe_source_fetcher,
            BrowserFetcher(
                settings.browser_service_url,
                service_token=settings.browser_service_token,
                timeout_seconds=settings.browser_timeout_seconds,
            ),
        )

    from ares.application.planning import DeterministicResearchPlanner
    from ares.adapters.ollama_synthesis import OllamaLLMProvider
    planner = DeterministicResearchPlanner()
    writer = (
        OllamaLLMProvider(settings.local_llm_url, settings.local_llm_model)
        if settings.local_llm_enabled else GeminiLLMProvider(
            settings.gemini_api_key, settings.gemini_model,
            thinking_level=settings.gemini_thinking_level,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    )

    return ResearchEngine(
        repository,
        SearXNGSearchProvider(
            settings.searxng_url, timeout_seconds=settings.provider_http_timeout_seconds
        ),
        source_fetcher,
        writer,
        planner=planner,
        candidate_reranker=LocalCrossEncoderReranker(),
        gemini_model=settings.local_llm_model if settings.local_llm_enabled else settings.gemini_model,
        gemini_rpm=60 if settings.local_llm_enabled else settings.gemini_rpm or 1,
        gemini_tpm=100_000 if settings.local_llm_enabled else settings.gemini_tpm or 1,
        gemini_rpd=10_000 if settings.local_llm_enabled else settings.gemini_rpd or 1,
        gemini_max_daily_spend_usd=settings.gemini_max_daily_spend_usd if settings.gemini_max_daily_spend_usd > 0 else None,
        global_http_concurrency=settings.max_http_concurrency,
        gemini_concurrency=settings.gemini_concurrency,
        provider_http_timeout_seconds=settings.provider_http_timeout_seconds,
        source_fetch_timeout_seconds=settings.source_fetch_timeout_seconds,
        gemini_timeout_seconds=settings.local_llm_timeout_seconds if settings.local_llm_enabled else settings.gemini_timeout_seconds,
        decisions=decisions,
        retriever=HybridRAGRetriever(embedder=embedder),
        registry=registry,
        persistent_documents=persistent_documents,
        discovery_concurrency=settings.discovery_concurrency,
        research_cache_enabled=settings.research_cache_enabled,
        web_search_cache_ttl_seconds=settings.web_search_cache_ttl_seconds,
        web_source_cache_ttl_seconds=settings.web_source_cache_ttl_seconds,
        academic_cache_ttl_seconds=settings.academic_cache_ttl_seconds,
        software_cache_ttl_seconds=settings.software_cache_ttl_seconds,
        semantic_checker=semantic_checker,
        semantic_checker_model=settings.semantic_checker_model,
        semantic_checker_max_claims=settings.semantic_checker_max_claims,
        semantic_checker_timeout_seconds=settings.semantic_checker_timeout_seconds,
        academic_full_text_fetcher=safe_source_fetcher
        if settings.academic_full_text_enabled
        else None,
        academic_full_text_limit=settings.academic_full_text_limit,
        academic_full_text_timeout_seconds=settings.academic_full_text_timeout_seconds,
        academic_full_text_max_bytes=settings.academic_full_text_max_bytes,
        academic_full_text_max_pages=settings.academic_full_text_max_pages,
    )


def build_research_runtime(settings: Settings, repository: Repository, *, embedding_runtime=None):
    if settings.ares_mode == "demo":
        return DemoResearchEngine(repository)
    from ares.application.model_routing import ModelRoutingEngine
    engines = {}
    if settings.gemini_api_key:
        engines["gemini"] = _build_research_runtime(
            settings.model_copy(update={"local_llm_enabled": False}), repository,
            embedding_runtime=embedding_runtime)
    if settings.local_llm_enabled:
        engines["qwen"] = _build_research_runtime(settings, repository, embedding_runtime=embedding_runtime)
    return ModelRoutingEngine(repository, engines, default="qwen" if settings.local_llm_enabled else "gemini")
