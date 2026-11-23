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

## 3. `BD_BACKEND/` configuration and packaging

| File | Purpose and functionality |
|---|---|
| `pyproject.toml` | Package metadata (Python 3.12), runtime dependencies (FastAPI, SQLAlchemy, Alembic, psycopg, Procrastinate, argon2-cffi), dev extras (pytest, httpx, ruff), ruff and pytest settings. |
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
**Purpose:** the FastAPI entry point served by uvicorn (`app.main:app`). Creates the app, installs the error handler and mounts the routes. Holds no business logic. Imported by `tests/test_auth_routes.py` and `tests/test_health.py`. No functions; module-level `app` is the object.

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
**Purpose:** the Procrastinate app (PostgreSQL-backed background job runner) started by the `worker` compose service. No tasks are registered yet (M1 no-op). Builds `app` at import time from `get_settings().psycopg_conninfo`, so it also fails fast without `DATABASE_URL`. No functions.

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

### `app/core/services.py`
**Purpose:** the business logic of login, logout and sessions. Routes and dependencies call these functions and never touch tokens, hashes or the sessions table directly. Expiry is absolute; the raw token is returned only once and only its hash is stored. Used by `core/api.py` and `core/dependencies.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `generate_session_token()` | New random 43-character URL-safe token. | Unguessable session identifier (called by `create_session`). |
| `hash_session_token(token)` | SHA-256 hex digest. | Only the hash is stored, so a database leak gives no usable tokens. |
| `create_session(db, user, lifetime=None)` | Saves a new session, commits, returns `(raw_token, row)`; raises `InactiveUserError` for a disabled user. | Called by `login` after a successful check. |
| `get_active_session(db, token)` | Returns the user and session if the hash matches, not revoked, not expired and user active; else `None`. Wrong-length tokens skip the database. | Called by `core/dependencies.py` to identify the caller; read-only. |
| `revoke_session(db, token)` | Marks a session revoked (idempotent), returns whether one was revoked now. | Logout. |
| `revoke_all_user_sessions(db, user_id)` | Revokes all of a user's active sessions, returns the count. | Tests only for now; planned for password change or disabling a user. |
| `normalize_email(email)` | Strip and lowercase. | Emails are stored lowercase, so lookups must match. |
| `_dummy_password_hash()` | Hash of a throwaway password, built once. | Unknown emails still cost one Argon2 check, so timing does not reveal which emails exist. |
| `_record_login_failure(...)` | Writes and commits one `auth.login_failed` audit row; stores the attempted email only if it looks like an email. | Failed logins are audited; people sometimes paste passwords into the email field. |
| `login(db, email, password, *, ip_address, lifetime=None)` | Checks credentials with one password verification on every path, audits failures, upgrades weak hashes, creates the session; raises `InvalidCredentialsError`. | The login rule, behind `POST /auth/login`. |
| `logout(db, token)` | Revokes the session if a token is given; never raises for bad tokens. | Behind `POST /auth/logout`. |
| `InactiveUserError`, `InvalidCredentialsError` | Exceptions for a disabled user and for any login failure. | The second is turned into HTTP 401 in `api.py`; the first is only raised and tested. |
| `AuthenticatedSession` | Pair of `user` and `session`. | Return value of `get_active_session`. |
| Constants `TOKEN_BYTES`, `TOKEN_LENGTH`, `EMAIL_MAX_LENGTH`, `DUMMY_PASSWORD`, `REASON_*` | Token sizes, email limit, dummy password, audit failure reasons. | Named values instead of magic numbers; the reasons are never shown to clients. |

### `app/core/dependencies.py`
**Purpose:** answers "who is calling?" for protected routes by turning the session cookie into the user. Authentication only: 401, never 403. Used by `core/api.py::me`.

| Name | What it does | Why it is used |
|---|---|---|
| `get_current_session(request, db, settings)` | Reads the session cookie, resolves it via `services.get_active_session`, raises 401 with one fixed message if missing or inactive. | One place that parses cookies; read-only, extends nothing. |
| `get_current_user(auth)` | Returns the session's user. | Convenience for routes. |
| `CurrentUser` | Type alias `Annotated[User, Depends(get_current_user)]`. | Routes write `current_user: CurrentUser` to require sign-in. |
| `NOT_AUTHENTICATED_DETAIL` | The one 401 message. | Responses never reveal why a token failed. |

### `app/core/cookies.py`
**Purpose:** defines the session cookie flags in one place. Used by `core/api.py::login` and `::logout`.

| Name | What it does | Why it is used |
|---|---|---|
| `set_session_cookie(response, token, settings)` | Sets the cookie: HttpOnly, SameSite=Lax, Path `/`, Max-Age equal to the session lifetime, Secure per setting. | The browser drops the cookie when the server session expires. |
| `clear_session_cookie(response, settings)` | Deletes the cookie with identical attributes. | A mismatch in path or flags would make the browser keep it. |
| `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_PATH`, `SECONDS_PER_HOUR` | Cookie constants. | No magic values. |

### `app/core/errors.py`
**Purpose:** error shaping for the whole API. FastAPI's default 422 echoes the submitted value, which would send a password back to the client. Registered by `app/main.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `validation_error_handler(request, exc)` | Returns a 422 with only `type`, `loc`, `msg` per error. | Never echoes submitted values. |
| `register_error_handlers(app)` | Installs that handler on the app. | Called once from `main.py`. |
| `VALIDATION_ERROR_STATUS`, `SAFE_ERROR_KEYS` | The status code and the allowed error keys. | Named constants. |

### `app/core/api.py`
**Purpose:** the HTTP routes, kept thin; all logic is in `core/services.py`. Mounted by `app/main.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `health(session)` | `GET /health`: runs `SELECT 1`; 200 ok, or 503 degraded when the database is unreachable. | Probes (Docker, operators) get a clear body and no error text. |
| `login(body, request, response, db, settings)` | `POST /auth/login`: calls `services.login`, maps `InvalidCredentialsError` to 401 with one message, sets the cookie, returns `UserResponse`. | Sign-in endpoint; uses the direct client IP only (forwarded headers not trusted yet). |
| `logout(db, settings, request)` | `POST /auth/logout`: revokes the session and clears the cookie; 204 always. | Needs no authentication so an expired session can still sign out. |
| `me(current_user)` | `GET /auth/me`: returns the signed-in user, or 401. | Lets a frontend check who is signed in. |
| `router`, `auth_router`, `INVALID_CREDENTIALS_DETAIL` | Route groups and the single login-failure message. | The message never says which part was wrong. |

### `app/audit/models.py`
**Purpose:** the `audit_log` table definition. Leaf module (imports only `db` and `core.clock`, never `core.models`; a test enforces it).

| Name | What it does | Why it is used |
|---|---|---|
| `AuditLog` (table `audit_log`) | One immutable row: time, actor user id (no foreign key), action, object type/id, JSON summary, IP. The database triggers from migration 0004 reject update, delete and truncate. | A permanent history of sensitive actions that even bugs or manual SQL cannot alter. |

### `app/audit/services.py`
**Purpose:** the only way code writes audit rows. Used by `core/services.py::_record_login_failure`.

| Name | What it does | Why it is used |
|---|---|---|
| `AuditAction` (enum) | Allowed actions such as `auth.login_failed`, `user.created`, `user.role_changed`. | A fixed vocabulary stops typos being stored forever. Only `LOGIN_FAILED` is used in production code; the rest are reserved for later tasks. |
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
| `test_imports_models.py` | The imports tables on real PostgreSQL: defaults, non-unique `sha256` and digest CHECK, status and count CHECKs, unique profile name, unique mapping per file and column, raw-row uniqueness, lowercase email and RESTRICT on files with rows, the immutability trigger (each original column rejected; `person_id` change and DELETE allowed; SET NULL on person delete), one report per file, change-summary uniqueness and CASCADE with the person, and the `quarantine_records.raw_row_id` unique link and CASCADE. Fixtures `import_file`, `raw_row`, `report`. |
| `test_imports_tables_migration.py` | Migration 0007 upgrades, downgrades to 0006 and upgrades again on a throwaway database (tables, guard trigger and function, quarantine column all appear and disappear); no rows inserted; the status CHECK lists exactly the `ImportStatus` values. Fixture `roundtrip_url`, helpers `alembic_config`, `_scalar`, `_tables_exist`, `_guard_exists`, `_quarantine_has_raw_row_id`. |
| `test_compliance_models.py` | The compliance tables on real PostgreSQL: opt-out defaults, one active opt-out per address, re-opt-out after removal, lowercase, source and removal CHECKs, SET NULL on user delete; the gate is seeded disabled and a second or non-singleton row is rejected; the checklist is seeded with the four keys and enforces unique keys and the passed/timestamp CHECK; erasure records need no person and survive its deletion. |
| `test_compliance_tables_migration.py` | Migration 0008 upgrades, downgrades to 0007 and upgrades again on a throwaway database; seeds exactly one gate row (disabled) and four checklist rows and no other rows; the source and item_key CHECKs list exactly the `OptOutSource` and `ChecklistItemKey` values. Fixture `roundtrip_url`, helpers `alembic_config`, `_scalar`, `_tables_exist`, `_check_values`. |
| `test_audit_log.py` | `record()` stores all fields and follows the clock; does not commit; triggers reject UPDATE/DELETE/TRUNCATE; secret keys and unknown actions are rejected; `AuditAction` values are unique and dotted; the audit package does not import `core` modules. Helpers: `_count_rows`. |
| `test_auth_routes.py` | `/auth/login`, `/auth/logout`, `/auth/me` through the real app: no secrets in responses, cookie flags, only the token hash stored, every failure looks identical, one committed audit row per failure, exactly one password check per path, weak hash upgraded, 422 never echoes values, logout idempotent, independent sessions. Fixtures: `api_app`, `use_settings`, `client`, `make_client`, `user`, `disabled_user`; helpers `_login`, `_count_rows`, `_failed_login_rows`, `_cookie_attributes`, `_make_settings`, `_keys_at_any_depth`. |
| `test_clock.py` | `now()` is aware UTC; `set_offset`/`reset_offset` shift and restore it. |
| `test_clock_offset_model.py` | `clock_offsets`: starts empty, defaults (offset 0, singleton true), signed offsets, second row and `singleton=false` rejected, `updated_by` FK and SET NULL. Fixtures `engine`, `session`, `user`. |
| `test_core_tables_migration.py` | Migration 0005 upgrades, downgrades to 0004 and upgrades again on a throwaway database; all three tables empty after upgrade. Fixture `roundtrip_url`, helpers `_existing_core_tables`, `_row_counts`. |
| `test_job_lock_model.py` | `job_locks`: unique name, different names coexist, re-lock after release, expiry-after-lock check, owner required, clock use. Helper `_new_lock`. |
| `test_setting_model.py` | `settings`: generated fields, duplicate key, key-format check (valid and invalid keys), JSON values round-trip, SQL NULL value, version rule, `updated_by` FK and SET NULL, clock use. |
| `test_config.py` | Missing `DATABASE_URL` fails; `psycopg_conninfo`; defaults and env overrides; bad lifetime, cookie name or origin rejected; production rules. Fixture: `base_env`. |
| `test_current_user.py` | A tiny app with protected routes: no, bad, expired, revoked or disabled session all give the same 401; role change visible next request; dependencies cached per request; cookie name from settings; no side effects. Helpers `_sign_in`, `_expire_by_clock`, `_disable`, `_arrange_*`. |
| `test_health.py` | `/health` returns 200 normally and 503 when the database session fails (via dependency override). Fixture: `client`. |
| `factories/__init__.py` | Header-only stub package (M1 task A0); per-module factory files (`core.py`, `leads.py`, ...) are added later. No functions. |
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
| `playwright.config.ts` | Playwright config (B4): tests in `tests/e2e`, Chromium only, not parallel (shared accounts), base URL from `E2E_BASE_URL` (default `http://localhost:3000`), and a `webServer` that starts `npm run dev` or reuses a running one. Loads the git-ignored `.env.local` with `process.loadEnvFile` when it exists, so the `E2E_*` accounts can live there. Used by `npm run test:e2e`; not part of `make check`. |
| `tests/unit/LoginForm.test.tsx` | Vitest tests for `LoginForm` (B4), with the API client and router faked: required fields, successful login (`replace("/leads")` before `refresh()`), 401 fixed message, 422 shows only `msg` texts, no-response message, and the busy "Signing in…" state. Synthetic credentials only. |
| `tests/unit/AppShell.test.tsx` | Vitest tests for `AppShell` (B4), with the router, API client and `next/link` faked: title, email and role, page body and Sign out button; a rep sees no Admin or Users link, an admin does. |
| `tests/unit/nav-items.test.ts` | Vitest tests for `NAV_ITEMS` (B4): the exact links, in order, for `rep`, `manager` and `admin`. `labelsFor(role)` applies the same filter as `NavBar`. |
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
