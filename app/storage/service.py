from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.storage.base import BlobRecord, BlobStoreUnavailableError
from app.storage.drive import DriveBlobStore
from app.storage.local import LocalBlobStore
from app.utils import json_dumps, json_loads, now_iso


@lru_cache(maxsize=4)
def _build_blob_store(
    backend: str,
    blob_dir: str,
    drive_folder_id: str | None,
):
    if backend == "local":
        return LocalBlobStore(root_dir=Path(blob_dir))
    if backend == "drive":
        return DriveBlobStore(folder_id=drive_folder_id)
    raise BlobStoreUnavailableError(f"지원하지 않는 blob backend입니다: {backend}")


def get_blob_store(settings: Settings | None = None):
    settings = settings or get_settings()
    return _build_blob_store(
        settings.blob_backend,
        str(settings.blob_dir),
        settings.drive_blob_folder_id,
    )


def store_text_blob(
    text: str,
    *,
    namespace: str,
    extension: str = ".txt",
    settings: Settings | None = None,
) -> BlobRecord:
    settings = settings or get_settings()
    return get_blob_store(settings).put_bytes(
        namespace=namespace,
        data=text.encode("utf-8"),
        extension=extension,
    )


def store_json_blob(
    value: Any,
    *,
    namespace: str,
    settings: Settings | None = None,
) -> BlobRecord:
    return store_text_blob(
        json_dumps(value),
        namespace=namespace,
        extension=".json",
        settings=settings,
    )


def load_text_blob(
    *,
    blob_id: str | None,
    settings: Settings | None = None,
) -> str | None:
    if not blob_id:
        return None
    settings = settings or get_settings()
    data = get_blob_store(settings).get_bytes(blob_id=blob_id)
    return data.decode("utf-8")


def load_json_blob(
    *,
    blob_id: str | None,
    default: Any,
    settings: Settings | None = None,
) -> Any:
    text = load_text_blob(blob_id=blob_id, settings=settings)
    if text is None:
        return default
    return json_loads(text, default)


def migrate_raw_fields_to_blobs(
    connection,
    *,
    settings: Settings | None = None,
    clear_legacy_columns: bool = True,
) -> dict[str, int]:
    settings = settings or get_settings()
    migrated_notes = 0
    migrated_jobs = 0
    timestamp = now_iso(settings.timezone)

    note_rows = connection.execute(
        """
        SELECT id, raw_text
        FROM interview_notes
        WHERE (raw_blob_id IS NULL OR raw_blob_id = '')
          AND raw_text IS NOT NULL
          AND TRIM(raw_text) != ''
        """
    ).fetchall()
    for row in note_rows:
        blob = store_text_blob(
            str(row["raw_text"]),
            namespace="interview_notes",
            extension=".txt",
            settings=settings,
        )
        connection.execute(
            """
            UPDATE interview_notes
            SET raw_blob_id = ?, raw_storage_backend = ?, raw_checksum = ?, raw_size_bytes = ?,
                raw_text = CASE WHEN ? THEN NULL ELSE raw_text END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                blob.blob_id,
                blob.storage_backend,
                blob.checksum,
                blob.size_bytes,
                1 if clear_legacy_columns else 0,
                timestamp,
                row["id"],
            ),
        )
        migrated_notes += 1

    job_rows = connection.execute(
        """
        SELECT id, raw_payload_json
        FROM job_posts
        WHERE (raw_blob_id IS NULL OR raw_blob_id = '')
          AND raw_payload_json IS NOT NULL
          AND TRIM(raw_payload_json) != ''
        """
    ).fetchall()
    for row in job_rows:
        blob = store_text_blob(
            str(row["raw_payload_json"]),
            namespace="job_posts",
            extension=".json",
            settings=settings,
        )
        connection.execute(
            """
            UPDATE job_posts
            SET raw_blob_id = ?, raw_storage_backend = ?, raw_checksum = ?, raw_size_bytes = ?,
                raw_payload_json = CASE WHEN ? THEN NULL ELSE raw_payload_json END,
                changed_at = ?
            WHERE id = ?
            """,
            (
                blob.blob_id,
                blob.storage_backend,
                blob.checksum,
                blob.size_bytes,
                1 if clear_legacy_columns else 0,
                timestamp,
                row["id"],
            ),
        )
        migrated_jobs += 1

    return {
        "interview_notes": migrated_notes,
        "job_posts": migrated_jobs,
    }
