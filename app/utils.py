from __future__ import annotations

import json
from datetime import date, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


def now_local(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def now_iso(timezone_name: str) -> str:
    return now_local(timezone_name).isoformat(timespec="seconds")


def today_local(timezone_name: str) -> date:
    return now_local(timezone_name).date()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def stable_hash(value: Any) -> str:
    return sha256(json_dumps(value).encode("utf-8")).hexdigest()


def parse_env_flag(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def parse_env_csv(value: str | None, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def normalize_navigation_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    parsed = urlparse(stripped)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return stripped


def normalize_optional_date(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    datetime.strptime(stripped, "%Y-%m-%d")
    return stripped


def normalize_priority(value: int, *, minimum: int = 1, maximum: int = 5) -> int:
    if value < minimum or value > maximum:
        raise ValueError(f"Priority must be between {minimum} and {maximum}.")
    return value
