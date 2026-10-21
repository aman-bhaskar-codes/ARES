import pytest
from ares.adapters.local_reranker import LocalCrossEncoderReranker


def test_missing_cached_reranker_never_downloads_or_breaks_startup(monkeypatch):
    from fastembed.rerank import cross_encoder
    def unavailable(**kwargs):
        if not kwargs.get('local_files_only'):
            pytest.fail('runtime attempted an unprovisioned model download')
        raise ValueError('model not provisioned')
    monkeypatch.setattr(cross_encoder, 'TextCrossEncoder', unavailable)
    ranker = LocalCrossEncoderReranker()
    assert ranker.rerank('query', [], max_results=3) == []
