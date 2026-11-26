<!--
Per-file catalogue of the Alphaleo BD repository: each tracked file with its purpose and, for code files,
every function/class with what it does and why the project needs it.
Needed so a new developer or Claude session can find the right file and function quickly.
It is a snapshot (2026-11-18, milestone M1); where files should live is defined in `FILE_STRUCTURE.md`,
module design in `ARCHITECTURE.md`. If the code and this file disagree, the code wins: update this file.
-->

# File descriptions

How to read: each file has a short **Purpose** (what it does and why it exists), then a table of its functions/classes (**What it does** / **Why it is used**). "Tests only" means nothing in `app/` calls it yet. Paths inside `BD_BACKEND/` are written relative to it.

## 1. Project root

| File | Purpose and functionality |
|---|---|
| `CLAUDE.md` | Rules for Claude Code: task workflow, documentation ownership, coding and documentation standards, definition of done. |
| `README.md` | Human entry point: what the app is, current status, tech stack, setup and commands. |
| `ARCHITECTURE.md` | Target design of the system: modules, data flow, API, database, AI. |
| `database.md` | Beginner-friendly reference for all 32 database models (core, audit, leads, imports, compliance): purpose, file location, example and every field. Update with any model or migration change. |
| `FILE_STRUCTURE.md` | Where files live and where new ones go (existing vs planned). |
| `filedescription.md` | This file: per-file purposes and per-function explanations. |
| `PROMPT.md` | Versioned registry of every prompt sent to AI SDK/API calls (no AI code exists yet). |
| `USERPROMPT.md` | Append-only log of development prompts and task summaries; not used by the app. |
| `Makefile` | Thin `make check` entry point (B5): one target, `check`, that runs `bash scripts/check.sh`. Holds no logic, so the same checks run where make is unavailable or blocked. |
| `scripts/check.sh` | The "is it green" script (B5), run from the repo root by any path. Steps in order, stopping at the first failure (`set -euo pipefail`): `docker compose up -d --wait db`; `docker compose build api` (the image copies code at build time, so this avoids checking a stale snapshot); `ruff check .` and `pytest` in the api image; then `npm run typecheck`, `npm run lint` and `npm test` in `BD_FRONTEND` (fails with a hint when `node_modules` is missing). `step()` prints a heading per step. Playwright is excluded (needs the full stack and A8). |
| `docker-compose.yml` | Local-dev stack: `db` (PostgreSQL 17 + pgvector), `api` (runs `alembic upgrade head`, then uvicorn), `worker` (Procrastinate), optional `frontend` profile (verified in B5: the compose-built frontend serves `/login` and redirects `/leads` to `/login`; B3 adds `API_INTERNAL_URL=http://api:8000` so the Next.js server can reach the API by service name). Credentials come from `.env`. |
| `.env.example` | Template for the root `.env` read by compose (`POSTGRES_*`, optional session settings). |
| `.gitignore` | Keeps secrets (`.env`), the per-developer `.claude/settings.local.json`, Python caches, Node/Next.js build output (`node_modules/`, `.next/`, `next-env.d.ts`, `*.tsbuildinfo`) and local artefacts out of git. |

## 2. `.claude/`, `docs/`, `milestone/`

| File | Purpose and functionality |
|---|---|
| `.claude/settings.json` | Shared Claude Code permissions; denies reading `.env*` files. |
| `.claude/skills/ai-adapter/SKILL.md` | Rules Claude must load before touching AI/LLM code or `PROMPT.md`. |
| `.claude/skills/outreach-compliance/SKILL.md` | Rules Claude must load before touching eligibility, opt-outs, campaigns or sending. |
| `docs/plan.md` | Roadmap, rationale, open items, risks, test and deploy plans. |
| `docs/requirements/Q-A.md` | Requirements source of truth (D-001 to D-113); wins over the plan on conflict. |
| `docs/requirements/BD-Ans-2026-10-23-R1.docx` | Original business answers, superseded by `Q-A.md`. |
| `docs/decisions/0001-2026-11-12-docker-in-scope-for-local-dev.md` | Decision record: Docker Compose is allowed for local development. |
| `docs/decisions/0002-2026-11-19-a2-core-tables-decisions.md` | Decision record for A2 (M1, Developer A): admin-editable personal-domain and generic-prefix settings, test clock safety, and the split between Procrastinate, database idempotency and `JobLock`. |
| `milestone/m1.md` | Detailed description of milestone M1 (setup and data model) and the two-developer split. |
| `milestone/m2.md` | Detailed description of milestone M2 (import, validation, quarantine, deduplication); planned, not started. |

## 3. `BD_BACKEND/` configuration and packaging

| File | Purpose and functionality |
|---|---|
| `pyproject.toml` | Package metadata (Python 3.12), runtime dependencies (FastAPI, SQLAlchemy, Alembic, psycopg, Procrastinate, argon2-cffi, and since M2-A1 python-multipart, openpyxl and defusedxml), dev extras (pytest, httpx, ruff), ruff and pytest settings. |
| `alembic.ini` | Alembic settings (`script_location = migrations`); the database URL is deliberately not here, `migrations/env.py` supplies it. |
| `Dockerfile` | Backend image used for both API and worker; installs the package (dev extras when `INSTALL_DEV=true`), runs as a non-root user, default command starts uvicorn on port 8000. |
| `.dockerignore` | Keeps secrets, virtualenvs and caches out of the image. |
| `.env.example` | Template for a native (non-Docker) `.env`: `DATABASE_URL`, `APP_ENV`, session settings. |
| `openapi.json` | Generated, committed OpenAPI schema (sorted keys, 2-space indent); the single contract the frontend client is generated from. Never hand-edited: regenerate with `python -m app.export_openapi` after every API change (task A1). |
| `temp.md` | Empty placeholder. |

## 4. `BD_BACKEND/app/` (application code)

### `app/__init__.py`, `app/core/__init__.py`, `app/audit/__init__.py`
Package markers so `app.*` imports resolve; they contain only docstrings. No functions.

### Stub packages: `app/{content,campaigns,outreach,mail,notifications}/{__init__,models}.py` and `app/{imports,compliance,leads}/__init__.py`
**Purpose:** added in M1 task A0 so every module has a fixed place before its real code exists. `__init__.py` is a docstring-only package marker; `models.py` is a header-only file with no models yet (`leads/models.py` and `imports/models.py` are no longer stubs, see their own sections). Each `models.py` is already imported by `app/models.py`, so the owning task adds its tables there without editing the registry. No functions.

### `app/main.py`
**Purpose:** the FastAPI entry point served by uvicorn (`app.main:app`). Creates the app with the app-level `verify_csrf` dependency (so every route gets the Origin and CSRF-token checks, A8), adds `CORSMiddleware` limited to `settings.frontend_origin` (credentials on, explicit methods and headers, no wildcards), installs the error handlers, mounts the routes (the core router and, since M2-0, the five still-empty M2 routers) and adds the 401/403 entries to the OpenAPI schema. Holds no business logic. Imported by `tests/test_auth_routes.py`, `tests/test_csrf.py` and `tests/test_health.py`. No functions; module-level `app` is the object and `CORS_ALLOWED_METHODS` / `CORS_ALLOWED_HEADERS` are the explicit CORS lists. Because it reads `get_settings()` once at import to build CORS, `DATABASE_URL` must be set when the module is imported (also for `python -m app.export_openapi`).

### `app/export_openapi.py`
Writes or checks `BD_BACKEND/openapi.json` so the frontend has one stable contract and a stale file is caught. Run `python -m app.export_openapi` (write) or `--check` (exit 1 if stale). Constants: `OPENAPI_PATH`, `JSON_INDENT`, `STALE_EXIT_CODE`, `REGENERATE_COMMAND`.
- `build_schema_text()`: renders `app.openapi()` as stable JSON (sorted keys, fixed indent, trailing newline) so output is byte-identical for the same API.
- `is_up_to_date(path)`: True if the file exists and equals the generated text; used by the test and `--check`.
- `main(argv)`: CLI entry; writes the file, or with `--check` returns 0/1 without writing.

### `app/config.py`
**Purpose:** reads environment variables (and a local `.env`) into one validated `Settings` object, so a missing or unsafe setting stops the process at startup. Used by `db.py`, `worker.py`, `core/api.py`, `core/dependencies.py`, `core/services.py`, `core/cookies.py` and `migrations/env.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `Settings` (class) | Typed settings: `database_url` (required), `app_env`, `session_lifetime_hours` (default 12), `session_cookie_name` (default `bd_session`), `session_cookie_secure` (default true), `frontend_origin`. | Single, validated source of configuration; no config lives in code. |
| `Settings.login_max_failures_per_account`, `login_max_failures_per_ip`, `login_throttle_window_minutes` | Login throttling limits (defaults 5, 20, 15; must be above 0; env `LOGIN_MAX_FAILURES_PER_ACCOUNT`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_THROTTLE_WINDOW_MINUTES`). | Configurable limits for A9; zero would lock everyone out, so it is rejected. |
| `Settings.upload_dir`, `upload_max_bytes`, `upload_max_rows`, `xlsx_max_entries`, `xlsx_max_member_bytes`, `xlsx_max_total_bytes`, `xlsx_max_compression_ratio` | Import upload settings (M2-A1): upload directory (default `/srv/uploads`, must be one volume shared by api and worker), 20 MB, 50,000 rows (D-110), and the XLSX ZIP limits 1,000 entries, 100 MB per member, 200 MB total, 100:1 ratio (env `UPLOAD_DIR`, `UPLOAD_MAX_BYTES`, `UPLOAD_MAX_ROWS`, `XLSX_MAX_*`; all above 0). | Limits are configuration, not code. |
| `Settings._validate_session_and_origin()` | On construction, checks `frontend_origin` is a bare http(s) origin (no path, credentials, query) and, in production, requires secure cookies and https. | Fails fast on unsafe production settings. |
| `Settings.psycopg_conninfo` (property) | Returns `database_url` without the `+psycopg` driver suffix. | Procrastinate needs a plain libpq URL (used by `worker.py`). |
| `get_settings()` | Builds `Settings` once and caches it. | Everyone shares one settings object; raises if `DATABASE_URL` is missing. |
| Constants `PRODUCTION_ENV`, `DEFAULT_SESSION_LIFETIME_HOURS`, `DEFAULT_SESSION_COOKIE_NAME`, `DEFAULT_FRONTEND_ORIGIN`, `ALLOWED_ORIGIN_SCHEMES` | Named defaults and allowed values. | No magic numbers or strings. |

### `app/db.py`
**Purpose:** the database plumbing: one SQLAlchemy engine, one base class for all models, and the per-request session. Used by every model and route that touches the database.

| Name | What it does | Why it is used |
|---|---|---|
| `Base` (class) | Parent of every SQLAlchemy model. | Alembic compares `Base.metadata` with the database to detect schema drift. |
| `get_engine()` | Creates the shared engine lazily (cached) with `pool_pre_ping`. | Importing the app never needs a database; stale connections are dropped. Called only by `get_session`. |
| `get_session()` | FastAPI dependency: yields one session per request and closes it; never commits. | Services decide when to commit. Used by `core/api.py` and `core/dependencies.py`; tests override it. |

### `app/models.py`
**Purpose:** model registry. Imports the `models` module of all ten modules (`audit`, `campaigns`, `compliance`, `content`, `core`, `imports`, `leads`, `mail`, `notifications`, `outreach`) so their tables register on `Base.metadata`. Needed because Alembic (`migrations/env.py`) and the schema-drift test only see imported models. Frozen after M1 task A0: new models go in each module's own `models.py`, not here. No functions.

### `app/worker.py`
**Purpose:** the Procrastinate app (PostgreSQL-backed background job runner) started by the `worker` compose service. Its only task is the core sample job (M1 task A10); `app.imports.tasks` (empty until M2-A3) is also listed. Both are registered through `import_paths=["app.core.tasks", "app.imports.tasks"]` (not a direct import, because `core/tasks.py` imports `app` from here). Builds `app` at import time from `get_settings().psycopg_conninfo`, so it also fails fast without `DATABASE_URL`. No functions.

### `app/core/clock.py`
**Purpose:** the only place that reads the system clock, so time-dependent rules can be tested by shifting time.

| Name | What it does | Why it is used |
|---|---|---|
| `now()` | Current UTC time (timezone-aware) plus the test offset. | Used for column defaults in `core/models.py` and `audit/models.py`, and for expiry/revocation in `core/services.py`. |
| `set_offset(delta)` | Shifts all later `now()` calls. | Tests only: simulate session expiry. |
| `reset_offset()` | Removes the shift. | Tests only: clean up after a test. |

### `app/core/passwords.py`
**Purpose:** Argon2id password hashing so no plaintext password is stored. Only `core/services.py` uses it.

| Name | What it does | Why it is used |
|---|---|---|
| `hash_password(plain)` | Returns the Argon2id hash (salt and parameters included); raises `ValueError` on an empty password. | Creating users, the dummy hash, and upgrading old hashes at login. |
| `verify_password(hash, plain)` | True if it matches; False for wrong password or malformed hash (never raises). | Login cannot tell a wrong password from a corrupt hash, and no library error text leaks. |
| `password_needs_rehash(hash)` | True if the hash uses weaker parameters than current. | Lets old hashes be upgraded after a successful login. |

### `app/core/models.py`
**Purpose:** the `core` tables: users and sessions for sign-in (migrations 0002, 0003; read by `core/services.py`), plus the settings store, test-clock offset and job locks (migration 0005, M1 task A2). The A2 tables have no service, API or `core.clock` connection yet (decision record `docs/decisions/0002-2026-11-19-a2-core-tables-decisions.md`).

| Name | What it does | Why it is used |
|---|---|---|
| `UserRole` (enum) | `rep`, `manager`, `admin`. | Roles for the permission module (planned); currently only returned in API responses. |
| `User` (table `users`) | id, email, password hash, role, `is_active`, timestamps; email must be lowercase and is unique ignoring case. | The person who signs in. |
| `UserSession` (table `sessions`) | user id, SHA-256 token hash (unique), created/expires/revoked times, with checks. | Server-side sessions that can be expired or revoked; the raw token is never stored. |
| `Setting` (table `settings`) | Unique lowercase `key` (letters, digits, `_`, `.` only), JSONB `value`, `version` (at least 1), timestamps, nullable `updated_by` FK to users (SET NULL). | Admin-editable configuration such as limits, model names and the personal-domain and generic-prefix lists; new keys need no migration. No rows seeded in A2. |
| `ClockOffset` (table `clock_offsets`) | At most one row (`singleton` true and unique): signed `offset_seconds` (default 0), `updated_at`, nullable `updated_by` FK to users (SET NULL). | Persisted admin test-clock offset. No row means zero. Not read by `core.clock` yet; the real-sending safety rule is a later service. |
| `JobLock` (table `job_locks`) | Unique `name`, `locked_by` worker id, `locked_at`, `expires_at` (must be after `locked_at`), index on `expires_at`. | Application-level lock (e.g. one poll per mailbox); a row exists only while held, and expiry frees a crashed worker's lock. Acquire and release logic is planned. |

### `app/core/model_helpers.py`
**Purpose:** shared SQLAlchemy building blocks (extracted from `leads/models.py` in M1 task A4) so every module that defines tables declares keys, timestamps and fixed-value columns the same way. Imported by `leads/models.py` and `imports/models.py`; migrations mirror the result by hand. No schema of its own.

| Name | What it does | Why it is used |
|---|---|---|
| `enum_column(enum_cls)` | Maps a `StrEnum` to a VARCHAR column that returns enum members. | One way to declare every fixed-value column. |
| `in_check(column, enum_cls, name)` | Builds the named CHECK listing the enum's values. | Keeps the CHECK in step with the Python enum; the migration mirrors it. |
| `TimestampMixin` | `created_at` / `updated_at` from `core.clock.now()`. | Shared by tables whose rows change; no server-side time defaults. |
| `uuid_pk()` | Primary key generated by `gen_random_uuid()`. | Same key style as every other table. |

### `app/leads/models.py`
**Purpose:** the `leads` tables (migration 0006, M1 task A3): unified people and companies that keep the latest values only (D-008), plus what hangs off them. M2 import writes and merges these rows; M3 search, lead detail and flags read them. Tables only: no service, API or search yet. Fixed-value columns are VARCHAR plus a named CHECK (not native enums) so the lists can grow; a test checks each CHECK matches its enum. Column helpers come from `core/model_helpers.py`. `quarantine_records.raw_row_id` was added by A4's `0007` (nullable, unique, CASCADE); `touches` and `lead_events` carry `campaign_id` and `outreach_message_id` without foreign keys (B's `0010` and `0011` add them).

| Name | What it does | Why it is used |
|---|---|---|
| `EmailType`, `EmailVerificationStatus`, `ContactChannelType`, `QuarantineStatus`, `DuplicateStatus`, `SegmentVisibility`, `LeadStatusFlagType`, `TouchChannel`, `TouchDirection`, `TouchStatus` (enums) | Lowercase value sets stored as VARCHAR with a CHECK. | Fixed vocabularies from the decisions (D-072, D-042, D-068, D-092, D-009, D-022/D-065/D-101, D-034, D-063); adding a value is a new migration replacing the CHECK. |
| `Company` (`companies`) | Domain, name and `normalized_name`, `name_is_derived` (D-071), industry (default "Unknown", D-070), NAICS/SIC, employees, revenue, funding fields, `technologies[]` and `keywords[]` (GIN-indexed), `uses_salesforce` (stored; the leads service recomputes it), HQ location, founded year; unique `apollo_account_id`; lowercase-domain and non-negative checks. | The unified company record and its matching keys (D-077) and filter fields (D-063, D-089). |
| `Person` (`people`) | First name (required, D-069), last name, title, seniority, department, location, IANA `timezone`, nullable `owner_id` (SET NULL: Unassigned pool, D-075), nullable `company_id` (SET NULL), `source_status`/`source_stage` as free text, `lists[]`, `last_contacted_at`, `email_bounced`, `replied_at`, stored-but-unused `intent_signals` and `qualify_contact` (D-074). No soft-delete column and no "possible duplicate" column: that state is derived from open `duplicate_candidates` rows (D-092). | The unified lead record. |
| `PersonEmail` (`person_emails`) | Address, lowercase `normalized_address`, type work/personal/generic, verification, `is_primary`, `is_invalid`; unique per person and address, at most one primary per person, index on the normalized address; CASCADE from person. | Several addresses per person (D-072); not globally unique so possible duplicates can share one (D-092); opt-out and matching lookups. |
| `PersonPhone`, `SocialProfile`, `ContactChannel` | Phone numbers and profile URLs per person (unique per person), and generic company channels such as info@ (unique per company, type and value). | Contact details kept apart from the person row. |
| `QuarantineRecord` (`quarantine_records`) | JSONB `issues` and editable `payload`, status open/released/discarded, resolver and time; a record is resolved exactly when not open; nullable `raw_row_id` FK to `raw_rows` (unique, CASCADE, added by 0007). | Import rows held for a human (D-068, D-072, D-107); the link to the untouched original is removed with it on erase-person. |
| `DuplicateCandidate` (`duplicate_candidates`) | Pair `person_a_id` < `person_b_id` (unique, ordered), reason, status open/merged/not_duplicate, decider and time; CASCADE from both people. | Possible-duplicate review queue (D-092). |
| `MergeRecord` (`merge_records`) | Survivor (CASCADE), `absorbed_person_id` (no FK: the row is deleted), JSONB snapshot, merger, time. | Merge history (D-108); erased with the survivor (D-099). |
| `Segment` (`segments`) | Name, JSONB filter set, visibility private/shared (default private), nullable owner (SET NULL). | Saved filters (D-009). |
| `LeadNote` (`lead_notes`) | Person, author (RESTRICT: deactivate users, do not delete), non-blank body. | Colleague notes. |
| `LeadEvent` (`lead_events`) | Person, lowercase event code, JSONB detail, actor (SET NULL), time, plain-UUID `campaign_id` / `outreach_message_id`. | Lead timeline. |
| `Touch` (`touches`) | Person, channel (email only in v1), direction, rep (SET NULL), status sent/opened/bounced/replied/demoed, time, plain-UUID `campaign_id` / `outreach_message_id`. | Contact history on any channel (D-034, D-063). |
| `LeadStatusFlag` (`lead_status_flags`) | One current row per person and flag type (existing customer, in conversation, partner, competitor, qualified, handed off to sales), who and when; clearing deletes the row. | Business flags (D-022, D-065, D-101); change history lives in the audit log and timeline, not here (D-008). |
| `IndustryMapping`, `StateMapping` | Lowercase unique source text mapped to a standard name. | Standardization (D-076, D-078). Empty until M2 seeds them. |

### M2-0 scaffold files: `app/leads/contracts.py`, `app/imports/{wiring,tasks,api,profiles_api}.py`, `app/leads/{quarantine,duplicates,mappings}_api.py`
**Purpose:** the shared parts of milestone M2, created once so the two workstreams never edit the same file afterwards (m2.md sections 17 and 18). No business logic.

| File and names | What it does | Why it is used |
|---|---|---|
| `leads/contracts.py`: `SourceRow`, `ImportContext`, `RowOutcome`, `FieldChange` (frozen dataclasses), `IngestSource`, `RowOutcomeKind` (enums), `IngestRow` (protocol), `JsonScalar` | Types for one row going in and one outcome coming back, the `{field, old, new}` change item, and the `ingest_row(session, row, ctx) -> RowOutcome` signature. | W1 builds rows and counts outcomes; W2 implements `ingest_row`; each tests against these types alone. Changes only by a PR both developers approve. |
| `imports/wiring.py`: `get_ingest_row()`, `_unwired_ingest_row()` | Returns the `ingest_row` the pipeline calls; the stub raises `NotImplementedError`. | The only place W1 reaches W2's code; fails loudly until integration step I1 (M2-A7). |
| `imports/tasks.py` | Docstring only. | Lets the worker already list the module; M2-A3 adds `process_import`. |
| `imports/profiles_api.py`, `leads/quarantine_api.py`, `leads/duplicates_api.py`, `leads/mappings_api.py` | Each holds one empty `router` (prefixes `/source-profiles`, `/quarantine`, `/duplicates`, `/reference-mappings`). | Mounted in `main.py` once; feature tasks add endpoints, each declaring a permission. |
| `imports/api.py` | The `/imports` router; since M2-A1 it holds the three endpoints below (see the M2-A1 section). | Mounted in `main.py` in M2-0. |

### M2-A1 upload files: `app/imports/{errors,storage,xlsx_safety,parsers,multipart,access,upload,schemas}.py`, `api.py`, migration `0014`
**Purpose:** receive a CSV or XLSX upload safely (D-109, D-110): stream it with a size cap, check for an identical earlier file, validate it, store the bytes outside PostgreSQL and register an `ImportFile`. Backend only; the upload page waits for B12.

| File and names | What it does | Why it is used |
|---|---|---|
| `errors.py`: `UploadErrorKind`, `UploadRejectedError`, `ImportNotFoundError`, `StorageError` | One refusal exception with a kind and a fixed client-safe message; a 404 error; an internal storage failure. | The API maps each kind to one 4xx status; messages never contain file contents, names or paths. |
| `storage.py`: `FileStorage` (protocol), `LocalDiskStorage`, `new_storage_key()`, `get_file_storage()` | Save (atomic rename), open and delete objects in `UPLOAD_DIR` by server-generated key (`<32 hex>.csv/.xlsx`, checked with `fullmatch` on every call). | The api and the worker share one directory; the store is replaceable; no path traversal is possible. |
| `xlsx_safety.py`: `ZipLimits`, `check_xlsx_archive()` | Reads only the ZIP directory: entry count, per-member and total size, compression ratio (members of 64 KB or more), encrypted members, presence of `xl/workbook.xml`. | Stops decompression bombs and non-workbooks before openpyxl opens the file; nothing is extracted. |
| `parsers.py`: `FileFormat`, `UploadLimits`, `WorksheetInfo`, `ParsedFile`, `detect_format()`, `parse_upload()`, `count_worksheet()`, `read_worksheet_headers()`, `limits_from_settings()` | CSV: strict UTF-8 (BOM allowed) then Windows-1252, delimiter comma or semicolon chosen by the header and 20-row consistency, ambiguous or single-column files refused. XLSX: read-only, cached values only, lists every sheet with its non-empty data-row count (stops at limit + 1). Blank rows and the header are never counted. | Enforces D-110 and the agreed format rules. |
| `multipart.py`: `read_upload()`, `ReceivedUpload` | Reads the multipart body with a byte counter (Content-Length check, then while streaming), finds the `file` part and the `allow_duplicate` field, hashes the file. | FastAPI's normal file parameter buffers everything first, so the 20 MB limit could not be enforced while receiving. |
| `access.py`: `can_view_import()`, `can_change_import()` | Reps see their own imports, managers and admins all; only the uploader may change one. | One place for the object-level rule; a team scope would change only this file. |
| `upload.py`: `receive_upload()`, `select_worksheet()`, `get_import_for_viewer()`, `find_earlier_upload()`, `clean_display_name()`, `DuplicateFileError`, `DuplicateFileInfo`, `UploadOutcome` | Duplicate check before storing, validation, save, `ImportFile` row, audit events, one commit (a failed commit deletes the stored file); worksheet choice re-counted from the stored file. | The business logic behind the three endpoints. |
| `schemas.py`: `ImportFileResponse`, `UploadResponse`, `WorksheetResponse`, `SelectWorksheetRequest`, `UploadErrorResponse`, `DuplicateFileResponse` | Typed API shapes; none contains the storage key. | Becomes the generated frontend client through `openapi.json`. |
| `api.py`: `POST /imports/upload` (201, 409 duplicate, 413, 415, 422), `GET /imports/{id}`, `POST /imports/{id}/worksheet` | Thin handlers, all `IMPORT_LEADS`; blocking work runs in a thread pool. | The M2-A1 API. |
| `migrations/versions/0014_import_file_storage.py` | Adds nullable `storage_key` (unique) and `size_bytes` (non-negative) to `import_files`. | Records where each stored file is; down_revision `0008`, so B's `0009` must be re-pointed onto it. |

### `app/imports/models.py`
**Purpose:** the `imports` tables (migration 0007, M1 task A4): keep every uploaded row exactly as received (D-099) and record what each import did (D-050). Tables only: no service, API or import pipeline yet. Same VARCHAR plus named CHECK style as `leads`; helpers from `core/model_helpers.py`. The uploaded file's bytes are not stored, only its SHA-256.

| Name | What it does | Why it is used |
|---|---|---|
| `ImportStatus` (enum), `SHA256_HEX_PATTERN`, `REPORT_COUNT_COLUMNS` | Status values uploaded/mapping/processing/completed/failed; the lowercase-hex digest pattern; the seven D-050 total names. | Single definitions shared by the models, the migration's CHECKs and the tests. |
| `SourceProfile` (`source_profiles`) | Unique `name`, free-text `layout`, JSONB `mapping_defaults`, `is_active`, creator (SET NULL). | Saved source description edited by admins only (D-049). Free text and no seed rows because the three layouts are unresolved. |
| `ImportFile` (`import_files`) | `sha256` (lowercase hex, indexed, deliberately not unique), filename, uploader and profile (SET NULL), `default_country` (D-078), `worksheet` (D-110), status, `row_count` (at least 0). | One uploaded file and the duplicate-file lookup (D-109). Row and size limits are checked by the future service. |
| `ColumnMapping` (`column_mappings`) | File (CASCADE), zero-based `column_index` (unique per file), nullable `source_header` and `target_field` (null target means ignored), `is_reassigned`. | The mapping actually used for each column of a file, including header-less columns (D-049). |
| `RawRow` (`raw_rows`) | File (RESTRICT), `row_number` (at least 1, unique per file), JSONB `original_values`, lowercase `email_normalized` (indexed), nullable `person_id` (SET NULL, indexed), `created_at` only. A trigger in 0007 rejects any UPDATE of the original columns; `person_id` may change and DELETE is allowed. | Immutable originals (D-099, D-008); erase-person finds rows by person or by address, including unlinked quarantined ones. |
| `ImportReport` (`import_reports`) | One per file (unique, CASCADE), the seven D-050 counts (each at least 0, default 0), JSONB `failure_reasons`. | Totals and the reason-coded failure breakdown shown after an import. |
| `ImportChange` (`import_changes`) | Report and person (both CASCADE), JSONB `changes` (field to old/new), unique per report and person. | Transient "what changed in this import" summary (D-050); holds personal values, so it goes with the person. No expiry yet: retention is unresolved. |

### `app/compliance/models.py`
**Purpose:** the `compliance` tables (migration 0008, M1 task A5): per-address opt-outs (D-066), the real-sending gate and its checklist (D-081) and erasure proof without personal data (D-099). Tables only: no service, API or eligibility logic yet. `EligibilitySnapshot` is planned, not built. Same VARCHAR plus named CHECK style as `leads` and `imports`.

| Name | What it does | Why it is used |
|---|---|---|
| `OptOutSource` (enum) | `manual`, `imported`, `reply`. | Single source of the allowed `opt_outs.source` values; a test checks the CHECK matches it. |
| `ChecklistItemKey` (enum) | The four D-081 keys: `m365_connected`, `unsubscribe_tested`, `footer_saved`, `postal_address_saved`. | Closed key set for the checklist; a test checks the CHECK matches it. |
| `OptOut` (`opt_outs`) | One row per opt-out event: lowercase `email_normalized`, source, optional reason, `created_by`/`removed_by` (SET NULL), `removed_at`, `removal_reason`. A removal needs a reason, and removal fields exist only together. A partial unique index allows one active row (`removed_at IS NULL`) per address. No FK to people. | Per-address suppression that survives erase-person and covers addresses without a person; soft removal keeps history and lets an address opt out again. |
| `ComplianceGateStatus` (`compliance_gate_status`) | Single row (a `singleton` flag forced true and unique): `real_sending_enabled`, `enabled_at` (set exactly when enabled), `enabled_by` (SET NULL). Seeded disabled by 0008. No kill switch (left to M8). | The M8 switch for real sending (D-081); readers never face a missing row. |
| `ComplianceChecklistItem` (`compliance_checklist_items`) | One row per D-081 key (unique, CHECK-limited), `is_passed` (true exactly when `passed_at` is set), `passed_by` (SET NULL), `note`. Four rows seeded not passed by 0008. | The conditions the admin must pass before enabling real sending; the closed key set stops the gate being weakened by deleting an item. |
| `ErasureRecord` (`erasure_records`) | `former_person_id` (plain UUID, no FK, indexed), `erased_by` (SET NULL), `erased_at`, `reason`, JSONB `removed_counts`. No personal data. | Proves an erase-person ran (D-099) after the person row is gone; the address stays only in `opt_outs`. |

### `app/core/schemas.py`
**Purpose:** strict shapes for the auth API so the boundary validates input and never serializes the `User` object (which holds the password hash). Used by `core/api.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `LoginRequest` | Body of `POST /auth/login`: trimmed email (max 320), password (max 1024, not trimmed); extra fields rejected. | Validates input; spaces can be part of a password. |
| `LoginRequest._email_has_at_sign()` | Rejects an email with no `@`. | Cheap sanity check; full validation is not needed to look a user up. |
| `UserResponse` | `{id, email, role}`. | The only user data returned to clients. |
| `SessionUserResponse` | `UserResponse` plus `csrf_token`. | Returned by login and `GET /auth/me` only (A8), so the frontend learns the token of the current session. |
| `UserDetailResponse` | `UserResponse` plus `is_active`, `created_at`, `updated_at`. | The admin user list and "my profile" (A7); still never the password hash. |
| `CreateUserRequest` (+ `_email_has_at_sign()`) | Body of `POST /users`: trimmed email, role, initial password (12 to 1024 characters, not trimmed); extra fields rejected. | Validates admin input; the password is hashed in the service. |
| `ChangeRoleRequest` | Body of `PATCH /users/{id}`: the new `role`. | Only the role is editable (see A7 notes in `m1.md`). |
| `ValidationErrorItem`, `ValidationErrorResponse` | `{type, loc, msg}` and `{detail: [...]}`. | Only used to document the real 422 body in `openapi.json` (A7; the body itself comes from `errors.py`). |
| `ErrorResponse` | `{detail}`, extra fields rejected. | Only used to describe the 401 and 403 bodies in `openapi.json` (the real bodies come from `dependencies.py` and `errors.py`). |
| Constants `PASSWORD_MAX_LENGTH`, `PASSWORD_MIN_LENGTH` | Password length bounds (the minimum applies only to admin-set initial passwords). | Named values; login still accepts older shorter passwords. |

### `app/core/user_services.py`
**Purpose:** the business logic of user management (M1 task A7): list, create, change role, deactivate and reactivate users, with the admin safeguards and the audit trail. Routes in `core/api.py` call it and add nothing. Every mutating function re-checks `MANAGE_USERS` and commits itself together with its audit row.

| Name | What it does | Why it is used |
|---|---|---|
| `list_users(db, actor)` | All users ordered by email. | Admin user list. |
| `create_user(db, actor, *, email, password, role, ip_address)` | Normalizes the email, refuses a duplicate (any letter case, also under a race), hashes the password with Argon2id, audits `user.created`. | Admin creates accounts with an initial password; no plaintext is stored or audited. |
| `change_role(db, actor, user_id, *, role, ip_address)` | Changes the role and audits `user.role_changed` with before and after; same role is a silent no-op; own role is refused. | Role changes are sensitive and audited (plan module S). |
| `deactivate_user(db, actor, user_id, *, ip_address)` | Sets `is_active` false, audits `user.disabled` and revokes all the user's sessions in one commit; idempotent. | A deactivated user must lose access at once (approved A7 design point 2). |
| `reactivate_user(db, actor, user_id, *, ip_address)` | Sets `is_active` true and audits `user.enabled`; old sessions stay revoked. | Undo a mistaken deactivation. |
| `_require_manage_users`, `_get_user_for_update`, `_lock_active_admin_count`, `_guard_admin_loss` | Capability re-check; row lock on the target; locked count of active admins; the self and last-admin safeguards. | The locks stop two admins removing each other at the same moment. |
| `UserManagementError` and `UserNotFoundError`, `EmailAlreadyExistsError`, `SelfModificationError`, `LastAdminError` | Expected failures. | Mapped to fixed 404 or 409 bodies in `api.py`. |

### `app/core/services.py`
**Purpose:** the business logic of login, logout and sessions. Routes and dependencies call these functions and never touch tokens, hashes or the sessions table directly. Expiry is absolute; the raw token is returned only once and only its hash is stored. Used by `core/api.py` and `core/dependencies.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `generate_session_token()` | New random 43-character URL-safe token. | Unguessable session identifier (called by `create_session`). |
| `hash_session_token(token)` | SHA-256 hex digest. | Only the hash is stored, so a database leak gives no usable tokens. |
| `create_session(db, user, lifetime=None)` | Saves a new session, commits, returns `(raw_token, row)`; raises `InactiveUserError` for a disabled user. | Called by `login` after a successful check. |
| `get_active_session(db, token)` | Returns the user and session if the hash matches, not revoked, not expired and user active; else `None`. Wrong-length tokens skip the database. | Called by `core/dependencies.py` to identify the caller; read-only. |
| `revoke_session(db, token)` | Marks a session revoked (idempotent), returns whether one was revoked now. | Logout. |
| `revoke_all_user_sessions(db, user_id)` | Revokes all of a user's active sessions, returns the count. | Called by `user_services.deactivate_user`; also planned for password change. |
| `normalize_email(email)` | Strip and lowercase. | Emails are stored lowercase, so lookups must match. |
| `_dummy_password_hash()` | Hash of a throwaway password, built once. | Unknown emails still cost one Argon2 check, so timing does not reveal which emails exist. |
| `_record_login_failure(...)` | Writes and commits one `auth.login_failed` audit row; stores the attempted email only if it looks like an email. | Failed logins are audited; people sometimes paste passwords into the email field. |
| `_record_login_throttled(db, *, user, scope, ip_address)` | Writes and commits one `auth.login_throttled` audit row (summary holds only the scope). | Blocked attempts are audited but, being a different action, are never counted as failures (A9 decision 8). |
| `login(db, email, password, *, ip_address, lifetime=None, throttle_limits=None)` | Checks credentials with one password verification on every path, then rejects the attempt if the account or address is throttled (even with a correct password), audits failures, upgrades weak hashes, writes `auth.login_succeeded`, creates the session; raises `InvalidCredentialsError` for failures and blocks alike. | The login rule, behind `POST /auth/login`; a block looks exactly like a wrong password. |
| `logout(db, token)` | Revokes the session if a token is given; never raises for bad tokens. | Behind `POST /auth/logout`. |
| `InactiveUserError`, `InvalidCredentialsError` | Exceptions for a disabled user and for any login failure. | The second is turned into HTTP 401 in `api.py`; the first is only raised and tested. |
| `AuthenticatedSession` | Pair of `user` and `session`. | Return value of `get_active_session`. |
| `SampleJobResult` (frozen dataclass) | Holds `echoed_message`. | Return type of the sample job service; equal inputs give equal results. |
| `run_sample_job(message)` | Returns a `SampleJobResult` with the same message; no writes, no clock, no tables. | The idempotent body of the worker sample job (A10); `core/tasks.py` wraps it, and later task services copy the shape. |
| Constants `TOKEN_BYTES`, `TOKEN_LENGTH`, `EMAIL_MAX_LENGTH`, `DUMMY_PASSWORD`, `REASON_*` | Token sizes, email limit, dummy password, audit failure reasons. | Named values instead of magic numbers; the reasons are never shown to clients. |

### `app/core/dependencies.py`
**Purpose:** answers "who is calling?" for protected routes by turning the session cookie into the user. Authentication only: 401, never 403 (the 403 checks live in `core/permissions.py`, which builds on `CurrentUser`).

| Name | What it does | Why it is used |
|---|---|---|
| `get_current_session(request, db, settings)` | Reads the session cookie, resolves it via `services.get_active_session`, raises 401 with one fixed message if missing or inactive. | One place that parses cookies; read-only, extends nothing. |
| `get_current_user(auth)` | Returns the session's user. | Convenience for routes. |
| `CurrentUser` | Type alias `Annotated[User, Depends(get_current_user)]`. | Routes write `current_user: CurrentUser` to require sign-in. |
| `NOT_AUTHENTICATED_DETAIL` | The one 401 message. | Responses never reveal why a token failed. |

### `app/core/permissions.py`
**Purpose:** the central permission module (M1 task A6, `plan.md` section 4): who may use each capability, the guards routes declare, and the owner-only rule. Every route declares exactly one of `public_route` or `require_permission(...)`; the matrix test reads those declarations. Used by `core/api.py`, `core/errors.py`, `app/main.py` and the tests. The capability list covers the whole `plan.md` section 4 table now; capabilities whose endpoints are not built yet (everything except `VIEW_OWN_PROFILE`) are **planned** and unused until their milestone.

| Name | What it does | Why it is used |
|---|---|---|
| `Permission` | One capability per `plan.md` section 4 row (the "sending limits, mailboxes, users, test clock" row is split into four). Log in/out has none: those routes are public. | Routes name what they guard instead of repeating role lists. |
| `PERMISSION_ROLES` | Maps each capability to the roles that hold it. Only reps get `EDIT_DRAFT` and `APPROVE_DRAFT`; managers and admins get `VIEW_ALL_DRAFTS` (read-only). | The single reviewable source of truth for grants (Q-ROLES-03). |
| `has_permission(user, permission)` | True if the user is active and their role holds the capability. | Used by the guard and by services. |
| `is_owner(user, owner_id)` | True only when `owner_id` is the user's id; a missing owner is nobody's. | Ownership test without depending on any draft model. |
| `require_owner(user, owner_id)` | Raises `PermissionDeniedError` unless the user owns the object. | Services call it so a job or a second route cannot skip the owner-only rule. |
| `PermissionDeniedError` | Domain exception for a denial. | Turned into a 403 by `core/errors.py`. |
| `PermissionGuard`, `require_permission(permission)` | Route dependency: signed-in user (401 first) whose role holds the capability, else 403; carries its capability. | One line per route; tests read the capability back. |
| `PublicRoute`, `public_route` | No-op marker dependency. | States "public on purpose" so a forgotten route is distinguishable. |
| `RouteDeclaration` | What a route declares (`public`, `permissions`, `is_valid`). | Result type for the matrix test. |
| `ApiRouteView`, `get_route_declaration(route)`, `iter_api_routes(app)` | Read a route's guards from its dependency tree; iterate API routes across FastAPI versions (lazy included routers in newer ones). | Lets the test and the OpenAPI step see what is enforced. |
| `install_permission_openapi(app)` | Adds 401 and 403 (`ErrorResponse`) to every guarded route in the OpenAPI schema. | The generated frontend client can type the errors without per-route `responses=`. |
| `PERMISSION_DENIED_DETAIL`, `ERROR_RESPONSE_SCHEMA_NAME` | The fixed 403 message and the schema name. | The 403 body never names a capability, owner or lead data. |

### `app/core/cookies.py`
**Purpose:** defines the session cookie flags in one place. Used by `core/api.py::login` and `::logout`.

| Name | What it does | Why it is used |
|---|---|---|
| `set_session_cookie(response, token, settings)` | Sets the cookie: HttpOnly, SameSite=Lax, Path `/`, Max-Age equal to the session lifetime, Secure per setting. | The browser drops the cookie when the server session expires. |
| `clear_session_cookie(response, settings)` | Deletes the cookie with identical attributes. | A mismatch in path or flags would make the browser keep it. |
| `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_PATH`, `SECONDS_PER_HOUR` | Cookie constants. | No magic values. |

### `app/core/tasks.py`
**Purpose:** the Procrastinate tasks of the `core` module, starting with the worker sample job (M1 task A10, the "run sample job" demo step). It is the pattern later `tasks.py` files copy: a thin task that only calls a service, with a queueing lock against duplicate jobs. Registered by `worker.py` through `import_paths`. Run by hand with `python -m app.core.tasks`.

| Name | What it does | Why it is used |
|---|---|---|
| `sample_job(message)` (task `core.sample_job`, queueing lock `core.sample_job`) | Calls `services.run_sample_job` and logs one line with the echoed message. | The thin-wrapper pattern; the lock refuses a second identical job while one waits. |
| `defer_sample_job()` (async) | Opens the app and defers one job; returns `True` if queued, `False` if `AlreadyEnqueued`. | Lets the command line and the tests defer the job the same way. |
| `main()` | Runs `defer_sample_job` and prints "queued" or "already waiting". | Entry for `python -m app.core.tasks`. |
| Constants `SAMPLE_JOB_NAME`, `SAMPLE_JOB_QUEUEING_LOCK`, `SAMPLE_JOB_MESSAGE` | Task name, lock key, echoed text. | No magic strings. |

### `app/core/login_throttle.py`
**Purpose:** decides whether a login attempt is blocked by too many recent failures (M1 task A9). It only reads existing `audit_log` rows, so there is no new table. Used by `core/services.py::login` and `core/api.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `LoginThrottleLimits` (frozen dataclass) | The limits: failures per account, failures per address, window length (defaults 5, 20, 15 minutes). `from_settings(settings)` builds it from `Settings`. | One typed object instead of loose numbers. |
| `ThrottleScope` (enum) | `account` or `ip`. | Records in the audit summary which limit blocked. |
| `find_throttle_scope(db, *, user_id, ip_address, limits)` | Returns the blocking scope or `None`. Account: `auth.login_failed` rows for the user after the window start and after their latest `auth.login_succeeded`. Address: `auth.login_failed` rows from that address inside the rolling window (successes ignored). An unknown email (no `user_id`) is limited by address only; a missing address skips the address limit. | The rule itself; throttled rows are never counted, so a block expires by itself. |
| `_count_failures_for_user`, `_count_failures_for_ip` | The two count queries. | Keep `find_throttle_scope` readable. |
| Constants `DEFAULT_MAX_FAILURES_PER_ACCOUNT`, `DEFAULT_MAX_FAILURES_PER_IP`, `DEFAULT_WINDOW_MINUTES` | Documented defaults. | No magic numbers. |

### `app/core/csrf.py`
**Purpose:** CSRF protection for the cookie session (M1 task A8): the session-bound token, the Origin check and the request guard. `verify_csrf` is installed on every route by `app/main.py`; the contract for the frontend is in `milestone/m1.md` section 16. Used by `core/api.py`, `app/main.py` and the tests.

| Name | What it does | Why it is used |
|---|---|---|
| `csrf_token_for_session_token(session_token)` | Returns `sha256("csrf:" + raw session token)` as hex. | Token derived from the session, so no table or column is needed and it dies with the session; the prefix keeps it different from the stored `token_hash`. |
| `verify_csrf(request, settings)` | App-level dependency. For POST, PUT, PATCH and DELETE: a present `Origin` must equal `settings.frontend_origin` exactly; except for `POST /auth/login`, `X-CSRF-Token` must match the token derived from the session cookie (constant-time compare). Raises 403 with the fixed body `{"detail": "CSRF check failed"}` otherwise; nothing is audited. | Stops a foreign site from using the browser's cookie; login only gets the Origin check because nobody has a token yet. |
| `_tokens_match(presented, expected)` | `hmac.compare_digest` on UTF-8 bytes. | Constant-time, and a non-ASCII header cannot raise. |
| `install_csrf_openapi(app)` | Adds the 403 (`ErrorResponse`) to every POST, PUT, PATCH and DELETE operation in `openapi.json`, or appends "or CSRF check failed" to the existing permission 403. | The schema documents what enforcement does. |
| `CSRF_HEADER_NAME`, `CSRF_TOKEN_PREFIX`, `STATE_CHANGING_METHODS`, `LOGIN_PATH`, `CSRF_FAILED_DETAIL` | Named constants. | No magic values. |

### `app/core/errors.py`
**Purpose:** error shaping for the whole API. FastAPI's default 422 echoes the submitted value, which would send a password back to the client; and a permission denial raised in a guard or a service must become one fixed 403. Registered by `app/main.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `validation_error_handler(request, exc)` | Returns a 422 with only `type`, `loc`, `msg` per error. | Never echoes submitted values. |
| `permission_denied_handler(request, exc)` | Returns a 403 with the fixed body `{"detail": "Not permitted"}` for any `PermissionDeniedError`. | One status and body for every denial (A6), nothing about the capability or owner. |
| `install_validation_error_openapi(app)` | Rewrites every 422 in `openapi.json` to `ValidationErrorResponse` (`type`, `loc`, `msg`) and drops FastAPI's default schemas. | The documented 422 now matches what the handler really returns (A7). |
| `register_error_handlers(app)` | Installs both handlers on the app. | Called once from `main.py`. |
| `VALIDATION_ERROR_STATUS`, `PERMISSION_DENIED_STATUS`, `SAFE_ERROR_KEYS`, `VALIDATION_RESPONSE_NAME` | The status codes, the allowed error keys and the schema name. | Named constants. |

### `app/core/api.py`
**Purpose:** the HTTP routes, kept thin; all logic is in `core/services.py` and `core/user_services.py`. Mounted by `app/main.py`. Every route declares its access: `/health`, `/auth/login` and `/auth/logout` use `public_route`; `/auth/me` and `/users/me` use `require_permission(Permission.VIEW_OWN_PROFILE)`; the other `/users` routes use `MANAGE_USERS` (admin only).

| Name | What it does | Why it is used |
|---|---|---|
| `health(session)` | `GET /health`: runs `SELECT 1`; 200 ok, or 503 degraded when the database is unreachable. | Probes (Docker, operators) get a clear body and no error text. |
| `login(body, request, response, db, settings)` | `POST /auth/login`: calls `services.login` (with `LoginThrottleLimits.from_settings(settings)`), maps `InvalidCredentialsError` to 401 with one message, sets the cookie, returns `SessionUserResponse` (user plus `csrf_token`). | Sign-in endpoint; uses the direct client IP only (forwarded headers not trusted yet). The only state-changing route exempt from the CSRF token. |
| `logout(db, settings, request)` | `POST /auth/logout`: revokes the session and clears the cookie; 204 once the CSRF check passed. | Needs no authentication so an expired session can still sign out, but since A8 it needs `X-CSRF-Token` (derived from the cookie, so an expired cookie still works; no cookie at all is 403). |
| `me(current_user, request, settings)` | `GET /auth/me`: returns the signed-in user and the session's `csrf_token`, or 401 (every role holds `VIEW_OWN_PROFILE`). | Lets a frontend check who is signed in and recover the token after a page reload. |
| `my_profile(current_user)` | `GET /users/me`: the caller's own profile (`UserDetailResponse`). | "My profile" screen. |
| `list_users`, `create_user`, `change_user_role`, `deactivate_user`, `reactivate_user` | `GET /users`, `POST /users` (201), `PATCH /users/{id}` (role only), `POST /users/{id}/deactivate`, `POST /users/{id}/reactivate`; admin only. Map `UserManagementError` to 404 or 409 with fixed messages. | Admin user management for the frontend (A7). |
| `_client_ip(request)`, `_http_error(error)`, `USER_ERROR_RESPONSES` | Direct peer address for audit; error to (status, fixed detail). | Same IP rule as login; one table for messages. |
| `router`, `auth_router`, `users_router`, `INVALID_CREDENTIALS_DETAIL` | Route groups and the single login-failure message. | The message never says which part was wrong. |

### `app/audit/models.py`
**Purpose:** the `audit_log` table definition. Leaf module (imports only `db` and `core.clock`, never `core.models`; a test enforces it).

| Name | What it does | Why it is used |
|---|---|---|
| `AuditLog` (table `audit_log`) | One immutable row: time, actor user id (no foreign key), action, object type/id, JSON summary, IP. The database triggers from migration 0004 reject update, delete and truncate. | A permanent history of sensitive actions that even bugs or manual SQL cannot alter. |

### `app/audit/services.py`
**Purpose:** the only way code writes audit rows. Used by `core/services.py::_record_login_failure`.

| Name | What it does | Why it is used |
|---|---|---|
| `AuditAction` (enum) | Allowed actions such as `auth.login_failed`, `auth.login_succeeded`, `auth.login_throttled`, `user.created`, `user.role_changed`, plus the 16 M2 actions added in M2-0 (`import.*`, `source_profile.*`, `quarantine.*`, `duplicate.*`, `mapping.reference_changed`). | A fixed vocabulary stops typos being stored forever. The login actions (failed, succeeded, throttled) and the user-management actions are used in production code; the M2 actions are used by the M2 tasks that own them (not yet). |
| `FORBIDDEN_SUMMARY_KEYS` | `password`, `password_hash`, `token`, `token_hash`, `session_token`. | Secrets must never enter a permanent log. |
| `_find_forbidden_key(value)` | Recursively finds a forbidden key in a summary (case-insensitive). | Used by `record`. |
| `record(db, *, action, actor_user_id, object_type, object_id, summary, ip_address)` | Validates the action and summary, adds the row and flushes (never commits); raises `ValueError` on bad input. | The caller's commit makes the audit row and the action it describes succeed or fail together. |

## 5. `BD_BACKEND/migrations/` (Alembic)

| File | Purpose and functionality |
|---|---|
| `env.py` | Alembic entry point. `_url()` picks the database URL (Alembic config first, else app settings). `run_migrations_offline()` prints SQL without a connection. `run_migrations_online()` connects (no pool) and applies migrations in a transaction. Imports `app.models` so autogenerate and the drift test see every table. Run by the `api` compose service and by tests. |
| `script.py.mako` | Template used to generate new migration files. |
| `migrations.md` | Plain-language explanation of what migrations are and how they are used here. |
| `versions/0001_enable_pgvector.py` | `upgrade()` installs the `vector` extension (needed for embeddings); `downgrade()` drops it and fails on purpose if any column uses it. |
| `versions/0002_create_users.py` | `upgrade()` creates the `user_role` enum, `users` table, lowercase-email check and case-insensitive unique index; `downgrade()` drops them (all users lost). |
| `versions/0003_create_sessions.py` | `upgrade()` creates `sessions` (FK to users with cascade, two checks, three indexes); `downgrade()` drops it (everyone logged out). |
| `versions/0004_create_audit_log.py` | `upgrade()` creates `audit_log`, its indexes, the function `audit_log_forbid_change()` and two triggers (row-level update/delete, statement-level truncate); `downgrade()` drops all of it (history lost). |
| `versions/0005_create_core_tables.py` | `upgrade()` creates `settings` (unique key, key-format and version checks, FK `updated_by`), `clock_offsets` (one-row cap, FK `updated_by`) and `job_locks` (unique name, expiry check, expiry index); inserts no rows. `downgrade()` drops all three (settings, offset and locks lost). |
| `versions/0006_create_leads_tables.py` | `upgrade()` creates the 16 leads tables in dependency order with their constraints and exact-filter, matching-key and GIN indexes; inserts no rows; leaves out `quarantine_records.raw_row_id` (0007) and the foreign keys on `touches`/`lead_events` link columns (B's 0010/0011). Helpers `_id_column`, `_timestamp_columns`, `_in`. `downgrade()` drops all 16 tables (all lead data lost). |
| `versions/0007_create_imports_tables.py` | `upgrade()` creates `source_profiles`, `import_files`, `column_mappings`, `raw_rows`, `import_reports` and `import_changes` with constraints and indexes; creates the PL/pgSQL function `raw_rows_forbid_original_change()` and trigger `raw_rows_guard_original_columns` (rejects UPDATE of the original columns, allows `person_id` changes and DELETE); adds `quarantine_records.raw_row_id` with a unique constraint and a CASCADE foreign key; inserts no rows. Helpers `_id_column`, `_timestamp_columns`. `downgrade()` drops the quarantine link, trigger, function and all six tables (all raw rows, mappings, reports and change summaries lost). |
| `versions/0008_create_compliance_tables.py` | `upgrade()` creates `opt_outs` (with the partial unique index on the active address), `compliance_gate_status`, `compliance_checklist_items` and `erasure_records` with constraints and indexes, then seeds one disabled gate row and the four D-081 checklist rows (timestamps from the database `now()`, since migrations run outside the app clock). Helpers `_id_column`, `_timestamp_columns`, `_in_list`. `downgrade()` drops all four tables: every opt-out, the gate state, checklist progress and erasure record is lost, so it must never run on a database holding real opt-outs. |
| `versions/0014_import_file_storage.py` | `upgrade()` adds nullable `import_files.storage_key` (unique) and `size_bytes` (non-negative CHECK); `downgrade()` drops them (the keys and sizes cannot be restored; stored files stay on disk). Revision `0014`, `down_revision` `0008`; B must re-point `0009` onto it. |

Alembic calls every `upgrade()`/`downgrade()` itself. Applied migrations are never edited; each model change adds a new one.

## 6. `BD_BACKEND/tests/` (pytest, real PostgreSQL with pgvector)

Common helpers repeated in several files: `_alembic_config(url)` (Alembic config for the test database), an `engine` fixture (migrates the test database once per module), a rolled-back `session` fixture, and an autouse `_reset_clock_offset` fixture (so one test cannot shift time for another). Tests never call external services; data is synthetic.

| File | Purpose and what it covers |
|---|---|
| `conftest.py` | `test_database_url` (session fixture): requires `DATABASE_URL`, drops and creates a throwaway `<name>_test` database and returns its URL, so the dev database is untouched. Added in A3 and used by the leads tests (older files keep their own copies): `alembic_config(url)`, `migrated_engine` (migrates once per module), `db_session` (rolled back after each test), `assert_rejected(row, constraint)` (insert must fail on that constraint, inside a SAVEPOINT so earlier rows survive), and synthetic-row fixtures `user`, `company`, `person`. |
| `test_company_person_models.py` | `companies`, `people`, `person_emails`, `person_phones`, `social_profiles`, `contact_channels`: defaults, arrays round-trip, lowercase and non-negative checks, unique Apollo id, mandatory first name, clock use, SET NULL on company and owner, email defaults and checks, per-person uniqueness but shared addresses allowed, one primary email, CASCADE on erase. Helper `_email`. |
| `test_leads_review_models.py` | `quarantine_records`, `duplicate_candidates`, `merge_records`: defaults, payload required, resolved-time matches status, status CHECK, SET NULL on resolver, ordered and unique pair, decision-time rule, cascades, merge snapshot without an absorbed row. Helper `_two_people`. |
| `test_leads_activity_models.py` | `segments`, `lead_notes`, `lead_events`, `touches`, `lead_status_flags`, `industry_mappings`, `state_mappings`: defaults, enum CHECKs, blank note, RESTRICT on note author, event-code format, link columns without FKs, SET NULL on rep, one flag per person and type, lowercase and unique mapping keys. Helper `_touch`. |
| `test_leads_tables_migration.py` | Migration 0006 upgrades, downgrades to 0005 and upgrades again on a throwaway database; all 16 tables empty after upgrade; `raw_row_id` present (added by 0007) and the B-owned link columns carry no FK; each of the ten enum CHECKs lists exactly its `StrEnum` values. Fixture `roundtrip_url`, helpers `alembic_config`, `_existing_tables`, `_row_counts`. |
| `test_import_storage.py` | `LocalDiskStorage` and the key rules: key shape, save/open/delete round trip, atomic save with no temporary leftovers, invalid keys (traversal, wrong extension, trailing newline) refused by every operation. |
| `test_import_parsers.py` | CSV and XLSX parsers and archive safety: encodings (UTF-8, BOM, Windows-1252, undecodable, NUL), delimiter rules (semicolon, single column, tie, consistent choice), blank rows not counted, row limit boundary, sheet listing and selection, oversized or empty sheets, non-ZIP and Office-encrypted files, ZIP entry, member, total, ratio and encrypted-flag limits. Uses `import_files.py`. |
| `test_import_upload.py` | The `/imports` endpoints on PostgreSQL: upload stores file and row and audits; duplicate 409 and "import anyway" with override audit; refusals (415, 422, 413 from Content-Length and while streaming) store nothing; failed commit removes the stored file; visibility by role; worksheet choice (uploader only, unknown, empty, oversized, after processing, CSV). |
| `test_import_storage_migration.py` | Migration `0014` round trip on its own database, plus unique `storage_key`, non-negative `size_bytes` and NULLs for old rows. |
| `import_files.py` | Test helper (not a test file): in-memory builders for CSV, XLSX and multipart bodies from synthetic rows (replaces committed binary fixtures). |
| `test_m2_scaffold.py` | M2-0 scaffold, no database: the six `RowOutcomeKind` values, contract objects immutable, `FieldChange` keys, the unwired `ingest_row` raising, each of the five routers having its prefix, tag, no routes and being imported by `main.py`, the 16 audit actions with agreed values and no duplicates, and `app.imports.tasks` in the worker's `import_paths`. |
| `test_module_dependencies.py` | Guard for the M2 imports/leads exception, using the standard `ast` module: `app/leads` imports only `app.imports.models` from imports; `app/imports` imports only `leads.contracts` and `leads.models`, plus `leads.ingest` in `wiring.py`. Helpers `_imported_modules`, `_is_within`. |
| `test_imports_models.py` | The imports tables on real PostgreSQL: defaults, non-unique `sha256` and digest CHECK, status and count CHECKs, unique profile name, unique mapping per file and column, raw-row uniqueness, lowercase email and RESTRICT on files with rows, the immutability trigger (each original column rejected; `person_id` change and DELETE allowed; SET NULL on person delete), one report per file, change-summary uniqueness and CASCADE with the person, and the `quarantine_records.raw_row_id` unique link and CASCADE. Fixtures `import_file`, `raw_row`, `report`. |
| `test_imports_tables_migration.py` | Migration 0007 upgrades, downgrades to 0006 and upgrades again on a throwaway database (tables, guard trigger and function, quarantine column all appear and disappear); no rows inserted; the status CHECK lists exactly the `ImportStatus` values. Fixture `roundtrip_url`, helpers `alembic_config`, `_scalar`, `_tables_exist`, `_guard_exists`, `_quarantine_has_raw_row_id`. |
| `test_compliance_models.py` | The compliance tables on real PostgreSQL: opt-out defaults, one active opt-out per address, re-opt-out after removal, lowercase, source and removal CHECKs, SET NULL on user delete; the gate is seeded disabled and a second or non-singleton row is rejected; the checklist is seeded with the four keys and enforces unique keys and the passed/timestamp CHECK; erasure records need no person and survive its deletion. |
| `test_compliance_tables_migration.py` | Migration 0008 upgrades, downgrades to 0007 and upgrades again on a throwaway database; seeds exactly one gate row (disabled) and four checklist rows and no other rows; the source and item_key CHECKs list exactly the `OptOutSource` and `ChecklistItemKey` values. Fixture `roundtrip_url`, helpers `alembic_config`, `_scalar`, `_tables_exist`, `_check_values`. |
| `test_audit_log.py` | `record()` stores all fields and follows the clock; does not commit; triggers reject UPDATE/DELETE/TRUNCATE; secret keys and unknown actions are rejected; `AuditAction` values are unique and dotted; the audit package does not import `core` modules. Helpers: `_count_rows`. |
| `test_auth_routes.py` | `/auth/login`, `/auth/logout`, `/auth/me` through the real app (using `CsrfTestClient`; login and `/auth/me` bodies include `csrf_token`): no secrets in responses, cookie flags, only the token hash stored, every failure looks identical, one committed audit row per failure, exactly one password check per path, weak hash upgraded, 422 never echoes values, logout idempotent, independent sessions. Fixtures: `api_app`, `use_settings`, `client`, `make_client`, `user`, `disabled_user`; helpers `_login`, `_count_rows`, `_failed_login_rows`, `_cookie_attributes`, `_make_settings`, `_keys_at_any_depth`. |
| `test_sample_job.py` | The A10 checks on Procrastinate's in-memory connector (no PostgreSQL, no network): service is idempotent, task is registered, a deferred job runs to success and logs the message, a second defer while one waits raises `AlreadyEnqueued`, and `defer_sample_job` returns `True` then `False`. |
| `test_login_throttle.py` | The A9 checks on PostgreSQL: block at 5 account failures (correct password rejected, no session), 4 do not block, throttled rows are not counted, the block ends after the window (test clock), success resets the account count, accounts are independent, the address limit and unknown emails, success does not reset the address count, `auth.login_succeeded` row, identical 401 over HTTP, throttle settings defaults, overrides and rejection of zero. |
| `csrf_client.py` | Test helper (not a test file). `CsrfTestClient` is a `TestClient` that adds `X-CSRF-Token`, derived from the session cookie it holds, to POST, PUT, PATCH and DELETE unless the caller passed the header. Used by `test_auth_routes.py`, `test_users_api.py` and `test_permission_matrix.py` so they need not repeat the header. |
| `test_csrf.py` | The A8 checks on PostgreSQL with plain clients: token formula and difference from the stored hash, safe methods need no token, missing, wrong, other-session and non-ASCII tokens are 403 (also before 422), a valid token passes, anonymous POST is 403 not 401, all failures share one body, foreign and near-miss Origins are 403 (also on login, which stays token-free), matching or absent Origin falls through to the token, login and `/auth/me` return the same session-bound token, logout needs the token, rejected requests write no audit row, CORS preflight (frontend allowed with credentials, other origins and unlisted headers refused, no wildcards, CORS headers on a CSRF 403), OpenAPI 403 and `csrf_token`. Fixtures `app`, `admin_client`; helpers `_make_user`, `_signed_in`, `_login`, `_preflight`. |
| `test_clock.py` | `now()` is aware UTC; `set_offset`/`reset_offset` shift and restore it. |
| `test_clock_offset_model.py` | `clock_offsets`: starts empty, defaults (offset 0, singleton true), signed offsets, second row and `singleton=false` rejected, `updated_by` FK and SET NULL. Fixtures `engine`, `session`, `user`. |
| `test_core_tables_migration.py` | Migration 0005 upgrades, downgrades to 0004 and upgrades again on a throwaway database; all three tables empty after upgrade. Fixture `roundtrip_url`, helpers `_existing_core_tables`, `_row_counts`. |
| `test_job_lock_model.py` | `job_locks`: unique name, different names coexist, re-lock after release, expiry-after-lock check, owner required, clock use. Helper `_new_lock`. |
| `test_setting_model.py` | `settings`: generated fields, duplicate key, key-format check (valid and invalid keys), JSON values round-trip, SQL NULL value, version rule, `updated_by` FK and SET NULL, clock use. |
| `test_config.py` | Missing `DATABASE_URL` fails; `psycopg_conninfo`; defaults and env overrides; bad lifetime, cookie name or origin rejected; production rules. Fixture: `base_env`. |
| `test_permissions.py` | No database. The table covers every capability; `has_permission` follows the table and denies inactive users; only reps edit or approve drafts while managers and admins view them read-only; `is_owner` and `require_owner` (a non-owner of any role, or an ownerless object, is rejected); a denial becomes exactly `{"detail": "Not permitted"}` with 403 and leaks nothing. Helper `_user`. |
| `test_users_api.py` | The `/users` API and `user_services` on PostgreSQL: rep and manager get 403 on every admin endpoint, anonymous 401, every role reads own profile, admin list order, create (normalized email, Argon2 hash, audit without the password, duplicate 409, invalid bodies 422 without echo), role change audited and no-op silent, self demotion and self deactivation refused, last-admin guard, deactivation revokes sessions and is idempotent, reactivation needs a new session, unknown id 404, narrowed 422 in OpenAPI. Fixture `app` (uses `CsrfTestClient`, so writes carry the CSRF header); helpers `_make_user`, `_client`, `_audit_actions`. |
| `test_permission_matrix.py` | The role-by-endpoint matrix. Structural: every real route declares exactly one of public or a capability, the ten existing routes declare what is expected, an undeclared or doubly-declared route is detected, a canary fails if FastAPI hides guards. Behavioural (PostgreSQL): one probe route per capability called as rep, manager, admin (200 or 403 per a hand-copied `plan.md` section 4 matrix) and anonymous (401), a disabled admin gets 401, real `/auth/me` per role. OpenAPI: 401 and 403 only on guarded routes (public POST routes get only the CSRF 403). Fixtures `probe_app`, `real_app_client_factory`; helpers `_override_session`, `_make_user`, `_client_for`, `_add_probe`. |
| `test_current_user.py` | A tiny app with protected routes: no, bad, expired, revoked or disabled session all give the same 401; role change visible next request; dependencies cached per request; cookie name from settings; no side effects. Helpers `_sign_in`, `_expire_by_clock`, `_disable`, `_arrange_*`. |
| `test_health.py` | `/health` returns 200 normally and 503 when the database session fails (via dependency override). Fixture: `client`. |
| `factories/__init__.py` | Header-only package marker (M1 task A0). No functions. Tests import it as `factories` (the `tests/` folder is on the path, there is no `tests/__init__.py`). |
| `factories/common.py` | Shared helpers. `next_number()` returns a run-wide unique integer so default emails, names and hashes never collide; `persist(session, row)` adds and flushes (never commits). |
| `factories/core.py` | `make_user`, `make_user_session`, `make_setting`, `make_clock_offset` (call once per test: the table allows one row), `make_job_lock`. Reused by B's factories for users. |
| `factories/leads.py` | One `make_*` per leads table (company, person, person email/phone, social profile, contact channel, quarantine record, duplicate candidate, merge record, segment, lead note/event, touch, status flag, industry and state mapping). Parents are created when not passed; the duplicate-candidate factory orders the pair by id as the CHECK requires. |
| `factories/imports.py` | `make_source_profile`, `make_import_file` (valid unique SHA-256), `make_column_mapping`, `make_raw_row`, `make_import_report`, `make_import_change`. Raw rows are only inserted, never updated (D-099). |
| `factories/compliance.py` | `make_opt_out`, `make_erasure_record`, plus `make_compliance_gate_status` and `make_compliance_checklist_item`, which return the rows migration 0008 already seeded (with overrides applied) instead of inserting a duplicate. |
| `test_factories.py` | Smoke tests: every repeatable factory inserts two distinct valid rows, the three single-row factories return a valid row, overrides win, and the seeded factories return the migration rows. Catches a factory drifting from `models.py`. |
| `test_schema_rule_gaps.py` | The A11 gap tests (34 foreign-key cases, 7 CHECK cases): each builds a valid row with a factory, sets one column invalid and expects PostgreSQL to reject it by constraint name. Covers rules the A2-A5 tests did not name. |
| `test_migration_heads.py` | `test_alembic_has_single_head`: the Alembic history has exactly one head, so parallel migrations that fork the chain fail the build. No database needed. |
| `test_migrations.py` | All migrations apply to an empty database and pgvector is installed. |
| `test_openapi_export.py` | Committed `openapi.json` equals the generated schema (stale file fails with the regenerate command); schema lists `/health` and `/auth/*`; generation is deterministic; `is_up_to_date` flags missing and changed files; `main(["--check"])` returns 0 and does not rewrite. No database. |
| `test_passwords.py` | Argon2id format, no plaintext in hash, salting, unicode, malformed hash returns False, empty password rejected, rehash detection. No database. |
| `test_session_model.py` | `sessions` constraints: unique token hash, foreign key, cascade delete, expiry check, hash length, clock use. Helpers `_new_session`, `_count_sessions`. |
| `test_session_service.py` | Token generation and hashing, `create_session` (hash only, lifetime, inactive user), `get_active_session` (unknown, wrong length with zero SQL, expiry, revoke, disabled user, single joined SELECT, role refresh), `revoke_session`, `revoke_all_user_sessions`. Helpers `_make_user`, `_collect_statements`. |
| `test_user_migration.py` | Users migration upgrades, downgrades and upgrades again; downgrade to 0002 drops `sessions` only. Fixture `roundtrip_url`, helper `_users_table_and_role_type_exist`. |
| `test_user_model.py` | `users` constraints (duplicate and mixed-case emails, unknown role, default active, clock use) and `test_models_match_the_migrated_schema`: autogenerate finds no difference between models and migrations. Helper `_new_user`. |

## 7. `BD_FRONTEND/`

| File | Purpose and functionality |
|---|---|
| `package.json` | Frontend manifest (M1 task B1): exact pins (next 16.4.6, react/react-dom 19.3.1, typescript 6.0.3, eslint 10.15.0, eslint-config-next 16.4.6, `@types/*`), `engines` Node `>=22.18 <25` (B2: the floor of the generator), scripts `dev`, `build`, `start`, `lint` (`eslint .`), `typecheck` (`tsc --noEmit`), `generate:api` (`openapi-ts`) and `check:api` (`node scripts/check-api.mjs`). B2 adds the dev dependency `@hey-api/openapi-ts` pinned to exactly 0.99.0. B4 adds the test dev dependencies, all pinned exactly: vitest 5.1.1, `@vitejs/plugin-react` 6.3.0, jsdom 31.0.1, `@testing-library/react` 16.3.3, `@testing-library/jest-dom` 8.0.0, `@testing-library/user-event` 14.6.13, `@playwright/test` 1.65.1, and the scripts `test` (`vitest run`) and `test:e2e` (`playwright test`). JSON has no comments, so this row is its header. |
| `package-lock.json` | Generated by `npm install`; locks the dependency tree so `npm ci` in the Dockerfile is reproducible. Never hand-edited. |
| `next.config.ts` | Next.js config exporting `nextConfig` with `output: "standalone"`; the Dockerfile copies `.next/standalone`, which only exists with this setting. |
| `tsconfig.json` | Strict TypeScript settings for Next.js (bundler resolution, `@/*` alias to `src/*`); Next.js maintains the `include` list itself; B4 adds `vitest.config.mts` to it so the Vitest config is type-checked. JSON has no comments, so this row is its header. |
| `eslint.config.mjs` | ESLint flat config: `eslint-config-next` core-web-vitals and TypeScript rule sets; build output, `next-env.d.ts`, the generated client `src/lib/api/**` and the Playwright output folders (`test-results/**`, `playwright-report/**`, B4) are ignored. Used by `npm run lint`. |
| `vitest.config.mts` | Vitest config (B4): React plugin, jsdom environment, the `@` alias to `src`, `vitest.setup.ts` as setup file, runs only `tests/unit/**/*.test.{ts,tsx}`, and a fallback `NEXT_PUBLIC_API_BASE_URL` so importing the API client cannot throw. Named `.mts` so Node loads it as an ES module. Used by `npm test`. |
| `vitest.setup.ts` | Vitest setup (B4), run before each test file: registers the jest-dom matchers (`toBeInTheDocument`, `toBeDisabled`, ...) and calls Testing Library's `cleanup()` after each test (globals are off, so it cannot do this itself). |
| `playwright.config.ts` | Playwright config (B4): tests in `tests/e2e`, Chromium only (bundled, or an installed browser via the optional `E2E_BROWSER_CHANNEL`, for example `msedge`), not parallel (shared accounts), base URL from `E2E_BASE_URL` (default `http://localhost:3000`), and a `webServer` that starts `npm run dev` or reuses a running one. Loads the git-ignored `.env.local` with `process.loadEnvFile` when it exists, so the `E2E_*` accounts can live there. Used by `npm run test:e2e`; not part of `make check`. |
| `tests/unit/LoginForm.test.tsx` | Vitest tests for `LoginForm` (B4), with the API client and router faked: required fields, successful login (`replace("/leads")` before `refresh()`), 401 fixed message, 422 shows only `msg` texts, no-response message, and the busy "Signing in…" state. Synthetic credentials only. |
| `tests/unit/AppShell.test.tsx` | Vitest tests for `AppShell` (B4), with the router, API client and `next/link` faked: title, email and role, page body and Sign out button; a rep sees no Admin or Users link, an admin does. |
| `src/app/(app)/{leads/import,leads/quarantine,leads/duplicates,admin/source-profiles,admin/mappings}/page.tsx` | Empty M2 screen shells (M2-0) built on `PlaceholderPage`; each owner replaces its shell's content in its own task. |
| `tests/unit/nav-items.test.ts` | Vitest tests for `NAV_ITEMS` (B4, extended in M2-0): the exact links, in order, for `rep`, `manager` (adds Duplicates) and `admin` (adds Source profiles and Mappings). `labelsFor(role)` applies the same filter as `NavBar`. |
| `tests/e2e/helpers.ts` | Playwright helpers (B4). `readCredentials(role)` reads `E2E_REP_*` or `E2E_ADMIN_*` from the environment and throws a clear error when missing; `submitLoginForm(page, credentials)` opens `/login` and submits the form. |
| `tests/e2e/login.spec.ts` | The one Playwright login journey (B4): wrong password shows the error, rep lands on `/leads` without Admin or Users links, admin sees them, logout returns to `/login` and `/leads` then redirects back. Needs the running API, the database, two existing test accounts and CORS (task A8). |
| `openapi-ts.config.ts` | Config for `@hey-api/openapi-ts` (B2): reads `../BD_BACKEND/openapi.json` (read-only contract owned by Developer A) and writes the typed client to `src/lib/api/` with the TypeScript types, SDK functions and fetch client plugins. Used by `npm run generate:api`. |
| `scripts/check-api.mjs` | Staleness check (B2), run as `npm run check:api`. `readTree()` snapshots the generated folder, `differences()` compares two snapshots; the script regenerates the client and exits 1 when any file changed, so a stale or hand-edited client is caught. Plain Node, no shell, works on Windows and Mac. |
| `src/lib/api/**` | Generated by `@hey-api/openapi-ts` from `openapi.json`; never hand-edited (CLAUDE.md). `types.gen.ts` (request, response and error types such as `LoginRequest`, `UserResponse`, `UserRole`, `HttpValidationError`), `sdk.gen.ts` (one function per endpoint: `loginAuthLoginPost`, `logoutAuthLogoutPost`, `meAuthMeGet`, `healthHealthGet`; names come from the schema's operation IDs and are accepted as-is), `client.gen.ts` (the shared fetch client instance), `index.ts`, plus `client/` and `core/` runtime helpers. |
| `src/lib/api-client.ts` | Hand-written runtime setup (B2), kept outside the generated folder. `readApiBaseUrl()` reads `NEXT_PUBLIC_API_BASE_URL` and throws when missing; the module configures the generated client once (base URL, `credentials: "include"` for the session cookie) and re-exports the API functions and types that pages use. Single place where B12 adds the CSRF header. B3 adds a browser-only response interceptor (guarded by `typeof window`) that sends any 401 to `/login` with a full page load, except for the login call itself (`/auth/login`) and when already on `/login`. |
| `src/lib/auth-server.ts` | Server-only session lookup (B3). `getSessionState()` reads the request's cookie and calls `meAuthMeGet` with the cookie in that call's own headers (never on the shared client, so sessions cannot leak between requests); returns `signed-in` (with the user), `signed-out` (401 or no cookie) or `unavailable` (backend down or 5xx). `readServerApiBaseUrl()` uses `API_INTERNAL_URL`, falling back to `NEXT_PUBLIC_API_BASE_URL`. |
| `src/lib/auth-context.tsx` | Client context (B3). `AuthProvider({ user })` holds the user the server layout already loaded; `useCurrentUser()` returns it and throws outside the provider. Makes no requests. |
| `src/lib/nav-items.ts` | Navigation entries (B3): `NAV_ITEMS` with label, path and the roles that see the link. Cosmetic only; the server enforces access. |
| `next-env.d.ts` | Generated by Next.js (git-ignored); type references for Next.js. Never edited. |
| `tsconfig.tsbuildinfo` | Generated TypeScript incremental cache (git-ignored). Never edited. |
| `src/app/layout.tsx` | Root layout. `metadata` sets the page title and description; `RootLayout({ children })` wraps every route in the base HTML document (`lang="en"`) and loads `globals.css` (B3). The signed-in shell lives in `(app)/layout.tsx`. |
| `src/app/page.tsx` | Home route `/` (B3, replaced the B1 placeholder). `HomePage()` calls `getSessionState()` and redirects: signed in to `/leads`, otherwise to `/login`. Renders nothing itself. |
| `src/app/globals.css` | The one global stylesheet (B3, plain class names, no CSS modules): colour variables with dark mode (including `--login-*` variables), login page (CSS-only gradient, dot grid and glows via `.auth-page`, card, `.auth-brand`, `.auth-tagline`), form fields with focus ring, buttons (`.button-block`), shell header, nav and content area. |
| `src/app/login/page.tsx` | Login page (B3). `LoginPage()` redirects signed-in visitors to `/leads`, otherwise renders `LoginForm`. |
| `src/app/(app)/layout.tsx` | Layout of every signed-in screen (B3). `AppLayout()` runs the server-side `/auth/me` check: 401 redirects to `/login`, backend failure shows a "Backend unavailable" message (no redirect, to avoid loops), success renders `AuthProvider` and `AppShell`. Runs on full loads and `router.refresh()`, not on client-side navigation. |
| `src/app/(app)/{leads,campaigns,review,outbox,admin,users,profile}/page.tsx` | Seven empty screen shells (B3), each rendering `PlaceholderPage` with a title and when it gets content (M3, M4, M5, or after the user management API A7). No API calls, no business rules. |
| `src/components/LoginForm.tsx` | Client login form (B3). Shows a brand block (title, tagline). `LoginForm()` calls `loginAuthLoginPost`; on success `router.replace("/leads")` then `router.refresh()`; any 401 shows one fixed message, a 422 shows only the `msg` texts, no response shows a "cannot reach the server" message. |
| `src/components/LogoutButton.tsx` | Client sign-out button (B3). `LogoutButton()` calls `logoutAuthLogoutPost`; on success `router.replace("/login")` then `router.refresh()`; on failure stays put and shows an error. |
| `src/components/NavBar.tsx` | Client navigation (B3). `NavBar()` lists `NAV_ITEMS` for the current role (cosmetic) and marks the active link with `aria-current`. |
| `src/components/AppShell.tsx` | Server component (B3): header with the user's email and role, `NavBar`, `LogoutButton`, and the content area. |
| `src/components/PlaceholderPage.tsx` | Shared body of the empty shells (B3): a title and an availability note. |
| `public/.gitkeep` | Keeps the otherwise empty `public/` folder in git; the Dockerfile copies `public/` and fails if it is missing. |
| `.env.local.example` | Template for the git-ignored `.env.local`: `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`, public) and, from B3, an optional commented `API_INTERNAL_URL` (server-side only, for Docker; falls back to the public URL). B4 adds commented `E2E_*` placeholders (base URL and the fake rep and admin test accounts) for Playwright. No real secrets. |
| `AGENTS.md` | Auto-written by `next dev` (Next.js agent notes). Not part of the B1 scope; keep or delete is pending the owner's decision. |
| `Dockerfile` | Three-stage Next.js build (deps, build, standalone run). Verified for B1: the image builds and serves the page. Used by the optional `frontend` compose profile. |
| `.dockerignore` | Excludes `node_modules`, build output and env files from the frontend image. |
| `temp.md` | Empty placeholder. |
