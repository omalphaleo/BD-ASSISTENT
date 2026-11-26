# FILE_STRUCTURE.md

Where things live and where new things go. Module responsibilities and dependencies are in `ARCHITECTURE.md`; do not repeat them here. "Exists" means present today; "planned" is created by the milestone shown (`docs/plan.md` section 16). Update this file in the same change that adds, moves or removes a file or folder.

## Project root

```
BD ASSISTANT/                  # project root
├── CLAUDE.md                  # exists: rules and coding standards for Claude Code
├── README.md                  # exists: human entry point and setup
├── USERPROMPT.md              # exists: append-only development task history
├── PROMPT.md                  # exists: versioned AI SDK prompt registry
├── FILE_STRUCTURE.md          # exists: this file
├── filedescription.md         # exists: per-file purpose list (snapshot of tracked files)
├── ARCHITECTURE.md            # exists: how the system is built
├── database.md                # exists: beginner-friendly reference of every database model and field
├── Makefile                   # planned (M1): `make check` runs all lint, type and test steps
├── Makefile                   # exists (B5): thin `make check` wrapper around scripts/check.sh
├── scripts/check.sh           # exists (B5): all lint, type and test steps; `bash scripts/check.sh` works without make
├── docker-compose.yml         # exists: local dev (db pgvector/pg17, api, worker, optional frontend profile)
├── .env.example               # exists: variables for compose (POSTGRES_*); real .env is git-ignored
├── .gitignore                 # exists
├── .claude/                   # exists: shared Claude Code config (settings.json, skills/ai-adapter, skills/outreach-compliance)
├── docs/
│   ├── plan.md                # exists: implementation plan (roadmap, rationale, open items)
│   ├── requirements/
│   │   ├── Q-A.md             # exists: requirements source of truth (D-001…D-113)
│   │   └── BD-Ans-2026-10-23-R1.docx   # exists: original BD answers, superseded by Q-A.md
│   └── decisions/             # exists: one short file per significant technical decision (0001 = Docker for local dev, 0002 = A2 core tables decisions)
├── milestone/                 # exists: one detailed description per milestone (m1.md; M2–M8 planned)
├── BD_BACKEND/                # exists: backend skeleton (see below)
└── BD_FRONTEND/               # exists: Next.js + TypeScript skeleton (B1); API client, login and tests planned
```

## BD_BACKEND (M1)

Exists today: `pyproject.toml`, `.env.example`, `alembic.ini`, `Dockerfile`, `.dockerignore`, `temp.md` (empty scratch), `migrations/` (also `migrations.md`) (env, template, `0001` enabling pgvector, `0002` users table and `user_role` enum, `0003` sessions table, `0004` append-only `audit_log` table with triggers, `0005` settings, clock_offsets and job_locks tables, `0006` the 16 leads tables, `0007` the six imports tables, the `raw_rows` immutability trigger and `quarantine_records.raw_row_id`, `0008` the four compliance tables and the seeded gate and checklist rows, `0009` the nine content tables, `0010` the five campaigns tables, `0011` the three outreach tables, `0012` the six mail tables, `0013` the two notifications tables), `app/{main,config,db,worker}.py`, `app/export_openapi.py` (writes/checks the committed `openapi.json`, the frontend's API contract), `openapi.json`, `app/core/api.py` (`/health`, `/auth/login`, `/auth/logout`, `/auth/me`, and the `/users` routes of M1 task A7), `app/core/user_services.py` (user list, create, change role, deactivate, reactivate with admin safeguards and audit; A7), `app/core/clock.py` (`now()` with test offset), `app/core/model_helpers.py` (shared `enum_column`, `in_check`, `TimestampMixin`, `uuid_pk`), `app/core/models.py` (`User`, `UserRole`, `UserSession`, `Setting`, `ClockOffset`, `JobLock`), `app/core/passwords.py` (Argon2id hashing), `app/core/login_throttle.py` (failed-login limits per account and address, counted from audit rows; M1 task A9), `app/core/csrf.py` (CSRF token, Origin check and the app-level `verify_csrf` guard; M1 task A8), `app/core/schemas.py` (`LoginRequest`, `UserResponse`, `SessionUserResponse`, `UserDetailResponse`, `CreateUserRequest`, `ChangeRoleRequest`, `ValidationErrorResponse`, `ErrorResponse`), `app/core/cookies.py` (set and clear the session cookie), `app/core/errors.py` (422 handler that never echoes submitted values; fixed 403 handler), `app/core/permissions.py` (central permission module: `Permission` table, `require_permission`, `public_route`, owner-only check, OpenAPI 401/403; M1 task A6), `app/core/services.py` (session create, lookup and revoke; `login`, `logout`, `normalize_email`), `app/core/dependencies.py` (`get_current_session`, `get_current_user`, `CurrentUser`), `app/models.py` (registry importing every module's `models.py` so Alembic and tests see the whole schema; frozen after M1 task A0), `app/audit/{__init__,models,services}.py` (`AuditLog`, `AuditAction`, `record()`), `app/leads/models.py` (the 16 leads models: `Company`, `Person`, `PersonEmail`, `PersonPhone`, `SocialProfile`, `ContactChannel`, `QuarantineRecord`, `DuplicateCandidate`, `MergeRecord`, `Segment`, `LeadNote`, `LeadEvent`, `Touch`, `LeadStatusFlag`, `IndustryMapping`, `StateMapping`), `app/imports/models.py` (the six imports models: `SourceProfile`, `ImportFile`, `ColumnMapping`, `RawRow`, `ImportReport`, `ImportChange`, plus `ImportStatus`), `app/compliance/models.py` (the four compliance models: `OptOut`, `ComplianceGateStatus`, `ComplianceChecklistItem`, `ErasureRecord`, plus `OptOutSource`, `ChecklistItemKey`), `app/content/models.py` (the nine content models: `VoiceSetting`, `SizeProfile`, `IndustryProfile`, `KnowledgeItem`, `KnowledgeEmbedding`, `IndustryProfileItem`, `EmailStructure`, `StructureSection`, `ConfigVersion`, plus their enums), header-only stub packages `app/{campaigns,outreach,mail,notifications}/{__init__,models}.py`, `app/{imports,leads,compliance,content}/__init__.py`, `tests/factories/__init__.py` (empty package), and `tests/` (`conftest.py`, `test_migration_heads.py` (single Alembic head), `test_openapi_export.py` (`openapi.json` is current), health, config, migrations, clock, user model, user migration, `test_session_model.py`, `test_passwords.py`, `test_session_service.py`, `test_current_user.py`, `test_permissions.py`, `test_permission_matrix.py` (role-by-endpoint matrix), `test_users_api.py` (the `/users` API), `test_csrf.py` (CSRF token, Origin check and CORS), `csrf_client.py` (test client that adds the CSRF header), `test_audit_log.py`, `test_auth_routes.py`, `test_setting_model.py`, `test_clock_offset_model.py`, `test_job_lock_model.py`, `test_core_tables_migration.py`, `test_company_person_models.py`, `test_leads_review_models.py`, `test_leads_activity_models.py`, `test_leads_tables_migration.py`, `test_imports_models.py`, `test_imports_tables_migration.py`, `test_compliance_models.py`, `test_compliance_tables_migration.py`). Everything else in the tree below is planned.

```
BD_BACKEND/
├── pyproject.toml             # exists: dependencies, ruff and pytest configuration
├── .env.example               # exists: every variable, no values; .env is git-ignored
├── alembic.ini                # exists
├── Dockerfile                 # exists: API/worker image
├── .dockerignore              # exists
├── openapi.json               # exists: committed API contract for the frontend (regenerated by app/export_openapi.py)
├── temp.md                    # exists: empty scratch file, not part of the product
├── migrations/                # exists: Alembic
│   ├── env.py, script.py.mako # exists
│   ├── migrations.md          # exists: plain-language explainer of migrations
│   └── versions/              # exists: 0001 pgvector, 0002 users, 0003 sessions, 0004 audit_log, 0005 core tables, 0006 leads tables, 0007 imports tables, 0008 compliance tables, 0009 content tables, 0010 campaigns tables, 0011 outreach tables, 0012 mail tables, 0013 notifications tables; 0014+ planned
├── app/
│   ├── __init__.py            # exists
│   ├── main.py                # exists: FastAPI app and router registration
│   ├── config.py              # exists: settings from environment, fail fast
│   ├── db.py                  # exists: engine, session, base model
│   ├── worker.py              # exists: Procrastinate app and task registration
│   ├── export_openapi.py      # exists: writes/checks openapi.json
│   ├── models.py              # exists: registry importing every module's models (frozen after A0)
│   ├── core/                  # exists: api, clock, cookies, dependencies, errors, model_helpers, models, passwords, schemas, services, tasks (sample job, A10); permissions planned
│   ├── audit/                 # exists: models, services (append-only audit log)
│   ├── imports/               # exists: models (6 tables: files, source profiles, mapping, raw rows, reports, changes); planned: services (upload, validation), api
│   ├── leads/                 # exists: models (16 tables); planned: services (matching, merge), search, api
│   ├── compliance/            # exists: models (4 tables: opt-outs, gate status, checklist items, erasure records); planned: services (eligibility, opt-outs, erasure, gate), api
│   ├── content/               # exists: models (9 tables: voice, size and industry profiles, knowledge items and embeddings, profile-item link, email structures and sections, config versions); planned: services (knowledge lifecycle, embedding, retrieval, versioning), api
│   ├── campaigns/             # exists: models (5 tables: campaigns, campaign leads, email sequences, email drafts, validation results); planned: services (creation, selection, drafting, review queue), api
│   ├── outreach/              # exists: models (3 tables: mailboxes, outreach messages, send attempts); planned: services (plan messages, scheduler, limits, retries), api
│   ├── mail/                  # exists: models (6 tables: mail threads, outbox copies, inbound replies, delta cursors, reply classifications, bounces); planned: Sender interface, MockSender, GraphSender, reply monitor, threading
│   ├── notifications/         # exists: models (2 tables: notifications, SLA reminders); planned: in-app and email notifications, SLA reminders, dashboard queries
│   └── ai/                    # planned: provider adapter, tasks, payload builders, validators, retrieval, prompt loader
└── tests/                     # exists: flat test_*.py files, conftest.py, factories/ (`__init__`, `common`, `core`, `leads`, `imports`, `compliance` since A11; `content`, `campaigns`, `outreach`, `mail`, `notifications` since B11), test_factories.py, test_b_factories.py, test_b_schema_gaps.py, test_schema_rule_gaps.py, test_sample_job.py; per-module folders planned
```

Each module folder holds `models.py`, `schemas.py`, `services.py`, `api.py` (router), and `tasks.py` if it has background jobs.

## BD_FRONTEND (skeleton since B1, generated API client since B2, layout, login and empty shells since B3, tests since B4, CSRF in the client since B12)

```
BD_FRONTEND/
├── package.json
├── next.config.ts
├── vitest.config.mts          # Vitest config (B4): jsdom, "@" alias, runs tests/unit only
├── vitest.setup.ts            # jest-dom matchers and cleanup after each test (B4)
├── playwright.config.ts       # Playwright config (B4): Chromium, starts the frontend, loads .env.local
├── openapi-ts.config.ts       # generator config (B2): reads ../BD_BACKEND/openapi.json
├── scripts/check-api.mjs      # fails when the generated client is stale (npm run check:api)
├── .env.local.example         # API base URL (+ optional server-side API_INTERNAL_URL); no secrets
├── src/
│   ├── app/                   # App Router routes
│   │   ├── globals.css        # the one global stylesheet (plain class names, no modules)
│   │   ├── login/             # public login page
│   │   └── (app)/             # route group: every signed-in screen; layout.tsx checks /auth/me server-side
│   │       └── leads/ campaigns/ review/ outbox/ admin/ users/ profile/   # empty shells (B3)
│   ├── components/            # shared UI: AppShell, NavBar, LoginForm, LogoutButton, PlaceholderPage; later tables, filter chips, email preview
│   └── lib/
│       ├── api/               # typed client generated from the FastAPI OpenAPI schema; never hand-edited
│       ├── api-client.ts      # hand-written setup (base URL, cookies, CSRF fetch, 401 redirect); pages import the API from here
│       ├── csrf.ts            # in-memory CSRF token and the fetch that sends X-CSRF-Token (B12)
│       ├── auth-server.ts     # server-only session lookup (cookie forwarded per request)
│       ├── auth-context.tsx   # AuthProvider and useCurrentUser() for client components
│       └── nav-items.ts       # menu entries and the roles that see them (cosmetic)
└── tests/
    ├── unit/                  # Vitest tests (LoginForm, AppShell, nav-items, csrf, auth-and-logout); run by npm test
    └── e2e/                   # Playwright journeys (login.spec.ts, helpers.ts); run by npm run test:e2e
```

## Where new things go

| You are adding | Put it in | Notes |
|---|---|---|
| Business logic | `BD_BACKEND/app/<module>/services.py` | Never in `api.py` or `tasks.py` |
| API endpoint | `BD_BACKEND/app/<module>/api.py`, schemas in `schemas.py` | Declare its permission; the role-by-endpoint matrix test fails otherwise |
| Background job | `BD_BACKEND/app/<module>/tasks.py`, registered in `worker.py` | Thin wrapper over a service; idempotent |
| Database table or column | `models.py` in the owning module, plus a new file in `BD_BACKEND/migrations/` | Never edit an applied migration |
| New backend module | `BD_BACKEND/app/<name>/` with the standard files | Add it to the dependency order in `ARCHITECTURE.md` first |
| Cross-module helper | `BD_BACKEND/app/core/` | Only if it holds no business rules |
| AI provider call | `BD_BACKEND/app/ai/` | Must reference a prompt ID and version from `PROMPT.md` |
| Prompt text or schema | `PROMPT.md` (new version, old ones kept); code loader in `BD_BACKEND/app/ai/` | Never a string literal in a service |
| Sender or mail integration | `BD_BACKEND/app/mail/` | Microsoft 365 code stays here |
| Backend test | `BD_BACKEND/tests/<module>/test_*.py`, mirroring `app/` | Cross-module flows in `BD_BACKEND/tests/integration/` |
| Test data and factories | `BD_BACKEND/tests/factories/` | Synthetic only |
| Frontend page | `BD_FRONTEND/src/app/<route>/` | No business rules |
| Frontend component | `BD_FRONTEND/src/components/` | Reusable only; page-specific parts stay beside the page |
| Frontend test | `BD_FRONTEND/tests/` | Playwright journeys in `BD_FRONTEND/tests/e2e/` |
| Seed data (mappings, structures, default voice) | `BD_BACKEND/app/<module>/seed/`, loaded idempotently | |
| Documentation | The owner in the ownership table in `CLAUDE.md` | Link instead of copying |
| Technical decision record | `docs/decisions/NNNN-title.md` | Requirements stay in `docs/requirements/Q-A.md` |

Names inside `BD_BACKEND/app/` and `BD_FRONTEND/src/` are proposals from the plan; if M1 chooses different names, update this file then.
