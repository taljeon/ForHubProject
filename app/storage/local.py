from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from app.storage.base import BlobRecord


class LocalBlobStore:
    backend_name = "local"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, *, namespace: str, data: bytes, extension: str) -> BlobRecord:
        checksum = sha256(data).hexdigest()
        safe_namespace = namespace.strip("/").replace("..", "_") or "misc"
        relative_path = Path(safe_namespace) / checksum[:2] / checksum[2:4] / f"{checksum}{extension}"
        target_path = self.root_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.exists():
            target_path.write_bytes(data)
        return BlobRecord(
            blob_id=str(relative_path),
            storage_backend=self.backend_name,
            checksum=checksum,
            size_bytes=len(data),
        )

    def get_bytes(self, *, blob_id: str) -> bytes:
        target_path = self.root_dir / blob_id
        return target_path.read_bytes()
