import pytest

from ares.application.documents import DocumentIngestService
from ares.domain.models import DocumentTextCreate


class FakeBlobStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []
    def put_bytes(self, namespace: str, content: bytes) -> str:
        return "documents/sha256/deadbeef"
    def delete(self, key: str) -> None:
        self.deleted.append(key)


class FailingRepository:
    def create_user_document(self, **kwargs):
        raise RuntimeError("db unavailable")
    def is_blob_referenced(self, key: str) -> bool:
        return False


class UnusedPdfParser:
    pass


def test_ingest_cleans_unreferenced_blob_when_db_persistence_fails() -> None:
    blobs = FakeBlobStore()
    service = DocumentIngestService(FailingRepository(), blobs, UnusedPdfParser())
    with pytest.raises(RuntimeError, match="db unavailable"):
        service.ingest_text(DocumentTextCreate(name="notes.txt", text="research evidence"))
    assert blobs.deleted == ["documents/sha256/deadbeef"]
