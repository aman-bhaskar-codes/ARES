from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class FilesystemBlobStore:
    """Content-addressed local blob store with atomic writes and path confinement."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("invalid blob key")
        path = (self.root / key).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("blob key escapes configured root")
        return path

    def put_bytes(self, namespace: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        safe_namespace = "/".join(part for part in namespace.split("/") if part and part not in {".", ".."})
        key = f"{safe_namespace}/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
        target = self._path(key)
        if target.exists():
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".ares-blob-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key


    def put_file(self, namespace: str, path: str | Path) -> str:
        source = Path(path)
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        hexdigest = digest.hexdigest()
        safe_namespace = "/".join(part for part in namespace.split("/") if part and part not in {".", ".."})
        key = f"{safe_namespace}/sha256/{hexdigest[:2]}/{hexdigest[2:4]}/{hexdigest}"
        target = self._path(key)
        if target.exists():
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".ares-blob-", dir=target.parent)
        try:
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def get_size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def get_range(self, key: str, start: int, end_inclusive: int) -> bytes:
        if start < 0 or end_inclusive < start:
            raise ValueError("invalid blob byte range")
        with self._path(key).open("rb") as handle:
            handle.seek(start)
            return handle.read(end_inclusive - start + 1)

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
