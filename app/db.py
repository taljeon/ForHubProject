from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import Settings, get_settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    is_authoritative INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mail_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_account_id INTEGER NOT NULL UNIQUE,
    sync_mode TEXT NOT NULL DEFAULT 'idle',
    last_history_id TEXT,
    last_full_sync_at TEXT,
    last_partial_sync_at TEXT,
    last_error TEXT,
    FOREIGN KEY (mail_account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mail_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_account_id INTEGER NOT NULL,
    gmail_message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT,
    history_id TEXT,
    internal_ts TEXT,
    subject TEXT,
    sender TEXT,
    recipient TEXT,
    snippet TEXT,
    labels_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT,
    received_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (mail_account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    careers_url TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    base_url TEXT NOT NULL,
    seed_url TEXT NOT NULL UNIQUE,
    parser_kind TEXT NOT NULL,
    requires_login INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    last_checked_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS job_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    source_id INTEGER,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    employment_type TEXT,
    graduate_year INTEGER,
    engineer_score REAL NOT NULL DEFAULT 0,
    location TEXT,
    deadline TEXT,
    raw_hash TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    summary TEXT,
    raw_payload_json TEXT,
    raw_blob_id TEXT,
    raw_storage_backend TEXT,
    raw_checksum TEXT,
    raw_size_bytes INTEGER,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (source_id) REFERENCES job_sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS site_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_or_platform TEXT NOT NULL UNIQUE,
    login_id TEXT,
    contact_email TEXT,
    vault_item_id TEXT,
    playwright_state_path TEXT,
    email_migrated INTEGER NOT NULL DEFAULT 0,
    last_login_verified_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playwright_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_account_id INTEGER,
    state_path TEXT NOT NULL UNIQUE,
    browser_engine TEXT NOT NULL DEFAULT 'chromium',
    last_captured_at TEXT,
    last_verified_at TEXT,
    uses_indexed_db INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    FOREIGN KEY (site_account_id) REFERENCES site_accounts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    route TEXT,
    contact_email TEXT,
    current_stage TEXT NOT NULL DEFAULT 'applied',
    next_action TEXT,
    deadline TEXT,
    my_priority INTEGER NOT NULL DEFAULT 3,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS interview_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    source_name TEXT NOT NULL,
    source_url TEXT,
    screening_stage TEXT,
    question_tags TEXT,
    summary_note TEXT,
    question_examples TEXT,
    prep_points TEXT,
    memo TEXT,
    raw_text TEXT,
    raw_blob_id TEXT,
    raw_storage_backend TEXT,
    raw_checksum TEXT,
    raw_size_bytes INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}',
    checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS selection_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    details TEXT,
    source TEXT,
    message_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT NOT NULL UNIQUE,
    markdown_path TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    llm_summary_json TEXT,
    generated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mail_messages_received_at ON mail_messages(received_at);
CREATE INDEX IF NOT EXISTS idx_job_posts_deadline ON job_posts(deadline);
CREATE INDEX IF NOT EXISTS idx_job_posts_status ON job_posts(status);
CREATE INDEX IF NOT EXISTS idx_applications_deadline ON applications(deadline);
CREATE INDEX IF NOT EXISTS idx_interview_notes_checked_at ON interview_notes(checked_at);
CREATE INDEX IF NOT EXISTS idx_selection_events_event_at ON selection_events(event_at);
"""


def get_connection(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    if column_name in _table_columns(connection, table_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


@contextmanager
def db_session(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    connection = get_connection(settings)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _ensure_column(
        connection,
        table_name="daily_digests",
        column_name="llm_summary_json",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="raw_text",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="detail_json",
        column_sql="TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="raw_blob_id",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="raw_storage_backend",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="raw_checksum",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="interview_notes",
        column_name="raw_size_bytes",
        column_sql="INTEGER",
    )
    _ensure_column(
        connection,
        table_name="job_posts",
        column_name="raw_blob_id",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="job_posts",
        column_name="raw_storage_backend",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="job_posts",
        column_name="raw_checksum",
        column_sql="TEXT",
    )
    _ensure_column(
        connection,
        table_name="job_posts",
        column_name="raw_size_bytes",
        column_sql="INTEGER",
    )
