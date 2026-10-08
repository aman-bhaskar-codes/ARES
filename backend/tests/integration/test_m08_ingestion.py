from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser
from ares.api.app import create_app
from ares.api.settings import Settings
from ares.application.asset_ingestion import (
    AssetAdmissionService,
    AssetIngestionExecutor,
    BuiltinRichExtractor,
)
from ares.application.indexing import DocumentEmbeddingIndexer
from ares.application.persistent_rag import PersistentDocumentRAG


class FakeEmbedder:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        lower = text.casefold()
        return [
            1.0 if "alpha" in lower else 0.1,
            1.0 if "90" in lower else 0.1,
            1.0 if "beta" in lower else 0.1,
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)


def _ingest_csv(repository, tmp_path: Path, *, embedder=None):
    blobs = FilesystemBlobStore(str(tmp_path / "blobs"))
    staged = tmp_path / "sample.csv"
    staged.write_bytes(b"name,value\nalpha,10\nbeta,90\ngamma,\n")
    admission = AssetAdmissionService(repository, blobs, max_upload_bytes=1024 * 1024)
    admitted = admission.admit_staged(path=staged, name="sample.csv", supplied_mime="text/csv")
    lease = repository.claim_next_ingestion()
    assert lease is not None and lease.ingestion_id == admitted.ingestion.id
    indexer = DocumentEmbeddingIndexer(
        repository,
        embedder,
        model_id="fake-3d" if embedder is not None else "",
        dimensions=3,
        batch_size=2,
        max_chunks=100,
    )
    executor = AssetIngestionExecutor(
        repository,
        blobs,
        BuiltinRichExtractor(
            BoundedPdfParser(max_bytes=1024 * 1024, max_pages=10, timeout_seconds=5)
        ),
        indexer,
        max_table_cells=100,
    )
    executor.execute(lease)
    return admitted


def test_csv_ingestion_publishes_table_segments_and_background_embeddings(
    repository, tmp_path: Path
) -> None:
    embedder = FakeEmbedder()
    admitted = _ingest_csv(repository, tmp_path, embedder=embedder)

    ingestion = repository.get_ingestion(admitted.ingestion.id)
    assert ingestion.status.value == "ready"
    assert ingestion.lexical_ready is True
    assert ingestion.semantic_ready is True
    assert ingestion.document_id is not None
    assert embedder.document_calls >= 1

    document = repository.get_documents([ingestion.document_id])[0]
    assert document.asset_version_id == admitted.asset.id
    assert document.lexical_ready is True
    assert document.semantic_ready is True

    chunks = repository.get_document_chunks([document.id])
    assert chunks and all(chunk.evidence_segment_id is not None for chunk in chunks)
    segment = repository.get_segment(chunks[0].evidence_segment_id)
    assert segment.asset_id == admitted.asset.id
    assert segment.locator.kind == "table_cells"

    table = repository.get_table_for_segment(segment.id)
    assert (table.rows, table.columns) == (4, 2)
    by_cell = {(cell.row, cell.column): cell for cell in table.cells}
    assert by_cell[(1, 1)].raw_text == "10"
    assert by_cell[(1, 1)].normalized_value == 10
    assert by_cell[(3, 1)].raw_text == ""
    assert by_cell[(3, 1)].normalized_value is None

    rag = PersistentDocumentRAG(
        repository,
        embedder=embedder,
        model_id="fake-3d",
        dimensions=3,
        rpm=100,
        tpm=100_000,
        rpd=1000,
    )
    result = rag.retrieve(
        "beta 90",
        documents=[document],
        source_id_by_document={document.id: uuid4()},
        limit=3,
    )
    assert result.semantic_used is True
    assert result.embedded_chunks == 0
    assert embedder.query_calls == 1
    assert any(candidate.segment_id is not None for candidate in result.candidates)


def test_v2_asset_api_is_async_and_supports_authorized_byte_ranges(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}",
        blob_root=str(tmp_path / "blobs"),
    )
    client = TestClient(create_app(settings))
    payload = b"name,value\nalpha,10\nbeta,90\n"
    created = client.post(
        "/api/v2/assets",
        files={"file": ("sample.csv", payload, "text/csv")},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["ingestion"]["status"] == "queued"
    assert body["ingestion"]["document_id"] is None

    worker = client.post("/api/v1/internal/worker/run-once")
    assert worker.status_code == 200 and worker.json()["kind"] == "ingestion"
    status = client.get(f"/api/v2/ingestions/{body['ingestion']['id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "ready"
    assert status.json()["lexical_ready"] is True

    ranged = client.get(
        f"/api/v2/assets/{body['asset']['id']}/content",
        headers={"Range": "bytes=0-8"},
    )
    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == f"bytes 0-8/{len(payload)}"
    assert ranged.content == payload[:9]


def test_v2_asset_api_rejects_image_extension_without_matching_signature(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'reject.sqlite3'}",
        blob_root=str(tmp_path / "blobs"),
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/v2/assets",
        files={"file": ("fake.png", b"this-is-not-a-png", "image/png")},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "ASSET_ADMISSION_REJECTED"


class FailingEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("local embedding runtime unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("not used")


def test_semantic_index_failure_preserves_lexical_document_as_partial(
    repository, tmp_path: Path
) -> None:
    admitted = _ingest_csv(repository, tmp_path, embedder=FailingEmbedder())

    ingestion = repository.get_ingestion(admitted.ingestion.id)
    assert ingestion.status.value == "partial"
    assert ingestion.lexical_ready is True
    assert ingestion.semantic_ready is False
    assert ingestion.document_id is not None
    assert any("Semantic indexing unavailable" in warning for warning in ingestion.warnings)

    document = repository.get_documents([ingestion.document_id])[0]
    assert document.lexical_ready is True
    assert document.semantic_ready is False
    assert repository.get_document_chunks([document.id])


def test_ingestion_cancel_retry_is_durable_and_idempotent(repository, tmp_path: Path) -> None:
    blobs = FilesystemBlobStore(str(tmp_path / "cancel-blobs"))
    staged = tmp_path / "cancel.csv"
    staged.write_bytes(b"name,value\nalpha,10\n")
    admission = AssetAdmissionService(repository, blobs, max_upload_bytes=1024 * 1024)
    admitted = admission.admit_staged(path=staged, name="cancel.csv", supplied_mime="text/csv")

    cancelled = repository.request_ingestion_cancel(admitted.ingestion.id)
    assert cancelled.status.value == "cancelled"
    assert repository.claim_next_ingestion() is None

    retried = repository.retry_ingestion(admitted.ingestion.id)
    assert retried.status.value == "queued"
    lease = repository.claim_next_ingestion()
    assert lease is not None and lease.ingestion_id == admitted.ingestion.id

    executor = AssetIngestionExecutor(
        repository,
        blobs,
        BuiltinRichExtractor(
            BoundedPdfParser(max_bytes=1024 * 1024, max_pages=10, timeout_seconds=5)
        ),
        DocumentEmbeddingIndexer(repository, None, model_id="", dimensions=3),
        max_table_cells=100,
    )
    executor.execute(lease)
    finished = repository.get_ingestion(admitted.ingestion.id)
    assert finished.status.value == "ready"
    events = repository.list_ingestion_events(admitted.ingestion.id)
    kinds = [event.event_type for event in events]
    assert "ingestion.cancelled" in kinds
    assert "ingestion.retried" in kinds
    assert kinds[-1] == "ingestion.ready"


def test_asset_repository_hides_cross_workspace_ids(repository, tmp_path: Path) -> None:
    from uuid import uuid4

    from ares.application.identity import Principal, WorkspaceRole, principal_scope
    from ares.application.repository import NotFoundError

    blobs = FilesystemBlobStore(str(tmp_path / "tenant-blobs"))
    staged = tmp_path / "tenant.csv"
    staged.write_bytes(b"name,value\nalpha,10\n")
    admission = AssetAdmissionService(repository, blobs, max_upload_bytes=1024 * 1024)
    admitted = admission.admit_staged(path=staged, name="tenant.csv", supplied_mime="text/csv")

    other = Principal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        role=WorkspaceRole.OWNER,
        subject="test:other-workspace",
    )
    with principal_scope(other):
        try:
            repository.get_asset_record(admitted.asset.id)
        except NotFoundError:
            pass
        else:  # pragma: no cover - explicit isolation assertion
            raise AssertionError("cross-workspace asset ID was visible")
        try:
            repository.get_ingestion(admitted.ingestion.id)
        except NotFoundError:
            pass
        else:  # pragma: no cover - explicit isolation assertion
            raise AssertionError("cross-workspace ingestion ID was visible")
