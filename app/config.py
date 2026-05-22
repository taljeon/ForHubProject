from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.utils import parse_env_csv, parse_env_flag


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
    allowed_hosts: tuple[str, ...]
    require_localhost: bool
    require_same_origin_posts: bool
    enable_demo_tools: bool
    enable_api_docs: bool
    dashboard_host: str
    dashboard_port: int
    dashboard_access_token_path: Path
    log_dir: Path
    blob_backend: str
    drive_blob_folder_id: str | None
    local_llm_backend: str
    local_llm_model: str
    local_llm_temperature: float
    local_llm_max_tokens: int
    local_llm_prompt_max_chars: int


def _load_local_env_files(default_root_dir: Path) -> None:
    values: dict[str, str] = {}
    for env_path in (default_root_dir / ".env", default_root_dir / ".env.local"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            value = raw_value.strip()
            if value.startswith(("\"", "'")) and value.endswith(("\"", "'")) and len(value) >= 2:
                value = value[1:-1]
            values[key.strip()] = value
    for key, value in values.items():
        os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_root_dir = Path(__file__).resolve().parent.parent
    _load_local_env_files(default_root_dir)
    root_dir = Path(os.getenv("FORME_ROOT_DIR", default_root_dir)).expanduser()
    data_dir = Path(os.getenv("FORME_DATA_DIR", root_dir / "data")).expanduser()
    dashboard_host = os.getenv("FORME_DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    default_allowed_hosts = tuple(
        dict.fromkeys(
            (
                dashboard_host,
                "127.0.0.1",
                "localhost",
                "::1",
                "[::1]",
                "testserver",
            )
        )
    )
    return Settings(
        app_name=os.getenv("FORME_APP_NAME", "Forme 취업 허브"),
        timezone=os.getenv("FORME_TIMEZONE", "Asia/Tokyo"),
        root_dir=root_dir,
        data_dir=data_dir,
        blob_dir=Path(os.getenv("FORME_BLOB_DIR", data_dir / "blobs")).expanduser(),
        db_path=Path(os.getenv("FORME_DB_PATH", data_dir / "forme.db")).expanduser(),
        registry_path=Path(
            os.getenv("FORME_SOURCE_REGISTRY", root_dir / "config" / "source_registry.json")
        ).expanduser(),
        digest_dir=Path(os.getenv("FORME_DIGEST_DIR", data_dir / "digests")).expanduser(),
        templates_dir=root_dir / "app" / "templates",
        static_dir=root_dir / "app" / "static",
        playwright_auth_dir=Path(
            os.getenv("FORME_PLAYWRIGHT_AUTH_DIR", root_dir / "playwright" / ".auth")
        ).expanduser(),
        gmail_credentials_path=Path(
            os.getenv(
                "FORME_GMAIL_CREDENTIALS",
                root_dir / "auth" / "google-oauth" / "credentials.json",
            )
        ).expanduser(),
        gmail_token_path=Path(
            os.getenv(
                "FORME_GMAIL_TOKEN",
                root_dir / "auth" / "google-oauth" / "token.json",
            )
        ).expanduser(),
        gmail_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        allowed_hosts=parse_env_csv(
            os.getenv("FORME_ALLOWED_HOSTS"),
            default=default_allowed_hosts,
        ),
        require_localhost=parse_env_flag(
            os.getenv("FORME_REQUIRE_LOCALHOST"),
            default=True,
        ),
        require_same_origin_posts=parse_env_flag(
            os.getenv("FORME_REQUIRE_SAME_ORIGIN_POSTS"),
            default=True,
        ),
        enable_demo_tools=parse_env_flag(
            os.getenv("FORME_ENABLE_DEMO_TOOLS"),
            default=False,
        ),
        enable_api_docs=parse_env_flag(
            os.getenv("FORME_ENABLE_API_DOCS"),
            default=False,
        ),
        dashboard_host=dashboard_host,
        dashboard_port=int(os.getenv("FORME_DASHBOARD_PORT", "8000")),
        dashboard_access_token_path=Path(
            os.getenv("FORME_DASHBOARD_ACCESS_TOKEN_PATH", data_dir / "dashboard-access.token")
        ).expanduser(),
        log_dir=Path(os.getenv("FORME_LOG_DIR", data_dir / "logs")).expanduser(),
        blob_backend=os.getenv("FORME_BLOB_BACKEND", "local"),
        drive_blob_folder_id=os.getenv("FORME_DRIVE_BLOB_FOLDER_ID") or None,
        local_llm_backend=os.getenv("FORME_LOCAL_LLM_BACKEND", "mlx"),
        local_llm_model=os.getenv("FORME_LOCAL_LLM_MODEL", "gemma4:e4b-it-8bit"),
        local_llm_temperature=float(os.getenv("FORME_LOCAL_LLM_TEMPERATURE", "0.1")),
        local_llm_max_tokens=int(os.getenv("FORME_LOCAL_LLM_MAX_TOKENS", "900")),
        local_llm_prompt_max_chars=int(os.getenv("FORME_LOCAL_LLM_MAX_PROMPT_CHARS", "18000")),
    )
