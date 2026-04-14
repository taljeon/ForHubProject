# Architecture

## Current Operating Mode

- Primary runtime: local-only
- Primary persistence: SQLite + local blob files
- LLM runtime: local MLX
- Background execution: local timers / launchd
- Deployment horizon: Firebase or GCP later, without changing application logic

## Layer Boundaries

### Presentation

- `app/main.py`
- `app/templates/`
- `app/static/`

Role:
- receive web requests
- render views
- call use-case level services only

Target direction:
- split `main.py` into router modules under `app/web/`

### Application Services

- `app/services/digest.py`
- `app/services/gmail_sync.py`
- `app/services/source_scanner.py`
- `app/services/job_sources.py`
- `app/services/tracker.py`
- `app/services/local_llm.py`

Role:
- orchestrate use cases
- hide infrastructure details from routes

Target direction:
- split into `jobs/`, `notes/`, `mail/`, `llm/`

### Infrastructure

- `app/db.py`
- `app/storage/`
- Gmail OAuth / Gmail API
- Playwright sessions

Role:
- SQLite access
- blob storage access
- external API and browser automation integration

## Storage Strategy

### Hot Data

- SQLite stays local
- used for lists, filters, dashboard counts, metadata, references

Examples:
- company name
- screening type
- deadline
- summary
- blob metadata

### Cold Blob Data

- raw HTML
- raw interview/note text
- large mail payloads later

Stored via `BlobStore` interface:
- `LocalBlobStore` now
- `DriveBlobStore` later

SQLite should store references, not large bodies:
- `raw_blob_id`
- `raw_storage_backend`
- `raw_checksum`
- `raw_size_bytes`

## Migration Policy

1. New raw data is written to blob storage first.
2. Legacy `raw_text` / `raw_payload_json` is migrated by CLI.
3. After migration, legacy DB raw columns are cleared.
4. Read path stays:
   - blob first
   - legacy DB fallback only if still present

This keeps rollout safe while moving toward blob-only storage.

## Scanner Strategy

### Static Scanner

- `requests + BeautifulSoup`
- public listing pages
- public job detail pages

### Dynamic Scanner

- Playwright only
- login-required pages
- JS-rendered pages
- saved session reuse

Selenium is intentionally not added now because the current project already depends on Playwright.

## Future Deployment

For the next 2 to 3 months, local-only remains the default.

Later deployment target:
- Firebase or GCP-hosted UI / backend

Design rule for future deployment:
- routes and services must not care whether blobs are local or remote
- only storage implementation changes
- SQLite can remain local for single-user mode, or move to a hosted DB later without changing route logic

## Refactor Order

1. storage abstraction
2. raw data migration to blobs
3. static / dynamic scanner split
4. router split from `main.py`
5. hosted deployment profile for Firebase / GCP
