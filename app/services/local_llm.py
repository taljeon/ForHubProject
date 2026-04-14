from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app.config import Settings, get_settings
class LocalLLMUnavailableError(RuntimeError):
    pass


def _stringify_list(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return None
        return "\n".join(f"- {item}" for item in items)
    text = str(value).strip()
    return text or None


def _stringify_tags(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        tags = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(tags) or None
    text = str(value).strip()
    return text or None


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_object_list(value: Any, *, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, str]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue
        normalized = {
            key: str(raw_item.get(key) or "").strip()
            for key in keys
            if str(raw_item.get(key) or "").strip()
        }
        if normalized:
            items.append(normalized)
    return items


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    return json.loads(match.group(0))


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def _build_note_context(note: dict[str, Any], settings: Settings) -> str:
    raw_text = str(note.get("raw_text") or "").strip()
    if raw_text:
        return _truncate(raw_text, settings.local_llm_prompt_max_chars)

    detail = note.get("detail") or {}
    parts: list[str] = []

    meta = detail.get("meta") or {}
    overview = detail.get("overview") or {}
    qa_pairs = detail.get("qa_pairs") or []
    sections = detail.get("sections") or []

    parts.append(f"회사명: {note.get('company_name') or meta.get('company_name') or '-'}")
    parts.append(f"출처: {note.get('source_name') or meta.get('source_name') or '-'}")
    parts.append(f"전형 단계: {note.get('screening_stage') or meta.get('screening_stage') or '-'}")
    parts.append(f"확인일: {note.get('checked_at') or meta.get('checked_at') or '-'}")
    if note.get("source_url") or meta.get("source_url"):
        parts.append(f"URL: {note.get('source_url') or meta.get('source_url')}")

    if overview:
        parts.append("\n[개요 정보]")
        for key, value in overview.items():
            if value:
                parts.append(f"{key}: {value}")

    if qa_pairs:
        parts.append("\n[질문 · 답변 블록]")
        for item in qa_pairs[:12]:
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if question:
                parts.append(f"Q. {question}")
            if answer:
                parts.append(f"A. {answer}")

    if sections:
        parts.append("\n[섹션별 내용]")
        for section in sections[:10]:
            title = str(section.get("title") or "").strip()
            content = str(section.get("content") or "").strip()
            if title:
                parts.append(f"## {title}")
            if content:
                parts.append(content)

    context = "\n".join(parts).strip()
    return _truncate(context, settings.local_llm_prompt_max_chars)


def _build_dashboard_context(snapshot: dict[str, Any], settings: Settings) -> str:
    parts: list[str] = [
        f"기준일: {snapshot.get('today')}",
        f"열린 공고: {snapshot.get('metrics', {}).get('open_jobs', 0)}",
        f"지원 현황: {snapshot.get('metrics', {}).get('tracked_applications', 0)}",
        f"저장된 메일: {snapshot.get('metrics', {}).get('cached_messages', 0)}",
        f"추적 소스: {snapshot.get('metrics', {}).get('tracked_sources', 0)}",
    ]

    highlights = snapshot.get("highlights") or {}
    previews = snapshot.get("previews") or {}
    action_items = snapshot.get("action_items") or []

    if highlights.get("new_jobs"):
        parts.append("\n[오늘 새 공고]")
        for item in highlights["new_jobs"][:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('title') or '-'} | {item.get('deadline') or '미정'}"
            )

    if highlights.get("changed_jobs"):
        parts.append("\n[변경 공고]")
        for item in highlights["changed_jobs"][:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('title') or '-'} | 변경 {item.get('changed_at') or '-'}"
            )

    if highlights.get("deadlines"):
        parts.append("\n[마감 임박]")
        for item in highlights["deadlines"][:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('title') or '-'} | 마감 {item.get('deadline') or '미정'}"
            )

    if previews.get("messages"):
        parts.append("\n[최근 메일]")
        for item in previews["messages"][:5]:
            parts.append(
                f"- {item.get('received_at') or '-'} | {item.get('sender') or '-'} | {item.get('subject') or '(제목 없음)'}"
            )

    if previews.get("applications"):
        parts.append("\n[최근 지원]")
        for item in previews["applications"][:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('current_stage') or '-'} | 다음 {item.get('next_action') or '-'} | 마감 {item.get('deadline') or '미정'}"
            )

    if previews.get("notes"):
        parts.append("\n[최근 후기 노트]")
        for item in previews["notes"][:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('source_name') or '-'} | {item.get('screening_stage') or '-'}"
            )

    if action_items:
        parts.append("\n[오늘 처리할 액션]")
        for item in action_items[:5]:
            parts.append(
                f"- {item.get('company_name') or '미확인'} | {item.get('current_stage') or '-'} | {item.get('next_action') or '-'}"
            )

    return _truncate("\n".join(parts).strip(), settings.local_llm_prompt_max_chars)


def _build_job_context(post: dict[str, Any], settings: Settings) -> str:
    raw_payload = post.get("raw_payload") or {}
    parts: list[str] = [
        f"회사명: {post.get('company_name') or '-'}",
        f"공고 제목: {post.get('title') or '-'}",
        f"전형 분류: {post.get('track_label') or post.get('employment_type') or '-'}",
        f"졸업년도: {post.get('graduate_year_resolved') or post.get('graduate_year') or '-'}",
        f"근무지: {post.get('location') or '-'}",
        f"마감일: {post.get('deadline') or '-'}",
        f"URL: {post.get('url') or raw_payload.get('source_url') or '-'}",
        f"요약: {post.get('summary') or raw_payload.get('description') or '-'}",
    ]

    body_text = str(raw_payload.get("body_text") or "").strip()
    if body_text:
        parts.append("\n[공고 본문]")
        parts.append(body_text)

    sections = raw_payload.get("sections") or []
    if isinstance(sections, list) and sections:
        parts.append("\n[섹션]")
        for section in sections[:10]:
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            content = str(section.get("content") or "").strip()
            if title:
                parts.append(f"## {title}")
            if content:
                parts.append(content)

    return _truncate("\n".join(parts).strip(), settings.local_llm_prompt_max_chars)


@lru_cache(maxsize=1)
def _load_mlx_model(model_name: str):
    try:
        from mlx_lm import load  # type: ignore
    except ModuleNotFoundError as exc:
        raise LocalLLMUnavailableError(
            "mlx-lm이 설치되지 않았습니다. scripts/install-mlx-gemma.sh를 먼저 실행하세요."
        ) from exc

    try:
        return load(model_name)
    except Exception as exc:  # pragma: no cover - runtime specific
        raise LocalLLMUnavailableError(
            f"로컬 모델을 불러오지 못했습니다: {model_name}"
        ) from exc


def summarize_interview_note_with_local_llm(
    note: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.local_llm_backend != "mlx":
        raise LocalLLMUnavailableError(
            f"지원하지 않는 로컬 LLM backend입니다: {settings.local_llm_backend}"
        )

    try:
        from mlx_lm import generate  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
    except ModuleNotFoundError as exc:
        raise LocalLLMUnavailableError(
            "mlx-lm이 설치되지 않았습니다. scripts/install-mlx-gemma.sh를 먼저 실행하세요."
        ) from exc

    model, tokenizer = _load_mlx_model(settings.local_llm_model)
    prompt_payload = _build_note_context(note, settings)
    system_prompt = (
        "You are a precise note-structuring assistant for Japanese recruiting reports. "
        "Return ONLY valid JSON. Do not include markdown fences or extra explanation. "
        "Use concise Korean for summaries. Preserve Japanese question text where useful."
    )
    user_prompt = f"""
다음 취업 후기 노트를 구조화해 주세요.

반드시 아래 JSON 형식만 반환:
{{
  "summary_note": "핵심 요약 3~6문장",
  "detailed_summary": ["상세 요약1", "상세 요약2"],
  "question_tags": ["태그1", "태그2"],
  "question_examples": ["질문1", "질문2", "질문3"],
  "prep_points": ["준비 포인트1", "준비 포인트2"],
  "evaluation_points": ["평가 포인트1", "평가 포인트2"],
  "question_insights": [
    {{
      "question": "질문 원문",
      "intent": "질문 의도",
      "answer_point": "답변 핵심 포인트"
    }}
  ],
  "section_summaries": [
    {{
      "section": "1차 면접",
      "summary": "섹션 핵심"
    }}
  ],
  "screening_stage": "가능하면 추정한 전형 단계"
}}

규칙:
- 핵심 요약은 한국어
- detailed_summary는 한국어 bullet 기준
- 질문 예시는 일본어 원문을 최대한 유지
- 준비 포인트는 면접 대비 관점으로 작성
- 평가 포인트는 면접관이 실제로 본 기준을 추정해 간단히 작성
- question_insights는 질문별 의도와 답변 초점을 붙여서 작성
- section_summaries는 긴 리포트를 섹션 단위로 빠르게 다시 볼 수 있게 작성
- 정보가 불충분하면 빈 문자열 또는 빈 배열 사용

입력 노트:
{prompt_payload}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    prompt = (
        tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        if getattr(tokenizer, "chat_template", None) is not None
        else f"{system_prompt}\n\n{user_prompt}"
    )
    sampler = make_sampler(temp=settings.local_llm_temperature)
    response_text = generate(
        model,
        tokenizer,
        prompt=prompt,
        verbose=False,
        sampler=sampler,
        max_tokens=settings.local_llm_max_tokens,
    )
    payload = _extract_json_object(str(response_text))

    return {
        "summary_note": str(payload.get("summary_note") or "").strip() or None,
        "detailed_summary": _normalize_text_list(payload.get("detailed_summary")),
        "question_tags": _stringify_tags(payload.get("question_tags")),
        "question_examples": _stringify_list(payload.get("question_examples")),
        "prep_points": _stringify_list(payload.get("prep_points")),
        "evaluation_points": _stringify_list(payload.get("evaluation_points")),
        "question_insights": _normalize_object_list(
            payload.get("question_insights"),
            keys=("question", "intent", "answer_point"),
        ),
        "section_summaries": _normalize_object_list(
            payload.get("section_summaries"),
            keys=("section", "summary"),
        ),
        "screening_stage": str(payload.get("screening_stage") or "").strip() or None,
        "model": settings.local_llm_model,
        "raw_response": str(response_text),
    }


def summarize_job_post_with_local_llm(
    post: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.local_llm_backend != "mlx":
        raise LocalLLMUnavailableError(
            f"지원하지 않는 로컬 LLM backend입니다: {settings.local_llm_backend}"
        )

    try:
        from mlx_lm import generate  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
    except ModuleNotFoundError as exc:
        raise LocalLLMUnavailableError(
            "mlx-lm이 설치되지 않았습니다. scripts/install-mlx-gemma.sh를 먼저 실행하세요."
        ) from exc

    model, tokenizer = _load_mlx_model(settings.local_llm_model)
    prompt_payload = _build_job_context(post, settings)
    system_prompt = (
        "You are a precise job-post structuring assistant for Japanese new-grad recruiting pages. "
        "Return ONLY valid JSON. Do not include markdown fences or extra explanation. "
        "Write concise Korean. Preserve Japanese role names where useful."
    )
    user_prompt = f"""
다음 채용 공고를 구조화해 주세요.

반드시 아래 JSON 형식만 반환:
{{
  "role_summary": "공고 핵심 요약 2~4문장",
  "key_points": ["핵심 포인트1", "핵심 포인트2"],
  "requirements": ["요구 역량1", "요구 역량2"],
  "selection_flow": ["전형 관련 포인트1", "전형 관련 포인트2"],
  "watch_points": ["지원 전에 확인할 점1", "확인할 점2"],
  "related_note_focus": ["후기 노트에서 보면 좋은 관점1", "관점2"],
  "section_summaries": [
    {{
      "section": "仕事内容",
      "summary": "섹션 핵심"
    }}
  ],
  "track_kind": "internship | main_selection | event | unknown",
  "graduate_year": 2028
}}

규칙:
- role_summary는 한국어 완성문
- requirements는 기술/자질 위주
- selection_flow는 선고 단계나 준비 포인트 위주
- related_note_focus는 면접/후기 노트를 어디에 연결해 보면 좋은지 작성
- track_kind는 반드시 internship, main_selection, event, unknown 중 하나
- 정보가 없으면 빈 배열 또는 null 사용

입력 공고:
{prompt_payload}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    prompt = (
        tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        if getattr(tokenizer, "chat_template", None) is not None
        else f"{system_prompt}\n\n{user_prompt}"
    )
    sampler = make_sampler(temp=settings.local_llm_temperature)
    response_text = generate(
        model,
        tokenizer,
        prompt=prompt,
        verbose=False,
        sampler=sampler,
        max_tokens=settings.local_llm_max_tokens,
    )
    payload = _extract_json_object(str(response_text))
    graduate_year_value = payload.get("graduate_year")
    graduate_year = None
    if isinstance(graduate_year_value, int):
        graduate_year = graduate_year_value
    elif isinstance(graduate_year_value, str) and graduate_year_value.strip().isdigit():
        graduate_year = int(graduate_year_value.strip())

    track_kind = str(payload.get("track_kind") or "").strip().lower() or None
    if track_kind not in {"internship", "main_selection", "event", "unknown", None}:
        track_kind = None

    return {
        "role_summary": str(payload.get("role_summary") or "").strip() or None,
        "key_points": _normalize_text_list(payload.get("key_points")),
        "requirements": _normalize_text_list(payload.get("requirements")),
        "selection_flow": _normalize_text_list(payload.get("selection_flow")),
        "watch_points": _normalize_text_list(payload.get("watch_points")),
        "related_note_focus": _normalize_text_list(payload.get("related_note_focus")),
        "section_summaries": _normalize_object_list(
            payload.get("section_summaries"),
            keys=("section", "summary"),
        ),
        "track_kind": track_kind,
        "graduate_year": graduate_year,
        "model": settings.local_llm_model,
        "raw_response": str(response_text),
    }


def summarize_dashboard_with_local_llm(
    snapshot: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.local_llm_backend != "mlx":
        raise LocalLLMUnavailableError(
            f"지원하지 않는 로컬 LLM backend입니다: {settings.local_llm_backend}"
        )

    try:
        from mlx_lm import generate  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
    except ModuleNotFoundError as exc:
        raise LocalLLMUnavailableError(
            "mlx-lm이 설치되지 않았습니다. scripts/install-mlx-gemma.sh를 먼저 실행하세요."
        ) from exc

    model, tokenizer = _load_mlx_model(settings.local_llm_model)
    prompt_payload = _build_dashboard_context(snapshot, settings)
    system_prompt = (
        "You are a precise operations assistant for a private recruiting dashboard. "
        "Return ONLY valid JSON. Do not add markdown fences or explanation. "
        "Write concise Korean. Keep output actionable."
    )
    user_prompt = f"""
다음 취업 대시보드 데이터를 전체 정리해 주세요.

반드시 아래 JSON 형식만 반환:
{{
  "headline": "전체 상황 요약 2~4문장",
  "top_actions": ["가장 중요한 액션1", "액션2", "액션3"],
  "mail_insights": ["메일 관점 핵심1", "메일 관점 핵심2"],
  "job_insights": ["공고 관점 핵심1", "공고 관점 핵심2"],
  "application_risks": ["지원 리스크1", "리스크2"],
  "note_insights": ["후기 노트 관점 핵심1", "핵심2"],
  "priority_companies": ["회사1", "회사2", "회사3"]
}}

규칙:
- headline은 한국어 완성문 2~4문장
- top_actions는 오늘 바로 처리할 일 우선
- application_risks는 놓치면 안 되는 마감/다음 액션/공백 위주
- priority_companies는 오늘 가장 신경 써야 할 회사 위주
- 정보가 부족하면 빈 배열 또는 빈 문자열 허용

입력 데이터:
{prompt_payload}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    prompt = (
        tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        if getattr(tokenizer, "chat_template", None) is not None
        else f"{system_prompt}\n\n{user_prompt}"
    )
    sampler = make_sampler(temp=settings.local_llm_temperature)
    response_text = generate(
        model,
        tokenizer,
        prompt=prompt,
        verbose=False,
        sampler=sampler,
        max_tokens=settings.local_llm_max_tokens,
    )
    payload = _extract_json_object(str(response_text))
    return {
        "headline": str(payload.get("headline") or "").strip() or None,
        "top_actions": _normalize_text_list(payload.get("top_actions")),
        "mail_insights": _normalize_text_list(payload.get("mail_insights")),
        "job_insights": _normalize_text_list(payload.get("job_insights")),
        "application_risks": _normalize_text_list(payload.get("application_risks")),
        "note_insights": _normalize_text_list(payload.get("note_insights")),
        "priority_companies": _normalize_text_list(payload.get("priority_companies")),
        "model": settings.local_llm_model,
        "raw_response": str(response_text),
    }
