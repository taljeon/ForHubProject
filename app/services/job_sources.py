from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.config import Settings, get_settings
from app.storage import load_json_blob, store_json_blob
from app.utils import json_dumps, json_loads, now_iso, stable_hash


ENGINEER_KEYWORDS: dict[str, float] = {
    "software engineer": 30,
    "backend": 18,
    "frontend": 18,
    "full stack": 16,
    "infra": 16,
    "platform engineer": 16,
    "sre": 18,
    "data engineer": 18,
    "machine learning": 18,
    "security": 16,
    "研究開発": 12,
    "技術職": 10,
    "開発職": 12,
    "エンジニア": 20,
    "developer": 16,
}

JOB_TRACK_LABELS = {
    "internship": "인턴",
    "main_selection": "본선고",
    "event": "설명회 / 이벤트",
    "unknown": "미분류",
}

INTERNSHIP_HINTS = (
    "サマーインターン",
    "夏インターン",
    "winter internship",
    "summer internship",
    "internship",
    "intern",
    "インターン",
)

MAIN_SELECTION_HINTS = (
    "本選考",
    "新卒採用",
    "new grad",
    "graduate",
    "entry",
    "エントリー",
    "本採用",
)

EVENT_HINTS = (
    "イベント",
    "説明会",
    "セミナー",
    "meetup",
    "career forum",
    "オープン・カンパニー",
)

SOURCE_NAME_BY_DOMAIN = {
    "syukatsu-kaigi.jp": "就活会議",
    "www.syukatsu-kaigi.jp": "就活会議",
    "onecareer.jp": "ONE CAREER",
    "www.onecareer.jp": "ONE CAREER",
    "openwork.jp": "OpenWork",
    "www.openwork.jp": "OpenWork",
    "mynavi.jp": "マイナビ",
    "job.mynavi.jp": "マイナビ",
    "rikunabi.com": "リクナビ",
    "job.rikunabi.com": "リクナビ",
    "gaishishukatsu.com": "外資就活ドットコム",
    "www.gaishishukatsu.com": "外資就活ドットコム",
    "talent.supporterz.jp": "サポーターズ",
    "www.supporterz.jp": "サポーターズ",
    "trackjob.jp": "Track Job",
    "www.trackjob.jp": "Track Job",
}

JOB_IMPORT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8,ko;q=0.7",
}


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def _truncate_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def infer_source_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    if host in SOURCE_NAME_BY_DOMAIN:
        return SOURCE_NAME_BY_DOMAIN[host]
    if host.startswith("www.") and host[4:] in SOURCE_NAME_BY_DOMAIN:
        return SOURCE_NAME_BY_DOMAIN[host[4:]]
    if not host:
        return None
    parts = [part for part in host.split(".") if part and part != "www"]
    return parts[0] if parts else host


def _extract_meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return _normalize_space(str(tag["content"]))
    return None


def _extract_text_blocks(root: Any) -> list[str]:
    if root is None:
        return []
    blocks: list[str] = []
    seen: set[str] = set()
    for element in root.find_all(["h1", "h2", "h3", "p", "li", "dt", "dd"]):
        text = _normalize_space(element.get_text(" ", strip=True))
        if len(text) < 2:
            continue
        if text in seen:
            continue
        seen.add(text)
        blocks.append(text)
    return blocks


def _extract_html_sections(root: Any) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for heading in root.find_all(["h2", "h3"]):
        title = _normalize_space(heading.get_text(" ", strip=True))
        if not title or len(title) > 80 or title in seen_titles:
            continue
        seen_titles.add(title)
        chunks: list[str] = []
        sibling = heading.next_sibling
        while sibling is not None and len(chunks) < 5:
            sibling_name = getattr(sibling, "name", None)
            if sibling_name in {"h1", "h2", "h3"}:
                break
            if hasattr(sibling, "get_text"):
                text = _normalize_space(sibling.get_text(" ", strip=True))
            else:
                text = _normalize_space(str(sibling))
            if text:
                chunks.append(text)
            sibling = sibling.next_sibling
        if chunks:
            sections.append(
                {
                    "title": title,
                    "content": _truncate_text("\n".join(chunks), 1800),
                }
            )
        if len(sections) >= 10:
            break
    return sections


def _infer_company_name_from_text(
    connection: sqlite3.Connection,
    *,
    title: str,
    body_text: str,
) -> str | None:
    haystack = "\n".join([title, body_text])
    rows = connection.execute(
        "SELECT name FROM companies ORDER BY LENGTH(name) DESC, name ASC"
    ).fetchall()
    for row in rows:
        name = str(row["name"] or "").strip()
        if name and name in haystack:
            return name

    for separator in ("｜", "|", " - ", " – ", " / ", "／", "｜採用", "採用情報"):
        if separator not in title:
            continue
        for part in [item.strip() for item in title.split(separator)]:
            if 2 <= len(part) <= 40 and not re.search(r"(募集|採用|インターン|本選考|エントリー)", part):
                return part
    return None


def _strip_company_from_title(title: str, company_name: str | None) -> str:
    cleaned = _normalize_space(title)
    if not company_name:
        return cleaned
    patterns = [
        rf"^{re.escape(company_name)}\s*[\-|｜|/／:：]*\s*",
        rf"\s*[\-|｜|/／:：]*\s*{re.escape(company_name)}$",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned).strip()
    return cleaned or title


def _extract_deadline(text: str) -> str | None:
    patterns = (
        r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})",
        r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日",
    )
    context_pattern = re.compile(r"(締切|応募締切|応募期限|エントリー締切|受付期限)")
    lines = text.splitlines()
    for line in lines:
        if not context_pattern.search(line):
            continue
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
                return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _extract_location(text: str) -> str | None:
    patterns = (
        r"(?:勤務地|勤務場所|開催場所|勤務エリア)\s*[:：]?\s*([^\n]{1,80})",
        r"(?:Location)\s*[:：]?\s*([^\n]{1,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _truncate_text(_normalize_space(match.group(1)), 80)
    return None


def extract_job_post_from_html(
    connection: sqlite3.Connection,
    *,
    url: str,
    html: str,
    company_name: str | None = None,
    source_name: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()

    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    document_title = _normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "")
    heading_title = _normalize_space((soup.find("h1") or {}).get_text(" ", strip=True) if soup.find("h1") else "")
    page_title = _extract_meta_content(soup, "og:title") or heading_title or document_title or url
    description = _extract_meta_content(soup, "description", "og:description")
    text_blocks = _extract_text_blocks(content_root)
    body_text = "\n".join(text_blocks)
    inferred_company = company_name or _infer_company_name_from_text(
        connection,
        title="\n".join(item for item in [page_title, document_title] if item),
        body_text=body_text,
    )
    title = _strip_company_from_title(page_title, inferred_company)
    sections = _extract_html_sections(content_root)
    summary = description or _truncate_text("\n".join(text_blocks[:4]), 320)
    employment_type = infer_job_track(title, body_text, url)
    graduate_year = infer_graduate_year(title, body_text, url)
    location = _extract_location(body_text)
    deadline = _extract_deadline(body_text)
    resolved_source_name = source_name or infer_source_name_from_url(url) or "수동 링크"
    raw_payload = {
        "source_name": resolved_source_name,
        "source_url": url,
        "page_title": page_title,
        "description": description,
        "body_text": _truncate_text(body_text, 24000),
        "sections": sections,
        "fetched_at": now_iso(settings.timezone),
    }
    return {
        "company_name": inferred_company or "미분류",
        "source_name": resolved_source_name,
        "source_seed_url": url,
        "title": title or page_title,
        "url": url,
        "employment_type": employment_type,
        "graduate_year": graduate_year,
        "location": location,
        "deadline": deadline,
        "summary": summary,
        "raw_payload": raw_payload,
    }


def import_job_post_from_url(
    connection: sqlite3.Connection,
    *,
    url: str,
    company_name: str | None = None,
    source_name: str | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    response = requests.get(url, headers=JOB_IMPORT_HEADERS, timeout=20)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = response.apparent_encoding or "utf-8"
    extracted = extract_job_post_from_html(
        connection,
        url=url,
        html=response.text,
        company_name=company_name,
        source_name=source_name,
        settings=settings,
    )
    return upsert_job_post(
        connection,
        company_name=extracted["company_name"],
        source_seed_url=extracted["source_seed_url"],
        title=extracted["title"],
        url=extracted["url"],
        employment_type=extracted["employment_type"],
        graduate_year=extracted["graduate_year"],
        location=extracted["location"],
        deadline=extracted["deadline"],
        summary=extracted["summary"],
        raw_payload=extracted["raw_payload"],
        settings=settings,
    )


def load_registry(registry_path: Path | None = None, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    registry_path = registry_path or settings.registry_path
    return json.loads(registry_path.read_text(encoding="utf-8"))


def ensure_company(
    connection: sqlite3.Connection,
    *,
    name: str,
    careers_url: str | None = None,
    notes: str | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    connection.execute(
        """
        INSERT INTO companies (name, careers_url, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            careers_url = COALESCE(excluded.careers_url, companies.careers_url),
            notes = COALESCE(excluded.notes, companies.notes),
            updated_at = excluded.updated_at
        """,
        (name, careers_url, notes, timestamp, timestamp),
    )
    row = connection.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
    return int(row["id"])


def seed_registry(connection: sqlite3.Connection, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    entries = load_registry(settings=settings)
    timestamp = now_iso(settings.timezone)
    for entry in entries:
        company_id = ensure_company(
            connection,
            name=entry["company"],
            careers_url=entry.get("careers_url") or entry.get("base_url"),
            notes=entry.get("company_notes"),
            settings=settings,
        )
        connection.execute(
            """
            INSERT INTO job_sources (
                company_id, source_name, source_type, base_url, seed_url,
                parser_kind, requires_login, state, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(seed_url) DO UPDATE SET
                company_id = excluded.company_id,
                source_name = excluded.source_name,
                source_type = excluded.source_type,
                base_url = excluded.base_url,
                parser_kind = excluded.parser_kind,
                requires_login = excluded.requires_login,
                state = excluded.state,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                company_id,
                entry["source_name"],
                entry["source_type"],
                entry["base_url"],
                entry["seed_url"],
                entry["parser_kind"],
                1 if entry.get("requires_login") else 0,
                entry.get("state", "active"),
                entry.get("notes"),
                timestamp,
                timestamp,
            ),
        )
    return len(entries)


def score_engineer_fit(title: str, text: str = "", url: str = "") -> float:
    haystack = " ".join([title, text, url]).lower()
    score = 0.0
    for keyword, weight in ENGINEER_KEYWORDS.items():
        if keyword in haystack:
            score += weight
    return min(score, 100.0)


def infer_graduate_year(title: str, text: str = "", url: str = "") -> int | None:
    haystack = " ".join([title, text, url])
    for pattern in (
        r"\b(20\d{2})\s*卒\b",
        r"\b(20\d{2})年卒\b",
        r"\b(20\d{2})\s*graduate\b",
        r"\b(\d{2})\s*卒\b",
    ):
        import re

        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        if len(value) == 4:
            return int(value)
        if len(value) == 2:
            year = int(value)
            if 20 <= year <= 39:
                return 2000 + year
    return None


def infer_job_track(title: str, text: str = "", url: str = "") -> str:
    haystack = " ".join([title, text, url]).lower()
    if any(hint.lower() in haystack for hint in INTERNSHIP_HINTS):
        return "internship"
    if any(hint.lower() in haystack for hint in MAIN_SELECTION_HINTS):
        return "main_selection"
    if any(hint.lower() in haystack for hint in EVENT_HINTS):
        return "event"
    return "unknown"


def normalize_job_track(employment_type: str | None, *, title: str = "", text: str = "", url: str = "") -> str:
    normalized = (employment_type or "").strip().lower()
    if normalized in JOB_TRACK_LABELS:
        return normalized
    if normalized in {"new grad", "graduate", "full time", "graduate recruitment"}:
        return "main_selection"
    if normalized in {"intern", "internship", "summer internship"}:
        return "internship"
    return infer_job_track(title, text, url)


def annotate_job_post(post: dict[str, Any]) -> dict[str, Any]:
    item = dict(post)
    track_kind = normalize_job_track(
        item.get("employment_type"),
        title=item.get("title") or "",
        text=item.get("summary") or "",
        url=item.get("url") or "",
    )
    graduate_year = item.get("graduate_year") or infer_graduate_year(
        item.get("title") or "",
        item.get("summary") or "",
        item.get("url") or "",
    )
    item["track_kind"] = track_kind
    item["track_label"] = JOB_TRACK_LABELS.get(track_kind, JOB_TRACK_LABELS["unknown"])
    item["graduate_year_resolved"] = graduate_year
    return item


def upsert_job_post(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    source_seed_url: str,
    title: str,
    url: str,
    employment_type: str | None = None,
    graduate_year: int | None = None,
    location: str | None = None,
    deadline: str | None = None,
    summary: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    status: str = "open",
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    company_id = ensure_company(connection, name=company_name, settings=settings)
    source_row = connection.execute(
        "SELECT id FROM job_sources WHERE seed_url = ?",
        (source_seed_url,),
    ).fetchone()
    source_id = int(source_row["id"]) if source_row else None
    payload = raw_payload or {}
    raw_blob = store_json_blob(payload, namespace="job_posts", settings=settings) if payload else None
    engineer_score = score_engineer_fit(title, summary or "", url)
    raw_hash = stable_hash(payload or {"title": title, "url": url})
    connection.execute(
        """
        INSERT INTO job_posts (
            company_id, source_id, title, url, employment_type, graduate_year,
            engineer_score, location, deadline, raw_hash, discovered_at, changed_at,
            status, summary, raw_payload_json, raw_blob_id, raw_storage_backend, raw_checksum, raw_size_bytes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title = excluded.title,
            employment_type = excluded.employment_type,
            graduate_year = excluded.graduate_year,
            engineer_score = excluded.engineer_score,
            location = excluded.location,
            deadline = excluded.deadline,
            raw_hash = excluded.raw_hash,
            changed_at = excluded.changed_at,
            status = excluded.status,
            summary = excluded.summary,
            raw_payload_json = excluded.raw_payload_json,
            raw_blob_id = COALESCE(excluded.raw_blob_id, job_posts.raw_blob_id),
            raw_storage_backend = COALESCE(excluded.raw_storage_backend, job_posts.raw_storage_backend),
            raw_checksum = COALESCE(excluded.raw_checksum, job_posts.raw_checksum),
            raw_size_bytes = COALESCE(excluded.raw_size_bytes, job_posts.raw_size_bytes)
        """,
        (
            company_id,
            source_id,
            title,
            url,
            employment_type,
            graduate_year,
            engineer_score,
            location,
            deadline,
            raw_hash,
            timestamp,
            timestamp,
            status,
            summary,
            None,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.storage_backend if raw_blob else None,
            raw_blob.checksum if raw_blob else None,
            raw_blob.size_bytes if raw_blob else None,
        ),
    )
    row = connection.execute("SELECT id FROM job_posts WHERE url = ?", (url,)).fetchone()
    return int(row["id"])


def list_sources(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = """
        SELECT js.*, c.name AS company_name
        FROM job_sources js
        LEFT JOIN companies c ON c.id = js.company_id
        ORDER BY c.name, js.source_name
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += "\nLIMIT ?\nOFFSET ?"
        params = (limit, offset)
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_recent_job_posts(
    connection: sqlite3.Connection,
    limit: int = 12,
    *,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        ORDER BY jp.discovered_at DESC
        LIMIT ?
        OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [annotate_job_post(dict(row)) for row in rows]


def list_all_job_posts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        ORDER BY jp.discovered_at DESC
        """
    ).fetchall()
    return [annotate_job_post(dict(row)) for row in rows]


def get_job_post(connection: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        WHERE jp.id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return None
    item = annotate_job_post(dict(row))
    if item.get("raw_blob_id"):
        item["raw_payload"] = load_json_blob(
            blob_id=item.get("raw_blob_id"),
            default={},
        )
    else:
        item["raw_payload"] = json_loads(item.get("raw_payload_json"), {})
    return item


def update_job_post_details(
    connection: sqlite3.Connection,
    job_id: int,
    *,
    employment_type: str | None = None,
    graduate_year: int | None = None,
    summary: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    raw_blob = store_json_blob(raw_payload, namespace="job_posts", settings=settings) if raw_payload is not None else None
    connection.execute(
        """
        UPDATE job_posts
        SET employment_type = COALESCE(?, employment_type),
            graduate_year = COALESCE(?, graduate_year),
            summary = COALESCE(?, summary),
            raw_payload_json = CASE WHEN ? IS NOT NULL THEN NULL ELSE raw_payload_json END,
            raw_blob_id = COALESCE(?, raw_blob_id),
            raw_storage_backend = COALESCE(?, raw_storage_backend),
            raw_checksum = COALESCE(?, raw_checksum),
            raw_size_bytes = COALESCE(?, raw_size_bytes),
            changed_at = ?
        WHERE id = ?
        """,
        (
            employment_type,
            graduate_year,
            summary,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.storage_backend if raw_blob else None,
            raw_blob.checksum if raw_blob else None,
            raw_blob.size_bytes if raw_blob else None,
            now_iso(settings.timezone),
            job_id,
        ),
    )
