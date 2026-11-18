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
| `FILE_STRUCTURE.md` | Where files live and where new ones go (existing vs planned). |
| `filedescription.md` | This file: per-file purposes and per-function explanations. |
| `PROMPT.md` | Versioned registry of every prompt sent to AI SDK/API calls (no AI code exists yet). |
| `USERPROMPT.md` | Append-only log of development prompts and task summaries; not used by the app. |
| `docker-compose.yml` | Local-dev stack: `db` (PostgreSQL 17 + pgvector), `api` (runs `alembic upgrade head`, then uvicorn), `worker` (Procrastinate), optional untested `frontend` profile. Credentials come from `.env`. |
| `.env.example` | Template for the root `.env` read by compose (`POSTGRES_*`, optional session settings). |
| `.gitignore` | Keeps secrets (`.env`), the per-developer `.claude/settings.local.json`, Python caches and local artefacts out of git. |

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
| `milestone/m1.md` | Detailed description of milestone M1 (setup and data model) and the two-developer split. |

## 3. `BD_BACKEND/` configuration and packaging

| File | Purpose and functionality |
|---|---|
| `pyproject.toml` | Package metadata (Python 3.12), runtime dependencies (FastAPI, SQLAlchemy, Alembic, psycopg, Procrastinate, argon2-cffi), dev extras (pytest, httpx, ruff), ruff and pytest settings. |
| `alembic.ini` | Alembic settings (`script_location = migrations`); the database URL is deliberately not here, `migrations/env.py` supplies it. |
| `Dockerfile` | Backend image used for both API and worker; installs the package (dev extras when `INSTALL_DEV=true`), runs as a non-root user, default command starts uvicorn on port 8000. |
| `.dockerignore` | Keeps secrets, virtualenvs and caches out of the image. |
| `.env.example` | Template for a native (non-Docker) `.env`: `DATABASE_URL`, `APP_ENV`, session settings. |
| `temp.md` | Empty placeholder. |

## 4. `BD_BACKEND/app/` (application code)

### `app/__init__.py`, `app/core/__init__.py`, `app/audit/__init__.py`
Package markers so `app.*` imports resolve; they contain only docstrings. No functions.

### Stub packages: `app/{imports,leads,compliance,content,campaigns,outreach,mail,notifications}/{__init__,models}.py`
**Purpose:** added in M1 task A0 so every module has a fixed place before its real code exists. `__init__.py` is a docstring-only package marker; `models.py` is a header-only file with no models yet. Each `models.py` is already imported by `app/models.py`, so the owning task adds its tables there without editing the registry. No functions.

### `app/main.py`
**Purpose:** the FastAPI entry point served by uvicorn (`app.main:app`). Creates the app, installs the error handler and mounts the routes. Holds no business logic. Imported by `tests/test_auth_routes.py` and `tests/test_health.py`. No functions; module-level `app` is the object.

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
**Purpose:** the tables for sign-in: users and their sessions. Created by migrations 0002 and 0003; read by `core/services.py`.

| Name | What it does | Why it is used |
|---|---|---|
| `UserRole` (enum) | `rep`, `manager`, `admin`. | Roles for the permission module (planned); currently only returned in API responses. |
| `User` (table `users`) | id, email, password hash, role, `is_active`, timestamps; email must be lowercase and is unique ignoring case. | The person who signs in. |
| `UserSession` (table `sessions`) | user id, SHA-256 token hash (unique), created/expires/revoked times, with checks. | Server-side sessions that can be expired or revoked; the raw token is never stored. |

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

Alembic calls every `upgrade()`/`downgrade()` itself. Applied migrations are never edited; each model change adds a new one.

## 6. `BD_BACKEND/tests/` (pytest, real PostgreSQL with pgvector)

Common helpers repeated in several files: `_alembic_config(url)` (Alembic config for the test database), an `engine` fixture (migrates the test database once per module), a rolled-back `session` fixture, and an autouse `_reset_clock_offset` fixture (so one test cannot shift time for another). Tests never call external services; data is synthetic.

| File | Purpose and what it covers |
|---|---|
| `conftest.py` | `test_database_url` (session fixture): requires `DATABASE_URL`, drops and creates a throwaway `<name>_test` database and returns its URL, so the dev database is untouched. |
| `test_audit_log.py` | `record()` stores all fields and follows the clock; does not commit; triggers reject UPDATE/DELETE/TRUNCATE; secret keys and unknown actions are rejected; `AuditAction` values are unique and dotted; the audit package does not import `core` modules. Helpers: `_count_rows`. |
| `test_auth_routes.py` | `/auth/login`, `/auth/logout`, `/auth/me` through the real app: no secrets in responses, cookie flags, only the token hash stored, every failure looks identical, one committed audit row per failure, exactly one password check per path, weak hash upgraded, 422 never echoes values, logout idempotent, independent sessions. Fixtures: `api_app`, `use_settings`, `client`, `make_client`, `user`, `disabled_user`; helpers `_login`, `_count_rows`, `_failed_login_rows`, `_cookie_attributes`, `_make_settings`, `_keys_at_any_depth`. |
| `test_clock.py` | `now()` is aware UTC; `set_offset`/`reset_offset` shift and restore it. |
| `test_config.py` | Missing `DATABASE_URL` fails; `psycopg_conninfo`; defaults and env overrides; bad lifetime, cookie name or origin rejected; production rules. Fixture: `base_env`. |
| `test_current_user.py` | A tiny app with protected routes: no, bad, expired, revoked or disabled session all give the same 401; role change visible next request; dependencies cached per request; cookie name from settings; no side effects. Helpers `_sign_in`, `_expire_by_clock`, `_disable`, `_arrange_*`. |
| `test_health.py` | `/health` returns 200 normally and 503 when the database session fails (via dependency override). Fixture: `client`. |
| `factories/__init__.py` | Header-only stub package (M1 task A0); per-module factory files (`core.py`, `leads.py`, ...) are added later. No functions. |
| `test_migration_heads.py` | `test_alembic_has_single_head`: the Alembic history has exactly one head, so parallel migrations that fork the chain fail the build. No database needed. |
| `test_migrations.py` | All migrations apply to an empty database and pgvector is installed. |
| `test_passwords.py` | Argon2id format, no plaintext in hash, salting, unicode, malformed hash returns False, empty password rejected, rehash detection. No database. |
| `test_session_model.py` | `sessions` constraints: unique token hash, foreign key, cascade delete, expiry check, hash length, clock use. Helpers `_new_session`, `_count_sessions`. |
| `test_session_service.py` | Token generation and hashing, `create_session` (hash only, lifetime, inactive user), `get_active_session` (unknown, wrong length with zero SQL, expiry, revoke, disabled user, single joined SELECT, role refresh), `revoke_session`, `revoke_all_user_sessions`. Helpers `_make_user`, `_collect_statements`. |
| `test_user_migration.py` | Users migration upgrades, downgrades and upgrades again; downgrade to 0002 drops `sessions` only. Fixture `roundtrip_url`, helper `_users_table_and_role_type_exist`. |
| `test_user_model.py` | `users` constraints (duplicate and mixed-case emails, unknown role, default active, clock use) and `test_models_match_the_migrated_schema`: autogenerate finds no difference between models and migrations. Helper `_new_user`. |

## 7. `BD_FRONTEND/`

| File | Purpose and functionality |
|---|---|
| `Dockerfile` | Three-stage Next.js build (deps, build, standalone run) written ahead of the app; untested and will fail until `package.json` exists. Used only by the optional `frontend` compose profile. |
| `.dockerignore` | Excludes `node_modules`, build output and env files from the frontend image. |
| `temp.md` | Empty placeholder. |
