from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("ares.adapters.s3_blob")


class S3BlobStore:
    """Content-addressed S3 / MinIO compatible object store.

    Implements the BlobStore port for production deployments, MinIO local stacks,
    and cloud storage (AWS S3, Cloudflare R2, Google Cloud Storage via S3 API).
    """

    def __init__(
        self,
        *,
        endpoint_url: str = "http://127.0.0.1:9000",
        bucket: str = "ares-blobs",
        access_key: str = "",
        secret_key: str = "",
        region: str = "us-east-1",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.timeout_seconds = timeout_seconds
        self._client: httpx.Client | None = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.timeout_seconds)

    def _object_url(self, key: str) -> str:
        clean_key = key.lstrip("/")
        return f"{self.endpoint_url}/{self.bucket}/{clean_key}"

    @property
    def _auth_kwargs(self) -> dict[str, Any]:
        if self.access_key and self.secret_key:
            return {"auth": (self.access_key, self.secret_key)}
        return {}

    def put_bytes(self, namespace: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        safe_namespace = "/".join(
            part for part in namespace.split("/") if part and part not in {".", ".."}
        )
        key = f"{safe_namespace}/sha256/{digest[:2]}/{digest[2:4]}/{digest}"

        if self.exists(key):
            return key

        url = self._object_url(key)
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(content)),
        }

        client = self._get_client()
        resp = client.put(url, content=content, headers=headers, **self._auth_kwargs)
        if resp.status_code not in {200, 201, 204}:
            raise RuntimeError(f"S3 put_bytes failed ({resp.status_code}): {resp.text[:200]}")
        return key

    def put_file(self, namespace: str, path: str | Path) -> str:
        source = Path(path)
        content = source.read_bytes()
        return self.put_bytes(namespace, content)

    def get_bytes(self, key: str) -> bytes:
        url = self._object_url(key)
        client = self._get_client()
        resp = client.get(url, **self._auth_kwargs)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Blob not found in S3 store: {key}")
        if resp.status_code != 200:
            raise RuntimeError(f"S3 get_bytes failed ({resp.status_code}): {resp.text[:200]}")
        return resp.content

    def get_size(self, key: str) -> int:
        url = self._object_url(key)
        client = self._get_client()
        resp = client.head(url, **self._auth_kwargs)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Blob not found in S3 store: {key}")
        if resp.status_code != 200:
            raise RuntimeError(f"S3 head_object failed ({resp.status_code})")
        return int(resp.headers.get("content-length", 0))

    def get_range(self, key: str, start: int, end_inclusive: int) -> bytes:
        url = self._object_url(key)
        headers = {"Range": f"bytes={start}-{end_inclusive}"}
        client = self._get_client()
        resp = client.get(url, headers=headers, **self._auth_kwargs)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Blob not found in S3 store: {key}")
        if resp.status_code not in {200, 206}:
            raise RuntimeError(f"S3 get_range failed ({resp.status_code})")
        return resp.content

    def delete(self, key: str) -> None:
        url = self._object_url(key)
        client = self._get_client()
        resp = client.delete(url, **self._auth_kwargs)
        if resp.status_code not in {200, 204, 404}:
            raise RuntimeError(f"S3 delete failed ({resp.status_code})")

    def exists(self, key: str) -> bool:
        url = self._object_url(key)
        client = self._get_client()
        try:
            resp = client.head(url, **self._auth_kwargs)
            return resp.status_code == 200
        except Exception:
            return False
