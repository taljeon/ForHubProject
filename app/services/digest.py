from __future__ import annotations

import math
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.services.gmail_sync import list_recent_messages
from app.services.job_sources import list_all_job_posts, list_recent_job_posts, list_sources
from app.services.local_llm import summarize_dashboard_with_local_llm
from app.services.tracker import (
    list_applications,
    list_interview_notes,
    list_recent_events,
    list_site_accounts,
)
from app.utils import json_dumps, json_loads, now_iso, today_local


DASHBOARD_VIEWS: dict[str, dict[str, str]] = {
    "overview": {
        "label": "개요",
        "title": "오늘 한눈에",
        "description": "핵심 변화만 짧게 보고 필요한 섹션으로 들어갑니다.",
    },
    "mail": {
        "label": "메일",
        "title": "Gmail 수신함",
        "description": "최근 메일을 페이지 단위로 확인하고 수동 또는 자동 새로고침을 선택합니다.",
    },
    "jobs": {
        "label": "공고",
        "title": "채용 공고",
        "description": "최근 공고를 깔끔하게 나눠 보고, 오늘 변동과 마감 임박도 따로 봅니다.",
    },
    "applications": {
        "label": "지원",
        "title": "지원 현황",
        "description": "지원 단계와 다음 액션을 한곳에서 관리합니다.",
    },
    "notes": {
        "label": "후기 노트",
        "title": "면접 · 후기 노트",
        "description": "원문은 로컬에 두고, 구조화 요약과 준비 포인트를 함께 봅니다.",
    },
    "accounts": {
        "label": "계정",
        "title": "사이트 계정",
        "description": "로그인 ID, 연락 메일, Playwright 세션 상태를 정리합니다.",
    },
    "sources": {
        "label": "소스",
        "title": "공고 소스",
        "description": "추적 중인 기업 및 플랫폼 소스를 페이지 단위로 관리합니다.",
    },
}

PAGE_SIZES = {
    "mail": 5,
    "jobs": 5,
    "applications": 6,
    "notes": 6,
    "accounts": 8,
    "sources": 5,
}

JOB_VIEW_FILTERS = {
    "latest": "최신",
    "internship": "인턴",
    "main_selection": "본선고",
    "event": "설명회 / 이벤트",
}


def _build_metrics(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "tracked_sources": connection.execute("SELECT COUNT(*) AS count FROM job_sources").fetchone()["count"],
        "open_jobs": connection.execute(
            "SELECT COUNT(*) AS count FROM job_posts WHERE status = 'open'"
        ).fetchone()["count"],
        "tracked_applications": connection.execute(
            "SELECT COUNT(*) AS count FROM applications"
        ).fetchone()["count"],
        "cached_messages": connection.execute(
            "SELECT COUNT(*) AS count FROM mail_messages"
        ).fetchone()["count"],
    }


def _load_mail_accounts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ma.email, ma.is_authoritative, mss.last_history_id, mss.last_full_sync_at,
               mss.last_partial_sync_at, mss.last_error
        FROM mail_accounts ma
        LEFT JOIN mail_sync_state mss ON mss.mail_account_id = ma.id
        ORDER BY ma.is_authoritative DESC, ma.email ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _query_new_jobs(
    connection: sqlite3.Connection,
    *,
    today: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        WHERE substr(jp.discovered_at, 1, 10) = ?
        ORDER BY jp.discovered_at DESC
    """
    params: tuple[Any, ...] = (today,)
    if limit is not None:
        query += "\nLIMIT ?"
        params += (limit,)
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _query_changed_jobs(
    connection: sqlite3.Connection,
    *,
    today: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        WHERE substr(jp.changed_at, 1, 10) = ? AND jp.changed_at != jp.discovered_at
        ORDER BY jp.changed_at DESC
    """
    params: tuple[Any, ...] = (today,)
    if limit is not None:
        query += "\nLIMIT ?"
        params += (limit,)
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _query_deadlines(
    connection: sqlite3.Connection,
    *,
    today: str,
    horizon: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT jp.*, c.name AS company_name
        FROM job_posts jp
        LEFT JOIN companies c ON c.id = jp.company_id
        WHERE jp.status = 'open' AND jp.deadline IS NOT NULL
          AND jp.deadline BETWEEN ? AND ?
        ORDER BY jp.deadline ASC
        LIMIT ?
        """,
        (today, horizon, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _build_pagination(total_count: int, page: int, per_page: int) -> dict[str, int | bool]:
    total_pages = max(1, math.ceil(total_count / per_page)) if total_count else 1
    current_page = min(max(page, 1), total_pages)
    offset = (current_page - 1) * per_page
    return {
        "page": current_page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "offset": offset,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "prev_page": current_page - 1,
        "next_page": current_page + 1,
    }


def get_latest_digest_record(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT digest_date, markdown_path, summary_json, llm_summary_json, generated_at
        FROM daily_digests
        ORDER BY digest_date DESC, generated_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["summary"] = json_loads(item.get("summary_json"), {})
    item["llm_summary"] = json_loads(item.get("llm_summary_json"), {})
    return item


def _recent_applications_preview(connection: sqlite3.Connection, limit: int = 5) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT a.*, c.name AS company_name
        FROM applications a
        LEFT JOIN companies c ON c.id = a.company_id
        ORDER BY a.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _recent_interview_notes_preview(connection: sqlite3.Connection, limit: int = 5) -> list[dict[str, Any]]:
    return list_interview_notes(connection, limit=limit)


def _recent_resources_preview(connection: sqlite3.Connection, limit: int = 5) -> list[dict[str, Any]]:
    site_rows = connection.execute(
        """
        SELECT company_or_platform AS title,
               login_id AS subtitle,
               updated_at AS sort_at,
               '계정' AS kind
        FROM site_accounts
        """
    ).fetchall()
    source_rows = connection.execute(
        """
        SELECT COALESCE(c.name, js.source_name) AS title,
               js.source_name AS subtitle,
               COALESCE(js.last_checked_at, js.updated_at) AS sort_at,
               '소스' AS kind
        FROM job_sources js
        LEFT JOIN companies c ON c.id = js.company_id
        """
    ).fetchall()
    items = [dict(row) for row in site_rows] + [dict(row) for row in source_rows]
    items.sort(key=lambda item: item.get("sort_at") or "", reverse=True)
    return items[:limit]


def _filter_job_posts(
    posts: list[dict[str, Any]],
    *,
    job_kind: str,
    grad_year: int | None,
) -> list[dict[str, Any]]:
    filtered = posts
    if grad_year is not None:
        filtered = [post for post in filtered if post.get("graduate_year_resolved") == grad_year]
    if job_kind not in {"latest"}:
        filtered = [post for post in filtered if post.get("track_kind") == job_kind]
    return filtered


def build_dashboard_snapshot(
    connection: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    today_date = today_local(settings.timezone)
    today = today_date.isoformat()
    horizon = (today_date + timedelta(days=7)).isoformat()

    return {
        "metrics": _build_metrics(connection),
        "today": today,
        "new_jobs": _query_new_jobs(connection, today=today),
        "changed_jobs": _query_changed_jobs(connection, today=today),
        "deadlines": _query_deadlines(connection, today=today, horizon=horizon),
        "applications": list_applications(connection),
        "interview_notes": list_interview_notes(connection),
        "recent_events": list_recent_events(connection),
        "site_accounts": list_site_accounts(connection),
        "sources": list_sources(connection),
        "recent_posts": list_recent_job_posts(connection),
        "recent_messages": list_recent_messages(connection),
        "mail_accounts": _load_mail_accounts(connection),
        "digest_count": connection.execute(
            "SELECT COUNT(*) AS count FROM daily_digests"
        ).fetchone()["count"],
        "next_digest_time_hint": "07:30 / 20:30 JST",
    }


def build_dashboard_view(
    connection: sqlite3.Connection,
    settings: Settings | None = None,
    *,
    view: str = "overview",
    page: int = 1,
    auto_refresh_seconds: int = 0,
    job_kind: str = "latest",
    grad_year: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    view = view if view in DASHBOARD_VIEWS else "overview"
    today_date = today_local(settings.timezone)
    today = today_date.isoformat()
    horizon = (today_date + timedelta(days=7)).isoformat()
    metrics = _build_metrics(connection)
    mail_accounts = _load_mail_accounts(connection)
    job_kind = job_kind if job_kind in JOB_VIEW_FILTERS else "latest"
    resolved_grad_year = grad_year if grad_year and 2000 <= grad_year <= 2099 else 2028
    all_posts = list_all_job_posts(connection)
    filtered_posts = _filter_job_posts(all_posts, job_kind=job_kind, grad_year=resolved_grad_year)
    latest_posts = _filter_job_posts(all_posts, job_kind="latest", grad_year=resolved_grad_year)
    latest_new_jobs = [
        post for post in latest_posts if str(post.get("discovered_at") or "").startswith(today)
    ]
    latest_changed_jobs = [
        post
        for post in latest_posts
        if str(post.get("changed_at") or "").startswith(today)
        and post.get("changed_at") != post.get("discovered_at")
    ]
    latest_deadlines = [
        post
        for post in latest_posts
        if post.get("status") == "open"
        and post.get("deadline")
        and today <= str(post["deadline"]) <= horizon
    ]
    latest_deadlines.sort(key=lambda post: post.get("deadline") or "")

    view_counts = {
        "overview": None,
        "mail": metrics["cached_messages"],
        "jobs": connection.execute("SELECT COUNT(*) AS count FROM job_posts").fetchone()["count"],
        "applications": metrics["tracked_applications"],
        "notes": connection.execute("SELECT COUNT(*) AS count FROM interview_notes").fetchone()["count"],
        "accounts": connection.execute("SELECT COUNT(*) AS count FROM site_accounts").fetchone()["count"],
        "sources": metrics["tracked_sources"],
    }

    snapshot: dict[str, Any] = {
        "today": today,
        "metrics": metrics,
        "digest_count": connection.execute(
            "SELECT COUNT(*) AS count FROM daily_digests"
        ).fetchone()["count"],
        "latest_digest": get_latest_digest_record(connection),
        "next_digest_time_hint": "07:30 / 20:30 JST",
        "mail_accounts": mail_accounts,
        "view": view,
        "page": 1,
        "auto_refresh_seconds": auto_refresh_seconds if auto_refresh_seconds in {0, 30, 60} else 0,
        "job_kind": job_kind,
        "job_grad_year": resolved_grad_year,
        "view_meta": DASHBOARD_VIEWS[view],
        "views": [
            {
                "key": key,
                "label": meta["label"],
                "count": view_counts[key],
            }
            for key, meta in DASHBOARD_VIEWS.items()
        ],
        "highlights": {
            "new_jobs": latest_new_jobs[:5],
            "changed_jobs": latest_changed_jobs[:5],
            "deadlines": latest_deadlines[:5],
            "recent_events": list_recent_events(connection, limit=5),
        },
        "previews": {
            "messages": list_recent_messages(connection, limit=5),
            "posts": list_recent_job_posts(connection, limit=5),
            "applications": _recent_applications_preview(connection, limit=5),
            "notes": _recent_interview_notes_preview(connection, limit=5),
            "resources": _recent_resources_preview(connection, limit=5),
        },
        "job_digest_lists": {
            "internship": _filter_job_posts(all_posts, job_kind="internship", grad_year=resolved_grad_year)[:5],
            "main_selection": _filter_job_posts(all_posts, job_kind="main_selection", grad_year=resolved_grad_year)[:5],
            "event": _filter_job_posts(all_posts, job_kind="event", grad_year=resolved_grad_year)[:5],
        },
        "action_items": [item for item in list_applications(connection) if item.get("next_action")][:5],
        "job_filters": [
            {"key": key, "label": label}
            for key, label in JOB_VIEW_FILTERS.items()
        ],
        "job_filter_counts": {
            key: len(_filter_job_posts(all_posts, job_kind=key, grad_year=resolved_grad_year))
            for key in JOB_VIEW_FILTERS
        },
    }
    latest_digest = snapshot.get("latest_digest") or {}
    snapshot["llm_overview"] = latest_digest.get("llm_summary") or {}

    pagination: dict[str, int | bool] | None = None
    if view == "mail":
        pagination = _build_pagination(metrics["cached_messages"], page, PAGE_SIZES["mail"])
        snapshot["recent_messages"] = list_recent_messages(
            connection,
            limit=PAGE_SIZES["mail"],
            offset=int(pagination["offset"]),
        )
    elif view == "jobs":
        total_jobs = len(filtered_posts)
        pagination = _build_pagination(total_jobs, page, PAGE_SIZES["jobs"])
        offset = int(pagination["offset"])
        snapshot["recent_posts"] = filtered_posts[offset : offset + PAGE_SIZES["jobs"]]
    elif view == "applications":
        total_applications = view_counts["applications"] or 0
        pagination = _build_pagination(total_applications, page, PAGE_SIZES["applications"])
        snapshot["applications"] = list_applications(
            connection,
            limit=PAGE_SIZES["applications"],
            offset=int(pagination["offset"]),
        )
        snapshot["recent_events"] = list_recent_events(connection, limit=8)
    elif view == "notes":
        total_notes = view_counts["notes"] or 0
        pagination = _build_pagination(total_notes, page, PAGE_SIZES["notes"])
        snapshot["interview_notes"] = list_interview_notes(
            connection,
            limit=PAGE_SIZES["notes"],
            offset=int(pagination["offset"]),
        )
    elif view == "accounts":
        total_accounts = view_counts["accounts"] or 0
        pagination = _build_pagination(total_accounts, page, PAGE_SIZES["accounts"])
        snapshot["site_accounts"] = list_site_accounts(
            connection,
            limit=PAGE_SIZES["accounts"],
            offset=int(pagination["offset"]),
        )
    elif view == "sources":
        total_sources = view_counts["sources"] or 0
        pagination = _build_pagination(total_sources, page, PAGE_SIZES["sources"])
        snapshot["sources"] = list_sources(
            connection,
            limit=PAGE_SIZES["sources"],
            offset=int(pagination["offset"]),
        )

    if pagination:
        snapshot["pagination"] = pagination
        snapshot["page"] = int(pagination["page"])

    return snapshot


def render_digest_markdown(snapshot: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# 일일 요약 - {snapshot['today']}",
        "",
        "## 개요",
        f"- 추적 중인 소스: {snapshot['metrics']['tracked_sources']}",
        f"- 열려 있는 공고: {snapshot['metrics']['open_jobs']}",
        f"- 추적 중인 지원: {snapshot['metrics']['tracked_applications']}",
        f"- 캐시된 Gmail 메시지: {snapshot['metrics']['cached_messages']}",
        f"- 기준 졸업년도: {snapshot['job_grad_year']}졸",
        "",
    ]

    llm_overview = snapshot.get("llm_overview") or {}
    if llm_overview.get("headline"):
        lines.extend(["## 로컬 LLM 전체 브리프", llm_overview["headline"]])
        if llm_overview.get("top_actions"):
            lines.append("- 오늘 우선 액션")
            for item in llm_overview["top_actions"]:
                lines.append(f"  - {item}")
        if llm_overview.get("application_risks"):
            lines.append("- 지원 리스크")
            for item in llm_overview["application_risks"]:
                lines.append(f"  - {item}")
        if llm_overview.get("priority_companies"):
            lines.append("- 우선 회사")
            for item in llm_overview["priority_companies"]:
                lines.append(f"  - {item}")
        lines.append("")

    lines.extend([
        "## 28졸 공고 현황",
        f"- 최신: {snapshot['job_filter_counts']['latest']}",
        f"- 인턴: {snapshot['job_filter_counts']['internship']}",
        f"- 본선고: {snapshot['job_filter_counts']['main_selection']}",
        f"- 설명회 / 이벤트: {snapshot['job_filter_counts']['event']}",
        "",
        "## 최신 공고",
    ])

    if snapshot["highlights"]["new_jobs"]:
        lines.append("- 오늘 새 공고")
        for job in snapshot["highlights"]["new_jobs"]:
            lines.append(
                f"  - {job['company_name'] or '미확인'} | {job['title']} | {job['track_label']} | 점수 {job['engineer_score']:.0f}"
            )
    else:
        lines.append("- 오늘 새 공고: 없음")

    if snapshot["highlights"]["changed_jobs"]:
        lines.append("- 변경 공고")
        for job in snapshot["highlights"]["changed_jobs"]:
            lines.append(
                f"  - {job['company_name'] or '미확인'} | {job['title']} | 변경 {job['changed_at']}"
            )
    else:
        lines.append("- 변경 공고: 없음")

    if snapshot["highlights"]["deadlines"]:
        lines.append("- 마감 임박")
        for job in snapshot["highlights"]["deadlines"]:
            lines.append(
                f"  - {job['company_name'] or '미확인'} | {job['title']} | 마감 {job['deadline'] or '미정'}"
            )
    else:
        lines.append("- 마감 임박: 없음")

    lines.extend(["", "## 인턴 공고"])
    if snapshot["job_digest_lists"]["internship"]:
        for job in snapshot["job_digest_lists"]["internship"]:
            lines.append(
                f"- {job['company_name'] or '미확인'} | {job['title']} | 마감 {job['deadline'] or '미정'}"
            )
    else:
        lines.append("- 인턴 공고가 없습니다.")

    lines.extend(["", "## 본선고 공고"])
    if snapshot["job_digest_lists"]["main_selection"]:
        for job in snapshot["job_digest_lists"]["main_selection"]:
            lines.append(
                f"- {job['company_name'] or '미확인'} | {job['title']} | 마감 {job['deadline'] or '미정'}"
            )
    else:
        lines.append("- 본선고 공고가 없습니다.")

    lines.extend(["", "## 최근 메일"])
    if snapshot["previews"]["messages"]:
        for message in snapshot["previews"]["messages"]:
            lines.append(
                f"- {message['received_at'] or '-'} | {message['sender'] or '-'} | {message['subject'] or '(제목 없음)'}"
            )
    else:
        lines.append("- 최근 메일이 없습니다.")

    lines.extend(["", "## 지원 단계 변화"])
    if snapshot["highlights"]["recent_events"]:
        for event in snapshot["highlights"]["recent_events"]:
            lines.append(
                f"- {event['company_name'] or '미확인'} | {event['event_type']} | {event['event_at']} | {event['details'] or ''}".rstrip()
            )
    else:
        lines.append("- 최근 전형 이벤트가 없습니다.")

    lines.extend(["", "## 최근 후기 노트"])
    if snapshot["previews"]["notes"]:
        for note in snapshot["previews"]["notes"]:
            lines.append(
                f"- {note['company_name'] or '미확인'} | {note['source_name']} | {note['screening_stage'] or '-'} | 확인 {note['checked_at'] or '-'}"
            )
    else:
        lines.append("- 저장된 후기 노트가 없습니다.")

    lines.extend(["", "## 오늘 처리할 액션"])
    if snapshot["action_items"]:
        for application in snapshot["action_items"]:
            lines.append(
                f"- {application['company_name'] or '미확인'} | {application['current_stage']} | {application['next_action']} | 마감 {application['deadline'] or '미정'}"
            )
    else:
        lines.append("- 남아 있는 액션이 없습니다.")

    return "\n".join(lines) + "\n"


def build_digest(
    connection: sqlite3.Connection,
    settings: Settings | None = None,
    *,
    with_local_llm: bool = False,
) -> Path:
    settings = settings or get_settings()
    snapshot = build_dashboard_view(
        connection,
        settings,
        view="overview",
        job_kind="latest",
        grad_year=2028,
    )
    llm_summary: dict[str, Any] | None = None
    if with_local_llm:
        llm_summary = summarize_dashboard_with_local_llm(snapshot, settings)
        snapshot["llm_overview"] = llm_summary
    digest_date = snapshot["today"]
    settings.digest_dir.mkdir(parents=True, exist_ok=True)
    digest_path = settings.digest_dir / f"{digest_date}.md"
    digest_path.write_text(render_digest_markdown(snapshot), encoding="utf-8")
    generated_at = now_iso(settings.timezone)
    connection.execute(
        """
        INSERT INTO daily_digests (digest_date, markdown_path, summary_json, llm_summary_json, generated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(digest_date) DO UPDATE SET
            markdown_path = excluded.markdown_path,
            summary_json = excluded.summary_json,
            llm_summary_json = COALESCE(excluded.llm_summary_json, daily_digests.llm_summary_json),
            generated_at = excluded.generated_at
        """,
        (
            digest_date,
            str(digest_path),
            json_dumps(snapshot["metrics"]),
            json_dumps(llm_summary) if llm_summary else None,
            generated_at,
        ),
    )
    return digest_path
