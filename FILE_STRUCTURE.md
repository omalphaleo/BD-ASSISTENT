# FILE_STRUCTURE.md

Where things live and where new things go. Module responsibilities and dependencies are in `ARCHITECTURE.md`; do not repeat them here. "Exists" means present today; "planned" is created by the milestone shown (`docs/plan.md` section 16). Update this file in the same change that adds, moves or removes a top-level directory or a module.

## Project root

```
BD ASSISTANT/                  # project root
├── CLAUDE.md                  # exists: rules and coding standards for Claude Code
├── README.md                  # exists: human entry point and setup
├── USERPROMPT.md              # exists: append-only development task history
├── PROMPT.md                  # exists: versioned AI SDK prompt registry
├── FILE_STRUCTURE.md          # exists: this file
├── ARCHITECTURE.md            # exists: how the system is built
├── Makefile                   # planned (M1): `make check` runs all lint, type and test steps
├── docker-compose.yml         # exists: local dev (db pgvector/pg17, api, worker, optional frontend profile)
├── .env.example               # exists: variables for compose (POSTGRES_*); real .env is git-ignored
├── .gitignore                 # exists
├── docs/
│   ├── plan.md                # exists: implementation plan (roadmap, rationale, open items)
│   ├── requirements/
│   │   ├── Q-A.md             # exists: requirements source of truth (D-001…D-113)
│   │   └── BD-Ans-2026-10-23-R1.docx   # exists: original BD answers, superseded by Q-A.md
│   └── decisions/             # exists: one short file per significant technical decision (0001 = Docker for local dev)
├── BD_BACKEND/                # exists: backend skeleton (see below)
└── BD_FRONTEND/               # exists: only an untested Dockerfile and .dockerignore (Next.js planned M1)
```

## BD_BACKEND (M1)

Exists today: `pyproject.toml`, `.env.example`, `alembic.ini`, `Dockerfile`, `.dockerignore`, `migrations/` (env, template, `0001` enabling pgvector, `0002` users table and `user_role` enum, `0003` sessions table, `0004` append-only audit_log table with triggers), `app/{main,config,db,worker}.py`, `app/core/api.py` (`/health`, `/auth/login`, `/auth/logout`, `/auth/me`), `app/core/clock.py` (`now()` with test offset), `app/core/models.py` (`User`, `UserRole`, `UserSession`), `app/core/passwords.py` (Argon2id hashing), `app/core/schemas.py` (`LoginRequest`, `UserResponse`), `app/core/cookies.py` (set and clear the session cookie), `app/core/errors.py` (422 handler that never echoes submitted values), `app/core/services.py` (session create, lookup and revoke; `login`, `logout`, `normalize_email`), `app/core/dependencies.py` (`get_current_session`, `get_current_user`, `CurrentUser`), `app/models.py` (registry importing every model module so Alembic and tests see the whole schema), `app/audit/{__init__,models,services}.py` (`AuditLog`, `AuditAction`, `record()`), and `tests/` (`conftest.py`, health, config, migrations, clock, user model, user migration, `test_session_model.py`, `test_passwords.py`, `test_session_service.py`, `test_current_user.py`, `test_audit_log.py`, `test_auth_routes.py`). Everything else in the tree below is planned.

```
BD_BACKEND/
├── pyproject.toml             # dependencies, ruff and pytest configuration
├── .env.example               # every variable, no values; .env is git-ignored
├── alembic.ini
├── migrations/                # Alembic revisions
├── app/
│   ├── main.py                # FastAPI app and router registration
│   ├── config.py              # settings from environment, fail fast
│   ├── db.py                  # engine, session, base model
│   ├── worker.py              # Procrastinate app and task registration
│   ├── core/                  # users, roles, permissions, clock, settings store, session auth, shared utilities
│   ├── imports/               # files, source profiles, mapping, raw rows, validation, reports
│   ├── leads/                 # people, companies, matching, merge, search, segments, notes, quarantine
│   ├── compliance/            # eligibility service, opt-outs, erasure, real-sending gate
│   ├── content/               # voice, profiles, structures, knowledge base, versions
│   ├── ai/                    # provider adapter, tasks, payload builders, validators, retrieval, prompt loader
│   ├── campaigns/             # campaigns, selection, sequences, review queue
│   ├── outreach/              # outreach_messages queue, scheduler, limits, retries
│   ├── mail/                  # Sender interface, MockSender, GraphSender, reply monitor, threading
│   ├── notifications/         # in-app and email notifications, SLA reminders, dashboard queries
│   └── audit/                 # append-only audit log
└── tests/                     # mirrors app/, plus integration and end-to-end flows
```

Each module folder holds `models.py`, `schemas.py`, `services.py`, `api.py` (router), and `tasks.py` if it has background jobs.

## BD_FRONTEND (planned, M1)

```
BD_FRONTEND/
├── package.json
├── next.config.ts
├── .env.local.example         # API base URL only; no secrets
├── src/
│   ├── app/                   # App Router routes (login, leads, campaigns, review, outbox, admin …)
│   ├── components/            # shared UI: tables, filter chips, forms, email preview
│   └── lib/api/               # typed client generated from the FastAPI OpenAPI schema; never hand-edited
└── tests/                     # Vitest component tests and Playwright journeys
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
