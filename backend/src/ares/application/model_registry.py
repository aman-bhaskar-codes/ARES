from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ares.ports.model_provider import ModelProvider

logger = logging.getLogger("ares.model_registry")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    provider: str
    model_id: str
    display_name: str
    family: str  # "gemini", "ollama", "local", "synthetic"
    context_window: int
    is_vision_capable: bool
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelProviderRegistry:
    """Central registry and dispatch table for grounded synthesis and reasoning models."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._descriptors: dict[str, ModelDescriptor] = {}
        self._default_provider_name: str = "deterministic"
        self._init_defaults()

    def _init_defaults(self) -> None:
        defaults = [
            ModelDescriptor(
                provider="gemini",
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                family="gemini",
                context_window=1_000_000,
                is_vision_capable=True,
            ),
            ModelDescriptor(
                provider="gemini",
                model_id="gemini-2.5-pro",
                display_name="Gemini 2.5 Pro",
                family="gemini",
                context_window=2_000_000,
                is_vision_capable=True,
            ),
            ModelDescriptor(
                provider="ollama",
                model_id="qwen2.5:latest",
                display_name="Qwen 2.5 7B (Local)",
                family="ollama",
                context_window=32_768,
                is_vision_capable=False,
            ),
            ModelDescriptor(
                provider="ollama",
                model_id="qwen2.5-vl:latest",
                display_name="Qwen 2.5 VL (Local Vision)",
                family="ollama",
                context_window=32_768,
                is_vision_capable=True,
            ),
            ModelDescriptor(
                provider="ollama",
                model_id="llama3.2-vision:latest",
                display_name="Llama 3.2 Vision (Local)",
                family="ollama",
                context_window=128_000,
                is_vision_capable=True,
            ),
            ModelDescriptor(
                provider="deterministic",
                model_id="deterministic-v1",
                display_name="Deterministic Test Provider",
                family="synthetic",
                context_window=8_192,
                is_vision_capable=False,
            ),
        ]
        for desc in defaults:
            self._descriptors[desc.model_id] = desc

    def register_provider(self, name: str, provider: ModelProvider, default: bool = False) -> None:
        self._providers[name] = provider
        if default or len(self._providers) == 1:
            self._default_provider_name = name
        logger.info("Registered model provider: %s", name)

    def get_provider(self, name: str | None = None) -> ModelProvider:
        target = name or self._default_provider_name
        if target in self._providers:
            return self._providers[target]
        if self._default_provider_name in self._providers:
            return self._providers[self._default_provider_name]
        raise KeyError(f"No model provider registered for: {target}")

    def register_descriptor(self, descriptor: ModelDescriptor) -> None:
        self._descriptors[descriptor.model_id] = descriptor

    def list_models(self) -> list[ModelDescriptor]:
        return list(self._descriptors.values())

    def get_descriptor(self, model_id: str) -> ModelDescriptor | None:
        return self._descriptors.get(model_id)
