from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BlobStoreUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlobRecord:
    blob_id: str
    storage_backend: str
    checksum: str
    size_bytes: int


class BlobStore(Protocol):
    backend_name: str

    def put_bytes(self, *, namespace: str, data: bytes, extension: str) -> BlobRecord: ...

    def get_bytes(self, *, blob_id: str) -> bytes: ...

