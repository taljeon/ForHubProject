from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.utils import json_dumps, now_iso


class GmailConfigError(RuntimeError):
    pass


@dataclass
class SyncResult:
    account_email: str
    processed_messages: int
    last_history_id: str | None
    mode: str


class GmailSyncService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _build_client(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GmailConfigError(
                "Google API dependencies are missing. Run `pip install -e .` first."
            ) from exc

        creds = None
        if self.settings.gmail_token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.settings.gmail_token_path),
                self.settings.gmail_scopes,
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.settings.gmail_credentials_path.exists():
                    raise GmailConfigError(
                        f"Desktop OAuth credentials not found at {self.settings.gmail_credentials_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.settings.gmail_credentials_path),
                    self.settings.gmail_scopes,
                )
                creds = flow.run_local_server(port=0)
            self.settings.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _ensure_mail_account(self, connection: sqlite3.Connection, account_email: str) -> int:
        timestamp = now_iso(self.settings.timezone)
        connection.execute(
            """
            INSERT INTO mail_accounts (email, display_name, status, is_authoritative, created_at, updated_at)
            VALUES (?, ?, 'active', 1, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                is_authoritative = 1,
                updated_at = excluded.updated_at
            """,
            (account_email, account_email, timestamp, timestamp),
        )
        row = connection.execute("SELECT id FROM mail_accounts WHERE email = ?", (account_email,)).fetchone()
        return int(row["id"])

    def _upsert_sync_state(
        self,
        connection: sqlite3.Connection,
        mail_account_id: int,
        *,
        sync_mode: str,
        last_history_id: str | None,
        last_full_sync_at: str | None = None,
        last_partial_sync_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO mail_sync_state (
                mail_account_id, sync_mode, last_history_id, last_full_sync_at, last_partial_sync_at, last_error
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mail_account_id) DO UPDATE SET
                sync_mode = excluded.sync_mode,
                last_history_id = COALESCE(excluded.last_history_id, mail_sync_state.last_history_id),
                last_full_sync_at = COALESCE(excluded.last_full_sync_at, mail_sync_state.last_full_sync_at),
                last_partial_sync_at = COALESCE(excluded.last_partial_sync_at, mail_sync_state.last_partial_sync_at),
                last_error = excluded.last_error
            """,
            (
                mail_account_id,
                sync_mode,
                last_history_id,
                last_full_sync_at,
                last_partial_sync_at,
                last_error,
            ),
        )

    def _extract_header(self, payload: dict[str, Any], target_name: str) -> str | None:
        headers = payload.get("headers", [])
        for header in headers:
            if header.get("name", "").lower() == target_name.lower():
                return header.get("value")
        return None

    def _raise_helpful_http_error(self, exc: Exception) -> None:
        status = getattr(getattr(exc, "resp", None), "status", None)
        message = str(exc)
        if status == 403 and (
            "accessNotConfigured" in message or "has not been used in project" in message
        ):
            project_match = re.search(r"project(?:=| )(\d{6,})", message)
            project_hint = (
                f" 프로젝트 번호 {project_match.group(1)}"
                if project_match
                else ""
            )
            raise GmailConfigError(
                "Gmail API가 OAuth 클라이언트를 만든 같은 프로젝트에서 아직 활성화되지 않았습니다."
                f"{project_hint}에서 Gmail API를 Enable한 뒤 2~5분 기다리고 다시 실행하세요."
            ) from exc
        raise exc

    def _persist_message(
        self,
        connection: sqlite3.Connection,
        *,
        mail_account_id: int,
        message: dict[str, Any],
    ) -> None:
        payload = message.get("payload", {})
        internal_date = message.get("internalDate")
        received_at = None
        if internal_date:
            received_at = datetime.fromtimestamp(
                int(internal_date) / 1000,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
        timestamp = now_iso(self.settings.timezone)
        connection.execute(
            """
            INSERT INTO mail_messages (
                mail_account_id, gmail_message_id, thread_id, history_id, internal_ts,
                subject, sender, recipient, snippet, labels_json, payload_json,
                received_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gmail_message_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                history_id = excluded.history_id,
                internal_ts = excluded.internal_ts,
                subject = excluded.subject,
                sender = excluded.sender,
                recipient = excluded.recipient,
                snippet = excluded.snippet,
                labels_json = excluded.labels_json,
                payload_json = excluded.payload_json,
                received_at = excluded.received_at,
                updated_at = excluded.updated_at
            """,
            (
                mail_account_id,
                message["id"],
                message.get("threadId"),
                message.get("historyId"),
                internal_date,
                self._extract_header(payload, "Subject"),
                self._extract_header(payload, "From"),
                self._extract_header(payload, "To"),
                message.get("snippet"),
                json_dumps(message.get("labelIds", [])),
                json_dumps(message),
                received_at,
                timestamp,
                timestamp,
            ),
        )

    def full_sync(self, connection: sqlite3.Connection, max_results: int = 100) -> SyncResult:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GmailConfigError(
                "Google API dependencies are missing. Run `pip install -e .` first."
            ) from exc

        service = self._build_client()
        try:
            profile = service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            self._raise_helpful_http_error(exc)
        account_email = profile["emailAddress"]
        mail_account_id = self._ensure_mail_account(connection, account_email)

        page_token = None
        processed = 0
        newest_history_id: str | None = None
        try:
            while processed < max_results:
                response = (
                    service.users()
                    .messages()
                    .list(userId="me", maxResults=min(50, max_results - processed), pageToken=page_token)
                    .execute()
                )
                for item in response.get("messages", []):
                    message = (
                        service.users().messages().get(userId="me", id=item["id"], format="full").execute()
                    )
                    self._persist_message(connection, mail_account_id=mail_account_id, message=message)
                    newest_history_id = message.get("historyId", newest_history_id)
                    processed += 1
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as exc:
            self._raise_helpful_http_error(exc)

        timestamp = now_iso(self.settings.timezone)
        self._upsert_sync_state(
            connection,
            mail_account_id,
            sync_mode="full",
            last_history_id=newest_history_id,
            last_full_sync_at=timestamp,
            last_error=None,
        )
        return SyncResult(
            account_email=account_email,
            processed_messages=processed,
            last_history_id=newest_history_id,
            mode="full",
        )

    def incremental_sync(self, connection: sqlite3.Connection) -> SyncResult:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GmailConfigError(
                "Google API dependencies are missing. Run `pip install -e .` first."
            ) from exc

        service = self._build_client()
        try:
            profile = service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            self._raise_helpful_http_error(exc)
        account_email = profile["emailAddress"]
        mail_account_id = self._ensure_mail_account(connection, account_email)
        state = connection.execute(
            "SELECT last_history_id FROM mail_sync_state WHERE mail_account_id = ?",
            (mail_account_id,),
        ).fetchone()
        if not state or not state["last_history_id"]:
            raise GmailConfigError("No stored history ID. Run full sync first.")

        processed = 0
        newest_history_id = state["last_history_id"]
        page_token = None

        try:
            while True:
                response = (
                    service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=state["last_history_id"],
                        historyTypes=["messageAdded"],
                        pageToken=page_token,
                    )
                    .execute()
                )
                for entry in response.get("history", []):
                    newest_history_id = entry.get("id", newest_history_id)
                    for added in entry.get("messagesAdded", []):
                        message_id = added["message"]["id"]
                        message = (
                            service.users()
                            .messages()
                            .get(userId="me", id=message_id, format="full")
                            .execute()
                        )
                        self._persist_message(connection, mail_account_id=mail_account_id, message=message)
                        processed += 1
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 404:
                self._upsert_sync_state(
                    connection,
                    mail_account_id,
                    sync_mode="needs_full_resync",
                    last_history_id=state["last_history_id"],
                    last_error="Stored history ID expired. Run full sync again.",
                )
                raise GmailConfigError("Stored history ID expired. Run full sync again.") from exc
            self._raise_helpful_http_error(exc)

        timestamp = now_iso(self.settings.timezone)
        self._upsert_sync_state(
            connection,
            mail_account_id,
            sync_mode="partial",
            last_history_id=newest_history_id,
            last_partial_sync_at=timestamp,
            last_error=None,
        )
        return SyncResult(
            account_email=account_email,
            processed_messages=processed,
            last_history_id=newest_history_id,
            mode="partial",
        )


def list_recent_messages(
    connection: sqlite3.Connection,
    *,
    limit: int = 12,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT mm.*, ma.email AS account_email
        FROM mail_messages mm
        LEFT JOIN mail_accounts ma ON ma.id = mm.mail_account_id
        ORDER BY COALESCE(mm.received_at, mm.updated_at) DESC
        LIMIT ?
        OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]
