from __future__ import annotations

from unittest.mock import MagicMock

from ares.adapters.s3_blob import S3BlobStore


def test_s3_blob_store_operations_mocked() -> None:
    mock_client = MagicMock()

    store = S3BlobStore(
        endpoint_url="http://minio:9000",
        bucket="test-bucket",
        access_key="minioadmin",
        secret_key="minioadmin",
        client=mock_client,
    )

    # 1. put_bytes
    mock_client.head.return_value.status_code = 404
    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_client.put.return_value = mock_put_resp

    key = store.put_bytes("docs", b"hello world s3")
    assert "docs/sha256/" in key
    assert mock_client.put.called

    # 2. exists
    mock_client.head.return_value.status_code = 200
    assert store.exists(key) is True

    # 3. get_bytes
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.content = b"hello world s3"
    mock_client.get.return_value = mock_get_resp

    data = store.get_bytes(key)
    assert data == b"hello world s3"

    # 4. get_size
    mock_client.head.return_value.headers = {"content-length": "14"}
    assert store.get_size(key) == 14

    # 5. delete
    mock_del_resp = MagicMock()
    mock_del_resp.status_code = 204
    mock_client.delete.return_value = mock_del_resp
    store.delete(key)
    assert mock_client.delete.called
