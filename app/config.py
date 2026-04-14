from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    timezone: str
    root_dir: Path
    data_dir: Path
    blob_dir: Path
    db_path: Path
    registry_path: Path
    digest_dir: Path
    templates_dir: Path
    static_dir: Path
    playwright_auth_dir: Path
    gmail_credentials_path: Path
    gmail_token_path: Path
    gmail_scopes: tuple[str, ...]
    blob_backend: str
    drive_blob_folder_id: str | None
    local_llm_backend: str
    local_llm_model: str
    local_llm_temperature: float
    local_llm_max_tokens: int
    local_llm_prompt_max_chars: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = root_dir / "data"
    return Settings(
        app_name=os.getenv("FORME_APP_NAME", "Forme 취업 허브"),
        timezone=os.getenv("FORME_TIMEZONE", "Asia/Tokyo"),
        root_dir=root_dir,
        data_dir=data_dir,
        blob_dir=Path(os.getenv("FORME_BLOB_DIR", data_dir / "blobs")),
        db_path=Path(os.getenv("FORME_DB_PATH", data_dir / "forme.db")),
        registry_path=Path(
            os.getenv("FORME_SOURCE_REGISTRY", root_dir / "config" / "source_registry.json")
        ),
        digest_dir=Path(os.getenv("FORME_DIGEST_DIR", data_dir / "digests")),
        templates_dir=root_dir / "app" / "templates",
        static_dir=root_dir / "app" / "static",
        playwright_auth_dir=root_dir / "playwright" / ".auth",
        gmail_credentials_path=Path(
            os.getenv(
                "FORME_GMAIL_CREDENTIALS",
                root_dir / "auth" / "google-oauth" / "credentials.json",
            )
        ),
        gmail_token_path=Path(
            os.getenv(
                "FORME_GMAIL_TOKEN",
                root_dir / "auth" / "google-oauth" / "token.json",
            )
        ),
        gmail_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        blob_backend=os.getenv("FORME_BLOB_BACKEND", "local"),
        drive_blob_folder_id=os.getenv("FORME_DRIVE_BLOB_FOLDER_ID") or None,
        local_llm_backend=os.getenv("FORME_LOCAL_LLM_BACKEND", "mlx"),
        local_llm_model=os.getenv("FORME_LOCAL_LLM_MODEL", "gemma4:e4b-it-8bit"),
        local_llm_temperature=float(os.getenv("FORME_LOCAL_LLM_TEMPERATURE", "0.1")),
        local_llm_max_tokens=int(os.getenv("FORME_LOCAL_LLM_MAX_TOKENS", "900")),
        local_llm_prompt_max_chars=int(os.getenv("FORME_LOCAL_LLM_MAX_PROMPT_CHARS", "18000")),
    )
