from __future__ import annotations

from unittest.mock import MagicMock

from ares.application.model_registry import ModelDescriptor, ModelProviderRegistry


def test_model_provider_registry() -> None:
    registry = ModelProviderRegistry()

    # Defaults are populated
    models = registry.list_models()
    assert len(models) >= 5
    family_set = {m.family for m in models}
    assert "gemini" in family_set
    assert "ollama" in family_set

    # Register custom provider
    fake_provider = MagicMock()
    registry.register_provider("custom_ollama", fake_provider, default=True)

    resolved = registry.get_provider("custom_ollama")
    assert resolved == fake_provider

    # Default fallback
    assert registry.get_provider() == fake_provider

    # Custom model descriptor
    desc = ModelDescriptor(
        provider="custom_ollama",
        model_id="deepseek-r1:latest",
        display_name="DeepSeek R1",
        family="ollama",
        context_window=65_536,
        is_vision_capable=False,
    )
    registry.register_descriptor(desc)
    assert registry.get_descriptor("deepseek-r1:latest") == desc
