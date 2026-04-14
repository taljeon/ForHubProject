from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import db_session, init_db
from app.services.bootstrap import ensure_project_dirs
from app.services.digest import build_dashboard_view, build_digest, get_latest_digest_record
from app.services.gmail_sync import GmailConfigError, GmailSyncService
from app.services.job_sources import (
    get_job_post,
    import_job_post_from_url,
    seed_registry,
    update_job_post_details,
)
from app.services.local_llm import (
    LocalLLMUnavailableError,
    summarize_interview_note_with_local_llm,
    summarize_job_post_with_local_llm,
)
from app.services.sample_data import seed_demo_data
from app.services.tracker import (
    add_selection_event,
    build_interview_note_detail,
    bulk_import_site_accounts,
    create_interview_note,
    create_application,
    get_interview_note,
    merge_interview_note_fields,
    update_interview_note,
    update_application,
    upsert_site_account,
)
from app.utils import json_dumps, now_iso, today_local


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))


def _build_note_prefill_raw(
    *,
    company_name: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    screening_stage: str | None = None,
) -> str:
    lines: list[str] = []
    if company_name:
        lines.append(f"회사명: {company_name}")
    if source_name:
        lines.append(f"출처: {source_name}")
    if screening_stage:
        lines.append(f"전형 단계: {screening_stage}")
    if source_url:
        lines.append(f"URL: {source_url}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


@app.on_event("startup")
def startup() -> None:
    ensure_project_dirs(settings)
    with db_session(settings) as connection:
        init_db(connection)
        seed_registry(connection, settings)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    notice: str | None = None,
    view: str = Query("overview"),
    page: int = Query(1, ge=1),
    auto_refresh: int = Query(0),
    job_kind: str = Query("latest"),
    grad_year: int = Query(2028),
    note_company: str | None = Query(None),
    note_source_name: str | None = Query(None),
    note_source_url: str | None = Query(None),
    note_stage: str | None = Query(None),
) -> HTMLResponse:
    with db_session(settings) as connection:
        snapshot = build_dashboard_view(
            connection,
            settings,
            view=view,
            page=page,
            auto_refresh_seconds=auto_refresh,
            job_kind=job_kind,
            grad_year=grad_year,
        )
    note_prefill_raw = _build_note_prefill_raw(
        company_name=note_company,
        source_name=note_source_name,
        source_url=note_source_url,
        screening_stage=note_stage,
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "settings": settings,
            "snapshot": snapshot,
            "notice": notice,
            "note_prefill_raw": note_prefill_raw,
        },
    )


@app.get("/digests/latest", response_class=HTMLResponse)
def latest_digest_view() -> HTMLResponse:
    with db_session(settings) as connection:
        latest_digest = get_latest_digest_record(connection)

    if not latest_digest:
        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html lang="ko">
              <head><meta charset="utf-8"><title>최근 요약</title></head>
              <body style="font-family: sans-serif; padding: 24px;">
                <h1>최근 요약이 없습니다.</h1>
                <p>대시보드에서 요약 파일 만들기를 먼저 실행하세요.</p>
              </body>
            </html>
            """,
            status_code=404,
        )

    digest_path = Path(str(latest_digest["markdown_path"]))
    if not digest_path.exists():
        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html lang="ko">
              <head><meta charset="utf-8"><title>최근 요약</title></head>
              <body style="font-family: sans-serif; padding: 24px;">
                <h1>요약 파일을 찾을 수 없습니다.</h1>
                <p>{escape(str(digest_path))}</p>
              </body>
            </html>
            """,
            status_code=404,
        )

    content = escape(digest_path.read_text(encoding="utf-8"))
    generated_at = escape(str(latest_digest["generated_at"] or "-"))
    digest_date = escape(str(latest_digest["digest_date"] or "-"))
    title = f"최근 요약 - {digest_date}"
    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="ko">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{title}</title>
            <style>
              body {{
                margin: 0;
                padding: 28px;
                background: #f4f7fa;
                color: #18222d;
                font-family: "Pretendard", "Noto Sans KR", "Noto Sans JP", sans-serif;
              }}
              .sheet {{
                max-width: 920px;
                margin: 0 auto;
                padding: 24px;
                border: 1px solid #d7e0e8;
                border-radius: 20px;
                background: #fff;
                box-shadow: 0 18px 42px rgba(30, 46, 66, 0.08);
              }}
              h1 {{
                margin: 0 0 8px;
                font-size: 1.6rem;
              }}
              p {{
                margin: 0 0 18px;
                color: #637486;
              }}
              pre {{
                margin: 0;
                white-space: pre-wrap;
                word-break: break-word;
                line-height: 1.65;
                font-family: "SFMono-Regular", Menlo, monospace;
                font-size: 0.93rem;
              }}
            </style>
          </head>
          <body>
            <main class="sheet">
              <h1>{title}</h1>
              <p>생성 시각 {generated_at}</p>
              <pre>{content}</pre>
            </main>
          </body>
        </html>
        """
    )


@app.get("/interview-notes/{note_id}", response_class=HTMLResponse)
def interview_note_detail_view(note_id: int) -> HTMLResponse:
    with db_session(settings) as connection:
        note = get_interview_note(connection, note_id)

    if not note:
        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html lang="ko">
              <head><meta charset="utf-8"><title>후기 노트</title></head>
              <body style="font-family: sans-serif; padding: 24px;">
                <h1>후기 노트를 찾을 수 없습니다.</h1>
              </body>
            </html>
            """,
            status_code=404,
        )

    detail = note.get("detail") or {}
    meta = detail.get("meta") or {}
    overview = detail.get("overview") or {}
    qa_pairs = detail.get("qa_pairs") or []
    sections = detail.get("sections") or []
    llm = detail.get("llm") or {}
    raw_text = str(note.get("raw_text") or "").strip()

    def slugify(value: str) -> str:
        return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "section"

    overview_rows = "".join(
        f"<div class='detail-kv'><span>{escape(str(key))}</span><strong>{escape(str(value))}</strong></div>"
        for key, value in overview.items()
        if value
    )
    qa_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(item.get('question') or '-'))}</h3>"
            f"<p>{escape(str(item.get('answer') or '-'))}</p>"
            "</article>"
        )
        for item in qa_pairs
    )
    section_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(item.get('title') or '-'))}</h3>"
            f"<p>{escape(str(item.get('content') or '-'))}</p>"
            "</article>"
        )
        for item in sections
    )
    section_nav_html = "".join(
        f"<a class='anchor-link' href='#{slugify(str(item.get('title') or 'section'))}'>{escape(str(item.get('title') or '-'))}</a>"
        for item in sections
        if item.get("title")
    )
    section_panel_html = "".join(
        (
            f"<section class='panel' id='{slugify(str(item.get('title') or 'section'))}'>"
            f"<h2>{escape(str(item.get('title') or '-'))}</h2>"
            f"<article class='detail-block'><p>{escape(str(item.get('content') or '-'))}</p></article>"
            "</section>"
        )
        for item in sections
    )
    llm_detailed_summary = llm.get("detailed_summary") or []
    llm_evaluation_points = llm.get("evaluation_points") or []
    llm_question_insights = llm.get("question_insights") or []
    llm_section_summaries = llm.get("section_summaries") or []
    llm_meta_html = ""
    if llm.get("model") or llm.get("last_summarized_at"):
        llm_meta_html = (
            "<div class='meta-grid'>"
            f"<div class='detail-kv'><span>LLM 모델</span><strong>{escape(str(llm.get('model') or '-'))}</strong></div>"
            f"<div class='detail-kv'><span>재정리 시각</span><strong>{escape(str(llm.get('last_summarized_at') or '-'))}</strong></div>"
            "</div>"
        )
    llm_detailed_html = "".join(
        f"<li>{escape(str(item))}</li>" for item in llm_detailed_summary if str(item).strip()
    )
    llm_evaluation_html = "".join(
        f"<li>{escape(str(item))}</li>" for item in llm_evaluation_points if str(item).strip()
    )
    llm_question_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(item.get('question') or '-'))}</h3>"
            f"<p><strong>질문 의도</strong>\n{escape(str(item.get('intent') or '-'))}</p>"
            f"<p><strong>답변 포인트</strong>\n{escape(str(item.get('answer_point') or '-'))}</p>"
            "</article>"
        )
        for item in llm_question_insights
    )
    llm_section_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(item.get('section') or '-'))}</h3>"
            f"<p>{escape(str(item.get('summary') or '-'))}</p>"
            "</article>"
        )
        for item in llm_section_summaries
    )
    llm_panel_html = ""
    if any([llm_meta_html, llm_detailed_html, llm_evaluation_html, llm_question_html, llm_section_html]):
        llm_columns_parts: list[str] = []
        if llm_detailed_html:
            llm_columns_parts.append(
                f"<article class='detail-block'><h3>상세 요약</h3><ul>{llm_detailed_html}</ul></article>"
            )
        if llm_evaluation_html:
            llm_columns_parts.append(
                f"<article class='detail-block'><h3>평가 포인트</h3><ul>{llm_evaluation_html}</ul></article>"
            )
        llm_columns_html = (
            f"<div class='detail-columns'>{''.join(llm_columns_parts)}</div>"
            if llm_columns_parts
            else ""
        )
        llm_panel_html = f"""
        <section class="panel">
          <h2>LLM 상세 정리</h2>
          {llm_meta_html}
          {llm_columns_html}
          {"<div class='stacked-detail'><h3>질문별 해설</h3>" + llm_question_html + "</div>" if llm_question_html else ""}
          {"<div class='stacked-detail'><h3>파트별 요약</h3>" + llm_section_html + "</div>" if llm_section_html else ""}
        </section>
        """
    raw_text_html = (
        f"""
        <section class="panel">
          <h2>원문 전체</h2>
          <article class="detail-block">
            <p>{escape(raw_text)}</p>
          </article>
        </section>
        """
        if raw_text
        else ""
    )

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="ko">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{escape(str(note.get('company_name') or '후기 노트'))}</title>
            <style>
              body {{
                margin: 0;
                padding: 28px;
                background: #f4f7fa;
                color: #18222d;
                font-family: "Pretendard", "Noto Sans KR", "Noto Sans JP", sans-serif;
              }}
              .sheet {{
                max-width: 1080px;
                margin: 0 auto;
                display: grid;
                gap: 16px;
              }}
              .panel {{
                padding: 22px;
                border: 1px solid #d7e0e8;
                border-radius: 22px;
                background: #fff;
                box-shadow: 0 18px 42px rgba(30, 46, 66, 0.08);
              }}
              h1, h2, h3 {{
                margin: 0 0 10px;
              }}
              p {{
                margin: 0;
                color: #425466;
                line-height: 1.72;
                white-space: pre-line;
              }}
              .meta-grid, .overview-grid {{
                display: grid;
                gap: 10px;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
              }}
              .anchor-row, .detail-columns {{
                display: grid;
                gap: 10px;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
              }}
              .detail-kv {{
                padding: 12px 14px;
                border: 1px solid #d7e0e8;
                border-radius: 16px;
                background: #f7f9fc;
                display: grid;
                gap: 4px;
              }}
              .detail-kv span {{
                color: #637486;
                font-size: 0.84rem;
              }}
              .detail-block {{
                padding: 16px 18px;
                border: 1px solid #d7e0e8;
                border-radius: 18px;
                background: #f9fbfd;
                display: grid;
                gap: 8px;
              }}
              .detail-block ul {{
                margin: 0;
                padding-left: 18px;
                color: #425466;
                line-height: 1.7;
              }}
              .anchor-link {{
                display: inline-flex;
                align-items: center;
                width: fit-content;
                padding: 10px 14px;
                border-radius: 14px;
                border: 1px solid #d7e0e8;
                background: #f7f9fc;
                color: #224c60;
                text-decoration: none;
                font-weight: 700;
              }}
              .stacked-detail {{
                display: grid;
                gap: 12px;
                margin-top: 16px;
              }}
              .back {{
                display: inline-flex;
                width: fit-content;
                padding: 10px 14px;
                border-radius: 14px;
                background: #2f6c89;
                color: #fff;
                text-decoration: none;
                font-weight: 700;
              }}
            </style>
          </head>
          <body>
            <main class="sheet">
              <a class="back" href="/?view=notes">후기 노트로 돌아가기</a>
              <section class="panel">
                <h1>{escape(str(note.get('company_name') or '미확인'))}</h1>
                <div class="meta-grid">
                  <div class="detail-kv"><span>출처</span><strong>{escape(str(note.get('source_name') or '-'))}</strong></div>
                  <div class="detail-kv"><span>전형 단계</span><strong>{escape(str(note.get('screening_stage') or '-'))}</strong></div>
                  <div class="detail-kv"><span>확인일</span><strong>{escape(str(note.get('checked_at') or '-'))}</strong></div>
                  <div class="detail-kv"><span>질문 태그</span><strong>{escape(str(note.get('question_tags') or '-'))}</strong></div>
                </div>
              </section>
              <section class="panel">
                <h2>핵심 정리</h2>
                <div class="overview-grid">
                  <div class="detail-block"><h3>핵심 요약</h3><p>{escape(str(note.get('summary_note') or '-'))}</p></div>
                  <div class="detail-block"><h3>자주 나온 질문</h3><p>{escape(str(note.get('question_examples') or '-'))}</p></div>
                  <div class="detail-block"><h3>준비 포인트</h3><p>{escape(str(note.get('prep_points') or '-'))}</p></div>
                  <div class="detail-block"><h3>메모</h3><p>{escape(str(note.get('memo') or '-'))}</p></div>
                </div>
              </section>
              <section class="panel">
                <h2>개요 정보</h2>
                <div class="overview-grid">{overview_rows or "<p>추출된 개요 정보가 없습니다.</p>"}</div>
              </section>
              {llm_panel_html}
              <section class="panel">
                <h2>질문 · 답변 블록</h2>
                <div class="sheet">{qa_html or "<p>추출된 질문 블록이 없습니다.</p>"}</div>
              </section>
              <section class="panel">
                <h2>섹션별 내용</h2>
                <div class="sheet">{section_html or "<p>추출된 섹션이 없습니다.</p>"}</div>
              </section>
              {"<section class='panel'><h2>파트별 보기</h2><div class='anchor-row'>" + section_nav_html + "</div></section>" if section_nav_html else ""}
              {section_panel_html}
              {raw_text_html}
            </main>
          </body>
        </html>
        """
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_view(job_id: int, notice: str | None = None) -> HTMLResponse:
    with db_session(settings) as connection:
        post = get_job_post(connection, job_id)
        if not post:
            return HTMLResponse(
                """
                <!DOCTYPE html>
                <html lang="ko">
                  <head><meta charset="utf-8"><title>공고 상세</title></head>
                  <body style="font-family: sans-serif; padding: 24px;">
                    <h1>공고를 찾을 수 없습니다.</h1>
                  </body>
                </html>
                """,
                status_code=404,
            )
        related_notes = connection.execute(
            """
            SELECT note.id, note.source_name, note.screening_stage, note.checked_at, note.summary_note
            FROM interview_notes note
            WHERE note.company_id = ?
            ORDER BY COALESCE(note.checked_at, note.updated_at) DESC, note.updated_at DESC
            LIMIT 5
            """,
            (post.get("company_id"),),
        ).fetchall()

    raw_payload = post.get("raw_payload") or {}
    llm = raw_payload.get("llm") or {}
    sections = raw_payload.get("sections") or []
    body_text = str(raw_payload.get("body_text") or "").strip()
    source_name = str(raw_payload.get("source_name") or "수동 링크").strip()
    note_prefill_link = (
        "/?view=notes"
        f"&note_company={quote(str(post.get('company_name') or ''))}"
        f"&note_source_name={quote(source_name)}"
        f"&note_source_url={quote(str(post.get('url') or ''))}"
        f"&note_stage={quote(str(post.get('track_label') or ''))}"
    )

    section_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(section.get('title') or '-'))}</h3>"
            f"<p>{escape(str(section.get('content') or '-'))}</p>"
            "</article>"
        )
        for section in sections
        if isinstance(section, dict)
    )
    related_html = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(row['source_name'] or '-'))} · {escape(str(row['screening_stage'] or '-'))}</h3>"
            f"<p>{escape(str(row['summary_note'] or '요약 없음'))}</p>"
            f"<p><a class='inline-link' href='/interview-notes/{int(row['id'])}'>후기 노트 보기</a></p>"
            "</article>"
        )
        for row in related_notes
    )
    llm_lists = []
    for title, items in (
        ("핵심 포인트", llm.get("key_points") or []),
        ("요구 역량", llm.get("requirements") or []),
        ("전형 포인트", llm.get("selection_flow") or []),
        ("확인 포인트", llm.get("watch_points") or []),
        ("후기에서 볼 포인트", llm.get("related_note_focus") or []),
    ):
        if not items:
            continue
        bullets = "".join(f"<li>{escape(str(item))}</li>" for item in items if str(item).strip())
        if bullets:
            llm_lists.append(f"<article class='detail-block'><h3>{title}</h3><ul>{bullets}</ul></article>")
    llm_sections = "".join(
        (
            "<article class='detail-block'>"
            f"<h3>{escape(str(item.get('section') or '-'))}</h3>"
            f"<p>{escape(str(item.get('summary') or '-'))}</p>"
            "</article>"
        )
        for item in (llm.get("section_summaries") or [])
        if isinstance(item, dict)
    )
    notice_html = (
        f"<section class='notice'>{escape(notice)}</section>"
        if notice
        else ""
    )
    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="ko">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{escape(str(post.get('company_name') or '공고 상세'))}</title>
            <style>
              body {{
                margin: 0;
                padding: 28px;
                background: #f4f7fa;
                color: #18222d;
                font-family: "Pretendard", "Noto Sans KR", "Noto Sans JP", sans-serif;
              }}
              .sheet {{
                max-width: 1120px;
                margin: 0 auto;
                display: grid;
                gap: 16px;
              }}
              .panel {{
                padding: 22px;
                border: 1px solid #d7e0e8;
                border-radius: 22px;
                background: #fff;
                box-shadow: 0 18px 42px rgba(30, 46, 66, 0.08);
              }}
              .notice {{
                padding: 14px 16px;
                border: 1px solid #c7dfd0;
                border-radius: 16px;
                background: #eef7f1;
                color: #266046;
              }}
              .meta-grid, .detail-columns {{
                display: grid;
                gap: 10px;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
              }}
              .detail-kv, .detail-block {{
                padding: 16px 18px;
                border: 1px solid #d7e0e8;
                border-radius: 18px;
                background: #f9fbfd;
              }}
              .detail-kv {{
                display: grid;
                gap: 4px;
              }}
              .detail-kv span {{
                color: #637486;
                font-size: 0.84rem;
              }}
              .detail-block h3, h1, h2 {{
                margin: 0 0 10px;
              }}
              .detail-block p, p {{
                margin: 0;
                color: #425466;
                line-height: 1.72;
                white-space: pre-line;
              }}
              .detail-block ul {{
                margin: 0;
                padding-left: 18px;
                color: #425466;
                line-height: 1.7;
              }}
              .top-actions {{
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
              }}
              .back, button, .link-button {{
                display: inline-flex;
                width: fit-content;
                padding: 10px 14px;
                border: 0;
                border-radius: 14px;
                background: #2f6c89;
                color: #fff;
                text-decoration: none;
                font: inherit;
                font-weight: 700;
                cursor: pointer;
              }}
              .secondary {{
                background: #e6f0f5;
                color: #224c60;
              }}
              form {{
                margin: 0;
              }}
            </style>
          </head>
          <body>
            <main class="sheet">
              <a class="back" href="/?view=jobs">공고 목록으로 돌아가기</a>
              {notice_html}
              <section class="panel">
                <div class="top-actions">
                  <a class="link-button secondary" href="{escape(str(post.get('url') or '#'))}" target="_blank" rel="noreferrer">원문 열기</a>
                  <a class="link-button secondary" href="{escape(note_prefill_link)}">후기 노트로 보내기</a>
                  <form method="post" action="/jobs/{int(post['id'])}/summarize-local">
                    <button type="submit">MLX 공고 정리</button>
                  </form>
                </div>
                <h1>{escape(str(post.get('company_name') or '미확인'))}</h1>
                <p>{escape(str(post.get('title') or '-'))}</p>
              </section>
              <section class="panel">
                <h2>개요 정보</h2>
                <div class="meta-grid">
                  <div class="detail-kv"><span>전형 분류</span><strong>{escape(str(post.get('track_label') or '-'))}</strong></div>
                  <div class="detail-kv"><span>졸업년도</span><strong>{escape(str(post.get('graduate_year_resolved') or '-'))}</strong></div>
                  <div class="detail-kv"><span>근무지</span><strong>{escape(str(post.get('location') or '-'))}</strong></div>
                  <div class="detail-kv"><span>마감일</span><strong>{escape(str(post.get('deadline') or '-'))}</strong></div>
                  <div class="detail-kv"><span>출처</span><strong>{escape(source_name)}</strong></div>
                  <div class="detail-kv"><span>적합도</span><strong>{escape(f"{post.get('engineer_score') or 0:.0f}")}</strong></div>
                </div>
              </section>
              <section class="panel">
                <h2>핵심 요약</h2>
                <article class="detail-block">
                  <p>{escape(str(post.get('summary') or raw_payload.get('description') or '-'))}</p>
                </article>
              </section>
              {f"<section class='panel'><h2>LLM 정리</h2><div class='detail-columns'>{''.join(llm_lists)}</div>{'<div class=\"detail-columns\" style=\"margin-top: 12px;\">' + llm_sections + '</div>' if llm_sections else ''}</section>" if llm_lists or llm_sections else ""}
              <section class="panel">
                <h2>섹션별 내용</h2>
                <div class="detail-columns">{section_html or "<p>추출된 섹션이 없습니다.</p>"}</div>
              </section>
              <section class="panel">
                <h2>관련 후기 노트</h2>
                <div class="detail-columns">{related_html or "<p>연결된 후기 노트가 없습니다. 후기 노트로 보내기를 눌러 바로 추가할 수 있습니다.</p>"}</div>
              </section>
              <section class="panel">
                <h2>원문 전체</h2>
                <article class="detail-block">
                  <p>{escape(body_text or raw_payload.get('description') or '-')}</p>
                </article>
              </section>
            </main>
          </body>
        </html>
        """
    )


@app.post("/mail/sync")
def sync_mail_route(
    return_view: str = Form("mail"),
    return_page: int = Form(1),
    auto_refresh: int = Form(0),
) -> RedirectResponse:
    gmail_service = GmailSyncService(settings)
    try:
        with db_session(settings) as connection:
            result = gmail_service.incremental_sync(connection)
        notice = quote(
            f"메일 동기화를 완료했습니다. 처리 건수 {result.processed_messages}, history ID {result.last_history_id or '-'}"
        )
    except GmailConfigError as exc:
        notice = quote(f"메일 동기화에 실패했습니다: {exc}")
    refresh_value = auto_refresh if auto_refresh in {0, 30, 60} else 0
    target_page = return_page if return_page > 0 else 1
    return RedirectResponse(
        url=(
            f"/?view={quote(return_view)}&page={target_page}"
            f"&auto_refresh={refresh_value}&notice={notice}"
        ),
        status_code=303,
    )


@app.post("/jobs/import-url")
def import_job_url_route(
    job_url: str = Form(...),
    company_name: str = Form(""),
    source_name: str = Form(""),
) -> RedirectResponse:
    try:
        with db_session(settings) as connection:
            job_id = import_job_post_from_url(
                connection,
                url=job_url.strip(),
                company_name=company_name.strip() or None,
                source_name=source_name.strip() or None,
                settings=settings,
            )
    except Exception as exc:
        return RedirectResponse(
            url=f"/?view=jobs&notice={quote(f'공고 링크를 가져오지 못했습니다: {exc}')}",
            status_code=303,
        )
    return RedirectResponse(url=f"/jobs/{job_id}?notice={quote('공고를 저장했습니다.')}", status_code=303)


@app.post("/jobs/{job_id}/summarize-local")
def summarize_job_post_route(job_id: int) -> RedirectResponse:
    with db_session(settings) as connection:
        post = get_job_post(connection, job_id)
        if not post:
            return RedirectResponse(
                url=f"/?view=jobs&notice={quote('공고를 찾지 못했습니다.')}",
                status_code=303,
            )
        try:
            llm_summary = summarize_job_post_with_local_llm(post, settings)
        except LocalLLMUnavailableError as exc:
            return RedirectResponse(
                url=f"/jobs/{job_id}?notice={quote(str(exc))}",
                status_code=303,
            )
        except Exception as exc:
            return RedirectResponse(
                url=f"/jobs/{job_id}?notice={quote(f'로컬 공고 요약에 실패했습니다: {exc}')}",
                status_code=303,
            )

        raw_payload = post.get("raw_payload") or {}
        raw_payload["llm"] = {
            "model": llm_summary["model"],
            "last_summarized_at": now_iso(settings.timezone),
            "key_points": llm_summary.get("key_points"),
            "requirements": llm_summary.get("requirements"),
            "selection_flow": llm_summary.get("selection_flow"),
            "watch_points": llm_summary.get("watch_points"),
            "related_note_focus": llm_summary.get("related_note_focus"),
            "section_summaries": llm_summary.get("section_summaries"),
        }
        update_job_post_details(
            connection,
            job_id,
            employment_type=llm_summary.get("track_kind"),
            graduate_year=llm_summary.get("graduate_year"),
            summary=llm_summary.get("role_summary") or post.get("summary"),
            raw_payload=raw_payload,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/jobs/{job_id}?notice={quote('MLX 공고 정리를 반영했습니다.')}",
        status_code=303,
    )


@app.post("/applications")
def create_application_route(
    company_name: str = Form(...),
    route: str = Form(""),
    contact_email: str = Form(""),
    current_stage: str = Form("applied"),
    next_action: str = Form(""),
    deadline: str = Form(""),
    my_priority: int = Form(3),
    notes: str = Form(""),
    return_view: str = Form("applications"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        create_application(
            connection,
            company_name=company_name,
            route=route or None,
            contact_email=contact_email or None,
            current_stage=current_stage,
            next_action=next_action or None,
            deadline=deadline or None,
            my_priority=my_priority,
            notes=notes or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('지원 현황을 저장했습니다.')}",
        status_code=303,
    )


@app.post("/applications/{application_id}/update")
def update_application_route(
    application_id: int,
    current_stage: str = Form(...),
    next_action: str = Form(""),
    deadline: str = Form(""),
    my_priority: int = Form(3),
    notes: str = Form(""),
    return_view: str = Form("applications"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        update_application(
            connection,
            application_id,
            current_stage=current_stage,
            next_action=next_action or None,
            deadline=deadline or None,
            my_priority=my_priority,
            notes=notes or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('지원 단계 정보를 수정했습니다.')}",
        status_code=303,
    )


@app.post("/applications/{application_id}/events")
def add_event_route(
    application_id: int,
    event_type: str = Form(...),
    details: str = Form(""),
    return_view: str = Form("applications"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        add_selection_event(
            connection,
            application_id=application_id,
            event_type=event_type,
            details=details or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('전형 이벤트를 추가했습니다.')}",
        status_code=303,
    )


@app.post("/interview-notes")
def create_interview_note_route(
    company_name: str = Form(""),
    source_name: str = Form(""),
    source_url: str = Form(""),
    screening_stage: str = Form(""),
    raw_text: str = Form(""),
    question_tags: str = Form(""),
    summary_note: str = Form(""),
    question_examples: str = Form(""),
    prep_points: str = Form(""),
    memo: str = Form(""),
    checked_at: str = Form(""),
    return_view: str = Form("notes"),
) -> RedirectResponse:
    resolved_checked_at = checked_at or (
        today_local(settings.timezone).isoformat() if raw_text.strip() else ""
    )
    parsed_fields = merge_interview_note_fields(
        raw_text=raw_text or None,
        company_name=company_name or None,
        source_name=source_name or None,
        source_url=source_url or None,
        screening_stage=screening_stage or None,
        question_tags=question_tags or None,
        summary_note=summary_note or None,
        question_examples=question_examples or None,
        prep_points=prep_points or None,
        memo=memo or None,
        prefer_parsed=False,
    )
    detail_json = json_dumps(
        build_interview_note_detail(
            raw_text=raw_text or None,
            company_name=parsed_fields["company_name"],
            source_name=parsed_fields["source_name"],
            source_url=parsed_fields["source_url"],
            screening_stage=parsed_fields["screening_stage"],
            question_tags=parsed_fields["question_tags"],
            summary_note=parsed_fields["summary_note"],
            question_examples=parsed_fields["question_examples"],
            prep_points=parsed_fields["prep_points"],
            memo=parsed_fields["memo"],
            checked_at=resolved_checked_at or None,
        )
    )
    with db_session(settings) as connection:
        create_interview_note(
            connection,
            company_name=parsed_fields["company_name"] or "미분류",
            source_name=parsed_fields["source_name"] or "수동 메모",
            source_url=parsed_fields["source_url"],
            screening_stage=parsed_fields["screening_stage"],
            question_tags=parsed_fields["question_tags"],
            summary_note=parsed_fields["summary_note"],
            question_examples=parsed_fields["question_examples"],
            prep_points=parsed_fields["prep_points"],
            memo=parsed_fields["memo"],
            raw_text=raw_text or None,
            detail_json=detail_json,
            checked_at=resolved_checked_at or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('후기 노트를 저장했습니다.')}",
        status_code=303,
    )


@app.post("/interview-notes/{note_id}/update")
def update_interview_note_route(
    note_id: int,
    company_name: str = Form(""),
    source_name: str = Form(""),
    source_url: str = Form(""),
    screening_stage: str = Form(""),
    raw_text: str = Form(""),
    question_tags: str = Form(""),
    summary_note: str = Form(""),
    question_examples: str = Form(""),
    prep_points: str = Form(""),
    memo: str = Form(""),
    checked_at: str = Form(""),
    return_view: str = Form("notes"),
) -> RedirectResponse:
    parsed_fields = merge_interview_note_fields(
        raw_text=raw_text or None,
        company_name=company_name or None,
        source_name=source_name or None,
        source_url=source_url or None,
        screening_stage=screening_stage or None,
        question_tags=question_tags or None,
        summary_note=summary_note or None,
        question_examples=question_examples or None,
        prep_points=prep_points or None,
        memo=memo or None,
        prefer_parsed=bool(raw_text.strip()),
    )
    detail_json = json_dumps(
        build_interview_note_detail(
            raw_text=raw_text or None,
            company_name=parsed_fields["company_name"],
            source_name=parsed_fields["source_name"],
            source_url=parsed_fields["source_url"],
            screening_stage=parsed_fields["screening_stage"],
            question_tags=parsed_fields["question_tags"],
            summary_note=parsed_fields["summary_note"],
            question_examples=parsed_fields["question_examples"],
            prep_points=parsed_fields["prep_points"],
            memo=parsed_fields["memo"],
            checked_at=checked_at or None,
        )
    )
    with db_session(settings) as connection:
        update_interview_note(
            connection,
            note_id,
            company_name=parsed_fields["company_name"],
            source_name=parsed_fields["source_name"] or "수동 메모",
            source_url=parsed_fields["source_url"],
            screening_stage=parsed_fields["screening_stage"],
            question_tags=parsed_fields["question_tags"],
            summary_note=parsed_fields["summary_note"],
            question_examples=parsed_fields["question_examples"],
            prep_points=parsed_fields["prep_points"],
            memo=parsed_fields["memo"],
            raw_text=raw_text.strip() or None,
            detail_json=detail_json,
            checked_at=checked_at or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('후기 노트를 수정했습니다.')}",
        status_code=303,
    )


@app.post("/interview-notes/{note_id}/summarize-local")
def summarize_interview_note_route(
    note_id: int,
    return_view: str = Form("notes"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        note = get_interview_note(connection, note_id)
        if not note:
            return RedirectResponse(
                url=f"/?view={quote(return_view)}&notice={quote('후기 노트를 찾지 못했습니다.')}",
                status_code=303,
            )
        try:
            llm_summary = summarize_interview_note_with_local_llm(note, settings)
        except LocalLLMUnavailableError as exc:
            return RedirectResponse(
                url=f"/?view={quote(return_view)}&notice={quote(str(exc))}",
                status_code=303,
            )
        except Exception as exc:
            return RedirectResponse(
                url=f"/?view={quote(return_view)}&notice={quote(f'로컬 요약에 실패했습니다: {exc}')}",
                status_code=303,
            )

        detail = note.get("detail") or {}
        detail["llm"] = {
            "model": llm_summary["model"],
            "last_summarized_at": now_iso(settings.timezone),
            "evaluation_points": llm_summary.get("evaluation_points"),
            "detailed_summary": llm_summary.get("detailed_summary"),
            "question_insights": llm_summary.get("question_insights"),
            "section_summaries": llm_summary.get("section_summaries"),
        }
        update_interview_note(
            connection,
            note_id,
            company_name=note.get("company_name"),
            source_name=note.get("source_name") or "수동 메모",
            source_url=note.get("source_url"),
            screening_stage=llm_summary.get("screening_stage") or note.get("screening_stage"),
            question_tags=llm_summary.get("question_tags") or note.get("question_tags"),
            summary_note=llm_summary.get("summary_note") or note.get("summary_note"),
            question_examples=llm_summary.get("question_examples") or note.get("question_examples"),
            prep_points=llm_summary.get("prep_points") or note.get("prep_points"),
            memo=note.get("memo"),
            raw_text=None,
            detail_json=json_dumps(detail),
            checked_at=note.get("checked_at"),
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('MLX 로컬 요약을 반영했습니다.')}",
        status_code=303,
    )


@app.post("/site-accounts")
def upsert_site_account_route(
    company_or_platform: str = Form(...),
    login_id: str = Form(""),
    contact_email: str = Form(""),
    vault_item_id: str = Form(""),
    playwright_state_path: str = Form(""),
    email_migrated: str = Form("no"),
    notes: str = Form(""),
    return_view: str = Form("accounts"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        upsert_site_account(
            connection,
            company_or_platform=company_or_platform,
            login_id=login_id or None,
            contact_email=contact_email or None,
            vault_item_id=vault_item_id or None,
            playwright_state_path=playwright_state_path or None,
            email_migrated=email_migrated == "yes",
            notes=notes or None,
            settings=settings,
        )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote('사이트 계정 정보를 저장했습니다.')}",
        status_code=303,
    )


@app.post("/site-accounts/import")
def import_site_accounts_route(
    raw_text: str = Form(...),
    contact_email: str = Form(""),
    return_view: str = Form("accounts"),
) -> RedirectResponse:
    with db_session(settings) as connection:
        result = bulk_import_site_accounts(
            connection,
            raw_text=raw_text,
            contact_email=contact_email or None,
            settings=settings,
        )
    notice = (
        f"사이트 계정 {result['imported']}건을 일괄 등록했습니다. "
        f"로그인 ID 포함 {result['with_login_id']}건, "
        f"비밀번호 미저장 처리 {result['password_ignored']}건"
    )
    return RedirectResponse(
        url=f"/?view={quote(return_view)}&notice={quote(notice)}",
        status_code=303,
    )


@app.post("/seed-demo")
def seed_demo_route() -> RedirectResponse:
    with db_session(settings) as connection:
        seed_demo_data(connection, settings)
    return RedirectResponse(url=f"/?notice={quote('데모 데이터를 반영했습니다.')}", status_code=303)


@app.post("/digests/build")
def build_digest_route() -> RedirectResponse:
    with db_session(settings) as connection:
        digest_path = build_digest(connection, settings)
    return RedirectResponse(
        url=f"/?notice={quote(f'요약 파일을 생성했습니다: {digest_path.name}')}",
        status_code=303,
    )


@app.post("/digests/build-local")
def build_local_digest_route() -> RedirectResponse:
    try:
        with db_session(settings) as connection:
            digest_path = build_digest(connection, settings, with_local_llm=True)
    except LocalLLMUnavailableError as exc:
        notice = str(exc)
    except Exception as exc:
        notice = f"로컬 LLM 전체 정리에 실패했습니다: {exc}"
    else:
        notice = f"로컬 LLM 전체 브리프를 생성했습니다: {digest_path.name}"
    return RedirectResponse(
        url=f"/?notice={quote(notice)}",
        status_code=303,
    )
