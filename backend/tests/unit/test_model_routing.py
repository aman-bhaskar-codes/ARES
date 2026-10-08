from types import SimpleNamespace
from unittest.mock import Mock

from ares.application.model_routing import ModelRoutingEngine


def test_routes_each_run_to_its_persisted_provider():
    repo = Mock()
    engines = {"gemini": Mock(), "qwen": Mock()}
    router = ModelRoutingEngine(repo, engines, default="qwen")
    for provider in ["gemini", "qwen", None]:
        repo.get_run.return_value = SimpleNamespace(model_provider=provider)
        lease = SimpleNamespace(run_id=provider, token="lease")
        router.execute(lease)
        engines[provider or "qwen"].execute.assert_called_with(lease)
    router.close()
    for engine in engines.values():
        engine.close.assert_called_once()
