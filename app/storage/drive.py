from __future__ import annotations

from app.storage.base import BlobRecord, BlobStoreUnavailableError


class DriveBlobStore:
    backend_name = "drive"

    def __init__(self, folder_id: str | None) -> None:
        self.folder_id = folder_id

    def put_bytes(self, *, namespace: str, data: bytes, extension: str) -> BlobRecord:
        raise BlobStoreUnavailableError("DriveBlobStore는 아직 구현 전입니다. 현재는 local backend만 사용하세요.")

    def get_bytes(self, *, blob_id: str) -> bytes:
        raise BlobStoreUnavailableError("DriveBlobStore는 아직 구현 전입니다. 현재는 local backend만 사용하세요.")
