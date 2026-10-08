from __future__ import annotations


class ModelRoutingEngine:
    """Choose a process-owned engine from the provider saved with each run."""

    def __init__(self, repository, engines: dict, *, default: str):
        self.repository = repository
        self.engines = engines
        self.default = default

    def execute(self, lease):
        self.repository.authorize_run_execution(lease.run_id, lease_token=lease.token)
        run = self.repository.get_run(lease.run_id)
        provider = run.model_provider or self.default
        engine = self.engines.get(provider)
        if engine is None:
            self.repository.fail_run(
                lease.run_id,
                "MODEL_UNAVAILABLE",
                f"{provider.title()} is not configured on this server.",
                lease_token=lease.token,
            )
            return
        engine.execute(lease)

    def close(self):
        for engine in self.engines.values():
            engine.close()
