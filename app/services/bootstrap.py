from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except FileNotFoundError:
        return
    except PermissionError:
        return
    except OSError:
        return


def _ensure_directory(path: Path, *, mode: int | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        _chmod_best_effort(path, mode)


def ensure_private_directory(path: Path) -> None:
    _ensure_directory(path, mode=0o700)


def ensure_private_file(path: Path) -> None:
    if path.exists():
        _chmod_best_effort(path, 0o600)


def ensure_project_dirs(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    _ensure_directory(settings.data_dir)
    _ensure_directory(settings.blob_dir)
    _ensure_directory(settings.digest_dir)
    _ensure_directory(settings.log_dir)
    ensure_private_directory(settings.playwright_auth_dir)
    ensure_private_directory(settings.gmail_credentials_path.parent)
    ensure_private_directory(settings.gmail_token_path.parent)
    ensure_private_directory(settings.dashboard_access_token_path.parent)
    ensure_private_file(settings.gmail_credentials_path)
    ensure_private_file(settings.gmail_token_path)
    ensure_private_file(settings.dashboard_access_token_path)
