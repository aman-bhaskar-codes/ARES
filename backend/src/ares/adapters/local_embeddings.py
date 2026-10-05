from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class LocalFastEmbedProvider:
    """Local ONNX embedding adapter backed by FastEmbed.

    The dependency and model are loaded lazily so the core text-only profile can
    start without the optional local-ML extra. Documents and queries use the
    retrieval-specific FastEmbed methods instead of sharing an ambiguous generic
    embedding path.
    """

    def __init__(
        self,
        *,
        model: str,
        cache_dir: str | None = None,
        threads: int | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model = model
        self.cache_dir = str(Path(cache_dir).expanduser()) if cache_dir else None
        self.threads = threads
        self.batch_size = batch_size
        self._client = None

    def _load(self):
        if self._client is not None:
            return self._client
        try:
            from fastembed import TextEmbedding  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency boundary
            raise RuntimeError(
                "FastEmbed is not installed; install the M08 local-ML optional dependency"
            ) from exc
        kwargs: dict[str, object] = {"model_name": self.model, "local_files_only": True}
        if self.cache_dir:
            kwargs["cache_dir"] = self.cache_dir
        if self.threads is not None:
            kwargs["threads"] = self.threads
        self._client = TextEmbedding(**kwargs)
        return self._client

    @staticmethod
    def _vectors(items: Iterable[object]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for item in items:
            tolist = getattr(item, "tolist", None)
            values = tolist() if callable(tolist) else list(item)  # type: ignore[arg-type]
            vectors.append([float(value) for value in values])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        client = self._load()
        method = getattr(client, "query_embed", None)
        if not callable(method):  # pragma: no cover - compatibility guard
            method = client.embed
        vectors = self._vectors(method([text], batch_size=1))
        if len(vectors) != 1:
            raise RuntimeError("FastEmbed query embedding returned an unexpected vector count")
        return vectors[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._load()
        method = getattr(client, "passage_embed", None)
        if not callable(method):  # pragma: no cover - compatibility guard
            method = client.embed
        vectors = self._vectors(method(texts, batch_size=self.batch_size))
        if len(vectors) != len(texts):
            raise RuntimeError("FastEmbed document embedding count did not match input count")
        return vectors

    def close(self) -> None:
        self._client = None
