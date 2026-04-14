from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.config import Settings, get_settings
from app.services.job_sources import infer_graduate_year, infer_job_track, score_engineer_fit, upsert_job_post
from app.utils import now_iso, stable_hash


DISCOVERY_HINTS = (
    "career",
    "careers",
    "job",
    "jobs",
    "recruit",
    "recruiting",
    "new grad",
    "graduate",
    "engineer",
    "developer",
    "backend",
    "frontend",
    "software",
    "platform",
    "sre",
    "data",
    "machine learning",
    "security",
    "エンジニア",
    "採用",
    "募集",
    "開発",
    "技術",
    "研究",
    "新卒",
)


@dataclass
class ScanResult:
    source_name: str
    seed_url: str
    discovered_posts: int
    status: str
    error: str | None = None


def _normalize_title(title: str, href: str) -> str:
    cleaned = " ".join(title.split())
    if cleaned:
        return cleaned[:200]
    slug = urlparse(href).path.rstrip("/").split("/")[-1]
    slug = slug.replace("-", " ").replace("_", " ").strip()
    if slug:
        return slug.title()[:200]
    return "Untitled job post"


def _looks_relevant(title: str, href: str) -> bool:
    parsed = urlparse(href)
    haystack = f"{title} {parsed.path} {parsed.query}".lower()
    return any(hint in haystack for hint in DISCOVERY_HINTS)


def _extract_deadline(text: str) -> str | None:
    text = " ".join(text.split())
    iso_match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if iso_match:
        return f"{iso_match.group(1)}-{int(iso_match.group(2)):02d}-{int(iso_match.group(3)):02d}"
    jp_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    if jp_match:
        return f"{jp_match.group(1)}-{int(jp_match.group(2)):02d}-{int(jp_match.group(3)):02d}"
    return None


def _fetch_html(url: str) -> str:
    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    return response.text


def _parse_candidates(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        absolute_url = urljoin(base_url, href)
        title = _normalize_title(anchor.get_text(" ", strip=True), absolute_url)
        surrounding_text = anchor.get_text(" ", strip=True)
        parent = anchor.parent.get_text(" ", strip=True) if anchor.parent else surrounding_text
        if not _looks_relevant(title, absolute_url):
            continue
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        parsed = urlparse(absolute_url)
        score = score_engineer_fit(title, parent, f"{parsed.path} {parsed.query}")
        if score <= 0:
            continue
        candidates.append(
            {
                "title": title,
                "url": absolute_url,
                "summary": parent[:500],
                "deadline": _extract_deadline(parent),
                "engineer_score": score,
                "raw_payload": {
                    "title": title,
                    "url": absolute_url,
                    "summary": parent[:500],
                    "discovered_from": base_url,
                },
            }
        )
    candidates.sort(key=lambda item: item["engineer_score"], reverse=True)
    return candidates


def scan_source(
    connection: sqlite3.Connection,
    *,
    source_row: sqlite3.Row,
    settings: Settings | None = None,
) -> ScanResult:
    settings = settings or get_settings()
    checked_at = now_iso(settings.timezone)
    try:
        html = _fetch_html(source_row["seed_url"])
        candidates = _parse_candidates(html, source_row["seed_url"])
        discovered = 0
        for candidate in candidates[:40]:
            upsert_job_post(
                connection,
                company_name=source_row["company_name"] or source_row["source_name"],
                source_seed_url=source_row["seed_url"],
                title=candidate["title"],
                url=candidate["url"],
                employment_type=infer_job_track(
                    candidate["title"],
                    candidate["summary"],
                    candidate["url"],
                ),
                graduate_year=infer_graduate_year(
                    candidate["title"],
                    candidate["summary"],
                    candidate["url"],
                ),
                deadline=candidate["deadline"],
                summary=candidate["summary"],
                raw_payload={
                    **candidate["raw_payload"],
                    "scanner_hash": stable_hash(candidate["raw_payload"]),
                },
                settings=settings,
            )
            discovered += 1
        connection.execute(
            """
            UPDATE job_sources
            SET last_checked_at = ?, last_error = NULL
            WHERE id = ?
            """,
            (checked_at, source_row["id"]),
        )
        return ScanResult(
            source_name=source_row["source_name"],
            seed_url=source_row["seed_url"],
            discovered_posts=discovered,
            status="ok",
        )
    except Exception as exc:
        connection.execute(
            """
            UPDATE job_sources
            SET last_checked_at = ?, last_error = ?
            WHERE id = ?
            """,
            (checked_at, str(exc), source_row["id"]),
        )
        return ScanResult(
            source_name=source_row["source_name"],
            seed_url=source_row["seed_url"],
            discovered_posts=0,
            status="error",
            error=str(exc),
        )


def scan_sources(
    connection: sqlite3.Connection,
    *,
    include_login_required: bool = False,
    settings: Settings | None = None,
) -> list[ScanResult]:
    settings = settings or get_settings()
    rows = connection.execute(
        """
        SELECT js.*, c.name AS company_name
        FROM job_sources js
        LEFT JOIN companies c ON c.id = js.company_id
        WHERE js.state = 'active'
          AND (? = 1 OR js.requires_login = 0)
        ORDER BY c.name, js.source_name
        """,
        (1 if include_login_required else 0,),
    ).fetchall()
    return [scan_source(connection, source_row=row, settings=settings) for row in rows]
