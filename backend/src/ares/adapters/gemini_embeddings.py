from __future__ import annotations


class GeminiEmbeddingProvider:
    """Optional Gemini embedding adapter; imported lazily so keyless demo has no SDK dependency."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-embedding-2",
        dimensions: int = 768,
        timeout_seconds: float = 45.0,
        client=None,
    ):
        if not api_key.strip():
            raise ValueError("Gemini API key is required for embeddings")
        if not 128 <= dimensions <= 3072:
            raise ValueError("embedding dimensions must be between 128 and 3072")
        owns_client = client is None
        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("google-genai is not installed") from exc
        self._types = types
        self.model = model
        self.dimensions = dimensions
        self.client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=max(1, int(float(timeout_seconds) * 1000))),
        )
        self._owns_client = owns_client

    def _embed(self, texts: list[str]) -> list[list[float]]:
        contents = [
            self._types.Content(parts=[self._types.Part.from_text(text=text)])
            for text in texts
        ]
        result = self.client.models.embed_content(
            model=self.model,
            contents=contents,
            config=self._types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )
        vectors: list[list[float]] = []
        for embedding in result.embeddings or []:
            values = embedding.values or []
            vectors.append([float(value) for value in values])
        if len(vectors) != len(texts):
            raise RuntimeError("Gemini embeddings response count did not match request")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"task: retrieval | query: {text}"])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed([f"task: retrieval | document: {text}" for text in texts])

    def close(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
