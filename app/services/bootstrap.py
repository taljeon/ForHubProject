from __future__ import annotations

from app.config import Settings, get_settings


def ensure_project_dirs(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.blob_dir.mkdir(parents=True, exist_ok=True)
    settings.digest_dir.mkdir(parents=True, exist_ok=True)
    settings.playwright_auth_dir.mkdir(parents=True, exist_ok=True)
    settings.gmail_credentials_path.parent.mkdir(parents=True, exist_ok=True)
