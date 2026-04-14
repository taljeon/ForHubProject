from __future__ import annotations

import sqlite3

from app.config import Settings, get_settings
from app.services.job_sources import seed_registry, upsert_job_post
from app.services.tracker import (
    add_selection_event,
    build_interview_note_detail,
    create_interview_note,
    create_application,
    register_playwright_state,
    upsert_site_account,
)
from app.utils import json_dumps


def seed_demo_data(connection: sqlite3.Connection, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    seed_registry(connection, settings)

    upsert_job_post(
        connection,
        company_name="メルカリ",
        source_seed_url="https://careers.mercari.com/en/jobs/",
        title="Backend Software Engineer, 2028 Summer Internship",
        url="https://careers.mercari.com/en/jobs/backend-software-engineer-new-grad",
        employment_type="internship",
        graduate_year=2028,
        location="Tokyo",
        deadline="2026-04-20",
        summary="2028 summer internship for API platform and backend service development.",
        raw_payload={"source": "demo", "tags": ["backend", "python", "go"]},
    )
    upsert_job_post(
        connection,
        company_name="ソニーグループ",
        source_seed_url="https://www.sony.com/ja/SonyInfo/Jobs/",
        title="研究開発エンジニア",
        url="https://www.sony.com/ja/SonyInfo/Jobs/rd-engineer",
        employment_type="main_selection",
        graduate_year=2028,
        location="Tokyo",
        deadline="2026-04-12",
        summary="2028 new graduate main selection for R&D covering computer vision and embedded software.",
        raw_payload={"source": "demo", "tags": ["研究開発", "computer vision"]},
    )
    upsert_job_post(
        connection,
        company_name="LINEヤフー",
        source_seed_url="https://www.lycorp.co.jp/ja/recruit/newgrads/",
        title="Frontend Engineer 28卒 本選考",
        url="https://www.lycorp.co.jp/ja/recruit/newgrads/frontend-engineer",
        employment_type="main_selection",
        graduate_year=2028,
        location="Tokyo",
        deadline="2026-04-08",
        summary="28卒 main selection for web UI engineering on large-scale consumer products.",
        raw_payload={"source": "demo", "tags": ["frontend", "typescript"]},
    )

    existing_application = connection.execute(
        """
        SELECT a.id
        FROM applications a
        JOIN companies c ON c.id = a.company_id
        WHERE c.name = ? AND a.route = ?
        """,
        ("メルカリ", "ONE CAREER"),
    ).fetchone()
    if existing_application:
        application_id = int(existing_application["id"])
    else:
        application_id = create_application(
            connection,
            company_name="メルカリ",
            route="ONE CAREER",
            contact_email="demo@example.com",
            current_stage="엔트리 제출 완료",
            next_action="코딩 테스트 준비",
            deadline="2026-04-04",
            my_priority=1,
            notes="우선순위 높음. 백엔드 중심.",
            settings=settings,
        )

    existing_event = connection.execute(
        """
        SELECT id FROM selection_events
        WHERE application_id = ? AND event_type = ? AND details = ?
        """,
        (application_id, "엔트리 접수", "ONE CAREER 경유 엔트리 제출 완료."),
    ).fetchone()
    if not existing_event:
        add_selection_event(
            connection,
            application_id=application_id,
            event_type="엔트리 접수",
            details="ONE CAREER 경유 엔트리 제출 완료.",
            settings=settings,
        )

    site_account_id = upsert_site_account(
        connection,
        company_or_platform="ONE CAREER",
        login_id="demo@example.com",
        contact_email="demo@example.com",
        vault_item_id="kp://jobhunt/onecareer",
        playwright_state_path=str(settings.playwright_auth_dir / "onecareer.json"),
        email_migrated=True,
        notes="연락처 이메일을 새 Gmail로 이관 완료.",
        settings=settings,
    )
    register_playwright_state(
        connection,
        site_account_id=site_account_id,
        state_path=str(settings.playwright_auth_dir / "onecareer.json"),
        uses_indexed_db=True,
        notes="데모용 state placeholder. 실제 로그인 세션으로 교체 필요.",
        settings=settings,
    )

    existing_note = connection.execute(
        """
        SELECT note.id
        FROM interview_notes note
        JOIN companies c ON c.id = note.company_id
        WHERE c.name = ? AND note.source_name = ?
        """,
        ("メルカリ", "就活会議"),
    ).fetchone()
    if not existing_note:
        create_interview_note(
            connection,
            company_name="メルカリ",
            source_name="就活会議",
            source_url="https://syukatsu-kaigi.jp/companies/mercury/interview",
            screening_stage="1차 면접",
            question_tags="ガクチカ, 志望動機, 逆質問",
            summary_note="정량 성과와 본인 역할을 끝까지 파고드는 편. 답변 구조가 흐트러지면 바로 다시 묻는다.",
            question_examples="가장 성과를 낸 경험, 팀에서 맡은 역할, 성과를 3배로 늘리려면 무엇을 할지.",
            prep_points="숫자 근거, 배경, 본인 기여, 개선안까지 1분 안에 말할 수 있게 정리.",
            memo="원문 복사 대신 준비 포인트만 정리한 데모 노트.",
            raw_text=None,
            detail_json=json_dumps(
                build_interview_note_detail(
                    raw_text=None,
                    company_name="メルカリ",
                    source_name="就活会議",
                    source_url="https://syukatsu-kaigi.jp/companies/mercury/interview",
                    screening_stage="1차 면접",
                    question_tags="ガクチカ, 志望動機, 逆質問",
                    summary_note="정량 성과와 본인 역할을 끝까지 파고드는 편. 답변 구조가 흐트러지면 바로 다시 묻는다.",
                    question_examples="가장 성과를 낸 경험, 팀에서 맡은 역할, 성과를 3배로 늘리려면 무엇을 할지.",
                    prep_points="숫자 근거, 배경, 본인 기여, 개선안까지 1분 안에 말할 수 있게 정리.",
                    memo="원문 복사 대신 준비 포인트만 정리한 데모 노트.",
                    checked_at="2026-03-26",
                )
            ),
            checked_at="2026-03-26",
            settings=settings,
        )
