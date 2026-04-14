from __future__ import annotations

import json
from datetime import date, datetime
from hashlib import sha256
from typing import Any
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

