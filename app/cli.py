from __future__ import annotations

import argparse

from app.config import get_settings
from app.db import db_session, init_db
from app.services.bootstrap import ensure_project_dirs
from app.services.digest import build_digest
from app.services.gmail_sync import GmailConfigError, GmailSyncService, list_recent_messages
from app.services.job_sources import seed_registry
from app.services.local_llm import LocalLLMUnavailableError, summarize_interview_note_with_local_llm
from app.services.sample_data import seed_demo_data
from app.services.source_scanner import scan_sources
from app.storage import migrate_raw_fields_to_blobs
from app.services.tracker import get_interview_note, update_interview_note
from app.utils import json_dumps, now_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forme JobHub local operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("seed-sources")
    subparsers.add_parser("seed-demo")
    subparsers.add_parser("build-digest")
    subparsers.add_parser("build-digest-local")
    migrate_parser = subparsers.add_parser("migrate-raw-to-blobs")
    migrate_parser.add_argument(
        "--keep-legacy-columns",
        action="store_true",
        help="Keep raw_text/raw_payload_json after migration.",
    )
    local_summary_parser = subparsers.add_parser("summarize-note-local")
    local_summary_parser.add_argument("--note-id", type=int, required=True)
    scan_parser = subparsers.add_parser("scan-sources")
    scan_parser.add_argument(
        "--include-login-required",
        action="store_true",
        help="Also scan sources marked as login-required.",
    )
    subparsers.add_parser("sync-gmail-full")
    subparsers.add_parser("sync-gmail-incremental")
    mail_parser = subparsers.add_parser("list-mail")
    mail_parser.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("show-config")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    ensure_project_dirs(settings)

    if args.command == "show-config":
        print(f"root_dir={settings.root_dir}")
        print(f"db_path={settings.db_path}")
        print(f"blob_backend={settings.blob_backend}")
        print(f"blob_dir={settings.blob_dir}")
        print(f"registry_path={settings.registry_path}")
        print(f"gmail_credentials_path={settings.gmail_credentials_path}")
        print(f"gmail_token_path={settings.gmail_token_path}")
        return

    with db_session(settings) as connection:
        init_db(connection)

        if args.command == "init-db":
            print(f"Initialized database at {settings.db_path}")
            return

        if args.command == "seed-sources":
            count = seed_registry(connection, settings)
            print(f"Seeded {count} job sources from {settings.registry_path}")
            return

        if args.command == "seed-demo":
            seed_demo_data(connection, settings)
            print("Inserted demo jobs, applications, and site account records")
            return

        if args.command == "migrate-raw-to-blobs":
            result = migrate_raw_fields_to_blobs(
                connection,
                settings=settings,
                clear_legacy_columns=not args.keep_legacy_columns,
            )
            print(
                "Migrated raw fields to blobs: "
                f"interview_notes={result['interview_notes']}, job_posts={result['job_posts']}"
            )
            return

        if args.command == "build-digest":
            digest_path = build_digest(connection, settings)
            print(f"Generated digest: {digest_path}")
            return

        if args.command == "build-digest-local":
            try:
                digest_path = build_digest(connection, settings, with_local_llm=True)
            except LocalLLMUnavailableError as exc:
                raise SystemExit(str(exc)) from exc
            except Exception as exc:
                raise SystemExit(f"로컬 LLM 전체 정리에 실패했습니다: {exc}") from exc
            print(f"Generated local LLM digest: {digest_path}")
            return

        if args.command == "summarize-note-local":
            note = get_interview_note(connection, args.note_id)
            if not note:
                raise SystemExit(f"Interview note not found: {args.note_id}")
            try:
                llm_summary = summarize_interview_note_with_local_llm(note, settings)
            except LocalLLMUnavailableError as exc:
                raise SystemExit(str(exc)) from exc
            except Exception as exc:
                raise SystemExit(f"로컬 요약에 실패했습니다: {exc}") from exc

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
                args.note_id,
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
            print(f"Updated interview note {args.note_id} with {llm_summary['model']}")
            return

        if args.command == "scan-sources":
            results = scan_sources(
                connection,
                include_login_required=args.include_login_required,
                settings=settings,
            )
            for result in results:
                status = result.status
                error = f" error={result.error}" if result.error else ""
                print(
                    f"{result.source_name} [{status}] discovered={result.discovered_posts}"
                    f" url={result.seed_url}{error}"
                )
            return

        if args.command == "list-mail":
            messages = list_recent_messages(connection, limit=args.limit)
            if not messages:
                print("No cached mail messages yet.")
                return
            for message in messages:
                print(
                    f"{message['received_at'] or '-'} | "
                    f"{message['account_email'] or '-'} | "
                    f"{message['sender'] or '-'} | "
                    f"{message['subject'] or '(no subject)'}"
                )
            return

        gmail_service = GmailSyncService(settings)
        try:
            if args.command == "sync-gmail-full":
                result = gmail_service.full_sync(connection)
            else:
                result = gmail_service.incremental_sync(connection)
        except GmailConfigError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            f"{result.mode} sync complete for {result.account_email}: "
            f"{result.processed_messages} messages, history_id={result.last_history_id}"
        )


if __name__ == "__main__":
    main()
