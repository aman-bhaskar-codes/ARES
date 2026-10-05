class SearchProviderError(RuntimeError):
    pass


class ProviderRateLimitError(SearchProviderError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMProviderError(RuntimeError):
    pass
