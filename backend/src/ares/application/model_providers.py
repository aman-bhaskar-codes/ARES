"""Model configuration/catalog and writer factories share one registry."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ares.adapters.gemini import GeminiLLMProvider
from ares.adapters.ollama_synthesis import OllamaLLMProvider
from ares.api.settings import Settings
from ares.ports.model_provider import ModelProvider

ProviderId = Literal['gemini', 'qwen']


@dataclass(frozen=True)
class ProviderDefinition:
    id: ProviderId
    label: str
    location: Literal['cloud', 'local']
    model_attribute: str
    is_available: Callable[[Settings], bool]
    factory: Callable[[Settings], ModelProvider]
    capabilities: tuple[str, ...] = ('grounded_json',)


class ModelProviderRegistry:
    def __init__(self) -> None:
        self.providers = (
            ProviderDefinition('gemini', 'Gemini', 'cloud', 'gemini_model',
                lambda cfg: bool(cfg.gemini_api_key),
                lambda cfg: GeminiLLMProvider(cfg.gemini_api_key, cfg.gemini_model,
                    thinking_level=cfg.gemini_thinking_level, timeout_seconds=cfg.gemini_timeout_seconds)),
            ProviderDefinition('qwen', 'Qwen', 'local', 'local_llm_model',
                lambda cfg: cfg.local_llm_enabled,
                lambda cfg: OllamaLLMProvider(cfg.local_llm_url, cfg.local_llm_model,
                    context_tokens=cfg.local_llm_context_tokens, passage_chars=cfg.local_llm_passage_chars)),
        )

    def default(self, cfg: Settings) -> ProviderId:
        return next((p.id for p in self.providers if p.location == 'local' and p.is_available(cfg)), self.providers[0].id)

    def get(self, provider_id: str) -> ProviderDefinition:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise ValueError(f'Unknown model provider: {provider_id}')

    def catalog(self, cfg: Settings) -> dict[str, object]:
        return {'default': self.default(cfg), 'models': [
            {'id': p.id, 'label': p.label, 'model': getattr(cfg, p.model_attribute),
             'available': p.is_available(cfg), 'location': p.location} for p in self.providers]}


MODEL_PROVIDERS = ModelProviderRegistry()
