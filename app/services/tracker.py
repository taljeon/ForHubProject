from __future__ import annotations

import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.services.job_sources import ensure_company
from app.storage import load_text_blob, store_text_blob
from app.utils import json_dumps, json_loads, now_iso


QUESTION_TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("ガクチカ", ("成果", "学生時代", "力を入れた", "頑張った", "最も成果")),
    ("志望動機", ("志望動機", "なぜ", "入社", "この会社")),
    ("役割", ("役割", "立場", "担当")),
    ("背景", ("背景", "きっかけ", "理由")),
    ("改善", ("改善", "3倍", "施策", "どうすべき", "さらに")),
    ("逆質問", ("逆質問",)),
    ("自己紹介", ("自己紹介",)),
]

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
}

METADATA_FIELD_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("company_name", ("회사명", "기업명", "company", "企業名", "회사")),
    ("source_name", ("출처", "사이트", "source", "媒体", "サイト")),
    ("source_url", ("url", "링크", "source url", "출처 url", "ページURL")),
    ("screening_stage", ("전형 단계", "단계", "stage", "選考段階", "選考")),
    ("question_tags", ("질문 태그", "태그", "tags", "質問タグ")),
    ("summary_note", ("핵심 요약", "요약", "summary", "概要")),
    ("question_examples", ("질문", "질문 예시", "questions", "質問例")),
    ("prep_points", ("준비 포인트", "대비 포인트", "prep", "準備ポイント")),
    ("memo", ("메모", "memo", "備考")),
]


def _normalize_note_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("閉じる", " ")).strip()


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _find_first_url(value: str) -> str | None:
    match = re.search(r"https?://[^\s)>\"]+", value)
    return match.group(0) if match else None


def _infer_source_name_from_url(value: str | None) -> str | None:
    if not value:
        return None
    host = urlparse(value).netloc.lower()
    return SOURCE_NAME_BY_DOMAIN.get(host)


def _infer_stage_from_text(value: str) -> str | None:
    rules = [
        ("최종 면접", ("최종 면접", "最終面接")),
        ("2차 면접", ("2차 면접", "二次面接", "二次選考")),
        ("1차 면접", ("1차 면접", "一次面接", "一次選考")),
        ("코딩 테스트", ("코딩 테스트", "コーディングテスト", "coding test", "webテスト")),
        ("적성 검사", ("적성 검사", "適性検査", "SPI")),
        ("ES", ("엔트리 시트", "entry sheet", "エントリーシート", "\nES\n", " ES ")),
        ("인턴", ("인턴", "インターン")),
        ("본선고", ("본선고", "本選考")),
    ]
    for stage, keywords in rules:
        if any(keyword.lower() in value.lower() for keyword in keywords):
            return stage
    return None


def _extract_metadata_from_raw_text(raw_text: str) -> tuple[dict[str, str | None], str]:
    metadata: dict[str, str | None] = {
        "company_name": None,
        "source_name": None,
        "source_url": None,
        "screening_stage": None,
        "question_tags": None,
        "summary_note": None,
        "question_examples": None,
        "prep_points": None,
        "memo": None,
    }
    content_lines: list[str] = []
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            content_lines.append("")
            continue

        url = _find_first_url(stripped)
        if url and not metadata["source_url"]:
            metadata["source_url"] = url

        matched = False
        for field_name, labels in METADATA_FIELD_PATTERNS:
            label_pattern = "|".join(re.escape(label) for label in labels)
            metadata_match = re.match(
                rf"^(?:{label_pattern})\s*[:：]\s*(.+)$",
                stripped,
                flags=re.IGNORECASE,
            )
            if metadata_match:
                metadata[field_name] = metadata_match.group(1).strip() or None
                matched = True
                break
        if matched:
            continue

        content_lines.append(stripped)

    content_text = "\n".join(content_lines).strip()
    if not metadata["company_name"]:
        for candidate in content_lines:
            candidate = candidate.strip()
            if (
                candidate
                and len(candidate) <= 40
                and not candidate.startswith(("Q", "A"))
                and "http" not in candidate
                and ":" not in candidate
                and "：" not in candidate
            ):
                metadata["company_name"] = candidate
                break

    if not metadata["source_name"]:
        metadata["source_name"] = _infer_source_name_from_url(metadata["source_url"])

    if not metadata["screening_stage"]:
        metadata["screening_stage"] = _infer_stage_from_text(content_text)

    return metadata, content_text


def _normalize_section_body(value: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", value).strip()
    boilerplate_patterns = (
        r"この項目は\d+人の学生が参考になったと回答しています。",
        r"icon_good参考になった",
        r"icon_bad参考にならなかった",
        r"問題を報告する",
        r"目次",
    )
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_section_blocks(raw_text: str) -> list[dict[str, str]]:
    heading_pattern = re.compile(
        r"^(インターン概要|志望動機・インターンシップ参加前|選考フロー|エントリーシート|1次面接|最終面接|"
        r"インターンシップの形式と概要|インターンシップの内容|インターンシップを終えて|"
        r"面接で聞かれた質問と回答|インターンの具体的な流れ・手順|インターンで学んだこと|"
        r"参加前に準備しておくべきだったこと|参加後の社員や人事のフォローについて教えて下さい)$"
    )
    lines = raw_text.splitlines()
    sections: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title:
            body = _normalize_section_body("\n".join(current_lines))
            if body:
                sections.append({"title": current_title, "content": body})
        current_title = None
        current_lines = []

    for raw_line in lines:
        line = raw_line.strip()
        if heading_pattern.fullmatch(line):
            flush()
            current_title = line
            continue
        if current_title:
            current_lines.append(raw_line.rstrip())
    flush()
    return sections


def _extract_overview_fields(raw_text: str) -> dict[str, str]:
    labels = {
        "report_title": ("レポート",),
        "published_at": ("公開日",),
        "graduate_year": ("卒業年度",),
        "executed_at": ("実施年月",),
        "course": ("コース",),
        "job_title": ("職種名",),
        "period": ("期間",),
        "selection_flow": ("選考フロー",),
        "location": ("開催場所",),
        "participants": ("参加人数",),
        "compensation": ("報酬",),
    }
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    result: dict[str, str] = {}
    for index, line in enumerate(lines):
        for key, label_candidates in labels.items():
            if line in label_candidates and index + 1 < len(lines):
                next_line = lines[index + 1]
                if next_line not in labels:
                    result[key] = next_line
    if not result.get("report_title"):
        for line in lines[:3]:
            if "レポート" in line:
                result["report_title"] = line
                break
    return result


def _is_question_line(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if re.match(r"^Q[.．:：]?", line):
        return True
    if len(line) > 120:
        return False
    endings = ("ですか？", "ですか。", "ください。", "教えてください。", "ありますか？", "ありますか。", "どうですか？")
    return line.endswith(("?", "？")) or any(line.endswith(ending) for ending in endings)


def _extract_question_blocks(raw_text: str) -> list[dict[str, str]]:
    explicit_matches = list(
        re.finditer(
            r"Q[.．:：]?\s*(.*?)\s*A[.．:：]?\s*(.*?)(?=(?:\n\s*Q[.．:：]?)|\Z)",
            raw_text,
            flags=re.DOTALL,
        )
    )
    if explicit_matches:
        blocks: list[dict[str, str]] = []
        for match in explicit_matches:
            question = _normalize_note_text(match.group(1))
            answer = _normalize_note_text(match.group(2))
            if question and answer:
                blocks.append({"question": question, "answer": answer})
        return blocks

    lines = raw_text.splitlines()
    blocks = []
    current_question: str | None = None
    current_answer: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current_question and current_answer:
                current_answer.append("")
            continue
        if _is_question_line(line):
            if current_question:
                answer = _normalize_section_body("\n".join(current_answer))
                if answer:
                    blocks.append({"question": current_question, "answer": answer})
            current_question = re.sub(r"^Q[.．:：]?\s*", "", line).strip()
            current_answer = []
            continue
        if current_question:
            current_answer.append(line)
    if current_question:
        answer = _normalize_section_body("\n".join(current_answer))
        if answer:
            blocks.append({"question": current_question, "answer": answer})
    return blocks


def parse_interview_note_raw_text(raw_text: str) -> dict[str, str | None]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("閉じる", "")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    questions: list[str] = []
    summaries: list[str] = []
    combined_text_parts: list[str] = []

    for block in _extract_question_blocks(normalized):
        question = _normalize_note_text(block["question"])
        answer = _normalize_note_text(block["answer"])
        if not question or not answer:
            continue
        questions.append(question)
        combined_text_parts.extend([question, answer])
        summaries.append(f"- {question}: {_truncate_text(answer, 110)}")

    fallback_text = _normalize_note_text(normalized)
    combined_text = " ".join(combined_text_parts) if combined_text_parts else fallback_text

    tags: list[str] = []
    for tag, keywords in QUESTION_TAG_RULES:
        if any(keyword in combined_text for keyword in keywords):
            tags.append(tag)

    prep_points: list[str] = []
    if any(keyword in combined_text for keyword in ("成果", "実績", "売上", "達成", "数字")):
        prep_points.append("숫자 성과와 전후 비교를 한 문장으로 바로 말할 수 있게 준비")
    if any(keyword in combined_text for keyword in ("役割", "立場", "担当", "チーム")):
        prep_points.append("본인 역할과 팀 기여를 분리해서 설명")
    if any(keyword in combined_text for keyword in ("背景", "きっかけ", "理由")):
        prep_points.append("문제의식과 시작 배경을 먼저 정리")
    if any(keyword in combined_text for keyword in ("改善", "3倍", "施策", "次")):
        prep_points.append("개선안과 다음 액션을 연결해서 답변")
    if not prep_points:
        prep_points.append("질문 의도, 본인 기여, 결과를 1분 안에 말할 수 있게 정리")

    return {
        "question_tags": ", ".join(tags) or None,
        "summary_note": "\n".join(summaries[:3]) or _truncate_text(fallback_text, 240) or None,
        "question_examples": "\n".join(f"- {question}" for question in questions[:6]) or None,
        "prep_points": "\n".join(f"- {item}" for item in prep_points) or None,
    }


def build_interview_note_detail(
    *,
    raw_text: str | None,
    company_name: str | None,
    source_name: str | None,
    source_url: str | None,
    screening_stage: str | None,
    question_tags: str | None,
    summary_note: str | None,
    question_examples: str | None,
    prep_points: str | None,
    memo: str | None,
    checked_at: str | None,
) -> dict[str, Any]:
    if not raw_text or not raw_text.strip():
        return {
            "meta": {
                "company_name": company_name,
                "source_name": source_name,
                "source_url": source_url,
                "screening_stage": screening_stage,
                "checked_at": checked_at,
            },
            "overview": {},
            "qa_pairs": [],
            "sections": [],
            "summary_note": summary_note,
            "question_examples": question_examples,
            "prep_points": prep_points,
            "memo": memo,
        }

    metadata, content_text = _extract_metadata_from_raw_text(raw_text)
    full_text = content_text or raw_text
    return {
        "meta": {
            "company_name": company_name or metadata.get("company_name"),
            "source_name": source_name or metadata.get("source_name"),
            "source_url": source_url or metadata.get("source_url"),
            "screening_stage": screening_stage or metadata.get("screening_stage"),
            "checked_at": checked_at,
        },
        "overview": _extract_overview_fields(raw_text),
        "qa_pairs": _extract_question_blocks(full_text)[:16],
        "sections": _extract_section_blocks(full_text)[:16],
        "summary_note": summary_note,
        "question_examples": question_examples,
        "prep_points": prep_points,
        "memo": memo,
    }


def merge_interview_note_fields(
    *,
    raw_text: str | None,
    company_name: str | None,
    source_name: str | None,
    source_url: str | None,
    screening_stage: str | None,
    question_tags: str | None,
    summary_note: str | None,
    question_examples: str | None,
    prep_points: str | None,
    memo: str | None,
    prefer_parsed: bool = False,
) -> dict[str, str | None]:
    metadata, content_text = (
        _extract_metadata_from_raw_text(raw_text) if raw_text and raw_text.strip() else ({}, "")
    )
    parsed = parse_interview_note_raw_text(content_text) if content_text else {}
    if prefer_parsed and parsed:
        return {
            "company_name": metadata.get("company_name") or company_name,
            "source_name": metadata.get("source_name") or source_name or "수동 메모",
            "source_url": metadata.get("source_url") or source_url,
            "screening_stage": metadata.get("screening_stage") or screening_stage,
            "question_tags": parsed.get("question_tags") or question_tags,
            "summary_note": parsed.get("summary_note") or summary_note,
            "question_examples": parsed.get("question_examples") or question_examples,
            "prep_points": parsed.get("prep_points") or prep_points,
            "memo": memo,
        }
    return {
        "company_name": company_name or metadata.get("company_name") or "미분류",
        "source_name": source_name or metadata.get("source_name") or "수동 메모",
        "source_url": source_url or metadata.get("source_url"),
        "screening_stage": screening_stage or metadata.get("screening_stage"),
        "question_tags": question_tags or parsed.get("question_tags"),
        "summary_note": summary_note or parsed.get("summary_note"),
        "question_examples": question_examples or parsed.get("question_examples"),
        "prep_points": prep_points or parsed.get("prep_points"),
        "memo": memo,
    }


def create_application(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    route: str | None,
    contact_email: str | None,
    current_stage: str,
    next_action: str | None,
    deadline: str | None,
    my_priority: int,
    notes: str | None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    company_id = ensure_company(connection, name=company_name, settings=settings)
    connection.execute(
        """
        INSERT INTO applications (
            company_id, route, contact_email, current_stage, next_action,
            deadline, my_priority, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            route,
            contact_email,
            current_stage,
            next_action,
            deadline,
            my_priority,
            notes,
            timestamp,
            timestamp,
        ),
    )
    row = connection.execute("SELECT last_insert_rowid() AS id").fetchone()
    return int(row["id"])


def update_application(
    connection: sqlite3.Connection,
    application_id: int,
    *,
    current_stage: str,
    next_action: str | None,
    deadline: str | None,
    my_priority: int,
    notes: str | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    connection.execute(
        """
        UPDATE applications
        SET current_stage = ?, next_action = ?, deadline = ?, my_priority = ?,
            notes = COALESCE(?, notes), updated_at = ?
        WHERE id = ?
        """,
        (
            current_stage,
            next_action,
            deadline,
            my_priority,
            notes,
            now_iso(settings.timezone),
            application_id,
        ),
    )


def add_selection_event(
    connection: sqlite3.Connection,
    *,
    application_id: int,
    event_type: str,
    details: str | None,
    source: str | None = "manual",
    message_id: str | None = None,
    event_at: str | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    connection.execute(
        """
        INSERT INTO selection_events (
            application_id, event_type, event_at, details, source, message_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            event_type,
            event_at or timestamp,
            details,
            source,
            message_id,
            timestamp,
        ),
    )
    row = connection.execute("SELECT last_insert_rowid() AS id").fetchone()
    return int(row["id"])


def create_interview_note(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    source_name: str,
    source_url: str | None,
    screening_stage: str | None,
    question_tags: str | None,
    summary_note: str | None,
    question_examples: str | None,
    prep_points: str | None,
    memo: str | None,
    raw_text: str | None,
    detail_json: str | None,
    checked_at: str | None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    company_id = ensure_company(connection, name=company_name, settings=settings)
    raw_blob = store_text_blob(raw_text, namespace="interview_notes", settings=settings) if raw_text else None
    connection.execute(
        """
        INSERT INTO interview_notes (
            company_id, source_name, source_url, screening_stage, question_tags,
            summary_note, question_examples, prep_points, memo, raw_text,
            raw_blob_id, raw_storage_backend, raw_checksum, raw_size_bytes,
            detail_json, checked_at,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            source_name,
            source_url,
            screening_stage,
            question_tags,
            summary_note,
            question_examples,
            prep_points,
            memo,
            None,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.storage_backend if raw_blob else None,
            raw_blob.checksum if raw_blob else None,
            raw_blob.size_bytes if raw_blob else None,
            detail_json or "{}",
            checked_at,
            timestamp,
            timestamp,
        ),
    )
    row = connection.execute("SELECT last_insert_rowid() AS id").fetchone()
    return int(row["id"])


def update_interview_note(
    connection: sqlite3.Connection,
    note_id: int,
    *,
    company_name: str | None,
    source_name: str,
    source_url: str | None,
    screening_stage: str | None,
    question_tags: str | None,
    summary_note: str | None,
    question_examples: str | None,
    prep_points: str | None,
    memo: str | None,
    raw_text: str | None,
    detail_json: str | None,
    checked_at: str | None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    company_id = ensure_company(connection, name=company_name or "미분류", settings=settings)
    raw_blob = store_text_blob(raw_text, namespace="interview_notes", settings=settings) if raw_text else None
    connection.execute(
        """
        UPDATE interview_notes
        SET company_id = ?, source_name = ?, source_url = ?, screening_stage = ?, question_tags = ?,
            summary_note = ?, question_examples = ?, prep_points = ?, memo = ?,
            raw_text = CASE WHEN ? IS NOT NULL THEN NULL ELSE raw_text END,
            raw_blob_id = COALESCE(?, raw_blob_id),
            raw_storage_backend = COALESCE(?, raw_storage_backend),
            raw_checksum = COALESCE(?, raw_checksum),
            raw_size_bytes = COALESCE(?, raw_size_bytes),
            detail_json = ?, checked_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            company_id,
            source_name,
            source_url,
            screening_stage,
            question_tags,
            summary_note,
            question_examples,
            prep_points,
            memo,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.blob_id if raw_blob else None,
            raw_blob.storage_backend if raw_blob else None,
            raw_blob.checksum if raw_blob else None,
            raw_blob.size_bytes if raw_blob else None,
            detail_json or "{}",
            checked_at,
            now_iso(settings.timezone),
            note_id,
        ),
    )


def upsert_site_account(
    connection: sqlite3.Connection,
    *,
    company_or_platform: str,
    login_id: str | None,
    contact_email: str | None,
    vault_item_id: str | None,
    playwright_state_path: str | None,
    email_migrated: bool,
    notes: str | None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    connection.execute(
        """
        INSERT INTO site_accounts (
            company_or_platform, login_id, contact_email, vault_item_id,
            playwright_state_path, email_migrated, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_or_platform) DO UPDATE SET
            login_id = excluded.login_id,
            contact_email = excluded.contact_email,
            vault_item_id = excluded.vault_item_id,
            playwright_state_path = excluded.playwright_state_path,
            email_migrated = excluded.email_migrated,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            company_or_platform,
            login_id,
            contact_email,
            vault_item_id,
            playwright_state_path,
            1 if email_migrated else 0,
            notes,
            timestamp,
            timestamp,
        ),
    )
    row = connection.execute(
        "SELECT id FROM site_accounts WHERE company_or_platform = ?",
        (company_or_platform,),
    ).fetchone()
    return int(row["id"])


def parse_site_account_bulk_text(raw_text: str) -> list[dict[str, str | None]]:
    def looks_like_login_id(value: str) -> bool:
        if re.search(r"\d", value):
            return True
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{3,}", value))

    items: list[dict[str, str | None]] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        company = line
        login_id: str | None = None
        password_present = False

        if ":" in line or "：" in line:
            left, right = re.split(r"[:：]", line, maxsplit=1)
            company = left.strip()
            tokens = right.strip().split()
        else:
            tokens = line.split()
            if len(tokens) >= 3 and looks_like_login_id(tokens[-2]):
                company = " ".join(tokens[:-2]).strip()
                tokens = tokens[-2:]
            elif len(tokens) == 2 and looks_like_login_id(tokens[1]):
                company = tokens[0].strip()
                tokens = tokens[1:]
            else:
                company = " ".join(tokens).strip() or line
                tokens = []

        if tokens:
            login_id = tokens[0].strip() or None
        if len(tokens) >= 2:
            password_present = True

        items.append(
            {
                "company_or_platform": company,
                "login_id": login_id,
                "password_present": "yes" if password_present else "no",
            }
        )
    return items


def bulk_import_site_accounts(
    connection: sqlite3.Connection,
    *,
    raw_text: str,
    contact_email: str | None,
    settings: Settings | None = None,
) -> dict[str, int]:
    items = parse_site_account_bulk_text(raw_text)
    imported = 0
    with_login_id = 0
    password_ignored = 0

    for item in items:
        notes = "일괄 입력으로 등록됨"
        if item["password_present"] == "yes":
            notes += " / 비밀번호는 보안상 저장하지 않음"
            password_ignored += 1
        upsert_site_account(
            connection,
            company_or_platform=item["company_or_platform"] or "",
            login_id=item["login_id"],
            contact_email=contact_email,
            vault_item_id=None,
            playwright_state_path=None,
            email_migrated=False,
            notes=notes,
            settings=settings,
        )
        imported += 1
        if item["login_id"]:
            with_login_id += 1

    return {
        "imported": imported,
        "with_login_id": with_login_id,
        "password_ignored": password_ignored,
    }


def register_playwright_state(
    connection: sqlite3.Connection,
    *,
    site_account_id: int | None,
    state_path: str,
    browser_engine: str = "chromium",
    uses_indexed_db: bool = False,
    notes: str | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    timestamp = now_iso(settings.timezone)
    connection.execute(
        """
        INSERT INTO playwright_states (
            site_account_id, state_path, browser_engine,
            last_captured_at, last_verified_at, uses_indexed_db, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(state_path) DO UPDATE SET
            site_account_id = excluded.site_account_id,
            browser_engine = excluded.browser_engine,
            last_captured_at = excluded.last_captured_at,
            last_verified_at = excluded.last_verified_at,
            uses_indexed_db = excluded.uses_indexed_db,
            notes = excluded.notes
        """,
        (
            site_account_id,
            state_path,
            browser_engine,
            timestamp,
            timestamp,
            1 if uses_indexed_db else 0,
            notes,
        ),
    )
    row = connection.execute(
        "SELECT id FROM playwright_states WHERE state_path = ?",
        (state_path,),
    ).fetchone()
    return int(row["id"])


def list_applications(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = """
        SELECT a.*, c.name AS company_name
        FROM applications a
        LEFT JOIN companies c ON c.id = a.company_id
        ORDER BY a.my_priority ASC, a.deadline ASC, a.updated_at DESC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += "\nLIMIT ?\nOFFSET ?"
        params = (limit, offset)
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_recent_events(
    connection: sqlite3.Connection,
    limit: int = 12,
    *,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT se.*, c.name AS company_name
        FROM selection_events se
        JOIN applications a ON a.id = se.application_id
        LEFT JOIN companies c ON c.id = a.company_id
        ORDER BY se.event_at DESC
        LIMIT ?
        OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def list_interview_notes(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT note.*, c.name AS company_name
        FROM interview_notes note
        LEFT JOIN companies c ON c.id = note.company_id
        ORDER BY COALESCE(note.checked_at, note.updated_at) DESC, note.updated_at DESC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += "\nLIMIT ?\nOFFSET ?"
        params = (limit, offset)
    rows = connection.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["detail"] = json_loads(item.get("detail_json"), {})
    return items


def get_interview_note(
    connection: sqlite3.Connection,
    note_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT note.*, c.name AS company_name
        FROM interview_notes note
        LEFT JOIN companies c ON c.id = note.company_id
        WHERE note.id = ?
        """,
        (note_id,),
    ).fetchone()
    if not row:
        return None
    settings = settings or get_settings()
    item = dict(row)
    item["detail"] = json_loads(item.get("detail_json"), {})
    if item.get("raw_blob_id"):
        item["raw_text"] = load_text_blob(blob_id=item.get("raw_blob_id"), settings=settings)
    return item


def list_site_accounts(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = """
        SELECT sa.*,
               ps.last_verified_at AS state_last_verified_at,
               ps.uses_indexed_db AS state_uses_indexed_db
        FROM site_accounts sa
        LEFT JOIN playwright_states ps ON ps.site_account_id = sa.id
        ORDER BY sa.company_or_platform ASC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += "\nLIMIT ?\nOFFSET ?"
        params = (limit, offset)
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]
