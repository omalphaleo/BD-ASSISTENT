# Alphaleo BD

Alphaleo BD is an internal, standalone web app that runs a company's outbound business development from lead list to reply handling: import Apollo or Excel lead files, search and filter leads, create campaigns, have AI draft a three-email sequence per lead, review and approve it, send on a controlled schedule through Microsoft 365, and classify replies. A human approves every email; there is no auto-send. Salesforce is only a searchable attribute on companies, not an integration.

## Status

M1 started. The backend skeleton exists (FastAPI app with `/health`, settings, database connection, Alembic migrations with pgvector, Procrastinate no-op worker, tests) together with Docker files. No business features and no frontend yet; `BD_FRONTEND/` has only an **untested** Dockerfile. The Docker path below was verified; the Mac-native path is documented but not yet verified. Open items are tracked in [docs/plan.md](docs/plan.md) section 17.

## Technology stack

Python 3.12 · FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL 17 with pgvector · Procrastinate (job queue on PostgreSQL) · Next.js + TypeScript · Google Gemini (behind a provider adapter) · Microsoft Graph for sending and reading mail · pytest, ruff, tsc, ESLint, Vitest, Playwright. Exact versions are not pinned yet (open item U1).

## Folder layout

```
BD_BACKEND/         FastAPI API, worker, migrations, tests, Dockerfile
BD_FRONTEND/        Next.js frontend (not built yet; untested Dockerfile only)
docker-compose.yml  local dev: db (pgvector), api, worker, optional frontend
docs/               plan.md, requirements/, decisions/
```

Full structure and where new files go: [FILE_STRUCTURE.md](FILE_STRUCTURE.md).

## Prerequisites

Pick one path. Both use the same code and environment variables (see `docs/decisions/0001-2026-11-12-docker-in-scope-for-local-dev.md`).

- **Docker path:** Docker with Compose v2. Nothing else is needed for the backend.
- **Native path (Mac):** Homebrew, PostgreSQL 17 with the pgvector extension, Python 3.12, and a current Node.js LTS (Node only when the frontend exists).

Later: a Gemini API key (free tier for development on test data; paid before any real prospect data) and, from M7, a Microsoft 365 app registration. Secrets go in git-ignored `.env` files; each side gets a `.env.example`.

## Setup and running: Docker path (verified)

1. Clone the repository.
2. `cp .env.example .env` and fill in `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (compose refuses to start if any is empty).
3. `docker compose up -d --build db api worker`. The API container applies Alembic migrations on start; the worker applies the Procrastinate schema and starts with no tasks.
4. Check: `curl http://localhost:8000/health` returns `{"status":"ok","database":"ok"}` (503 if the database is down). API docs: `http://localhost:8000/docs`.
5. PostgreSQL is published on `127.0.0.1:5432` only. Logs: `docker compose logs -f api worker`. Stop: `docker compose down` (add `-v` to delete the database volume).
6. The `frontend` service is behind the `frontend` profile and its Dockerfile is **untested** until the Next.js skeleton exists.

## Setup and running: Mac-native path (documented, not yet verified)

1. Install and start PostgreSQL 17 with pgvector (`brew install postgresql@17 pgvector`), then create a role and a database.
2. `cd BD_BACKEND`, create a Python 3.12 virtualenv, `pip install -e ".[dev]"`.
3. `cp .env.example .env` and set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/DBNAME`.
4. `alembic upgrade head` (the migration runs `CREATE EXTENSION vector`, which needs a role allowed to create extensions).
5. API: `uvicorn app.main:app --reload`. Worker (separate terminal): `procrastinate --app=app.worker.app schema --apply` once, then `procrastinate --app=app.worker.app worker`.
6. Frontend: not built yet (M1 frontend task).

## Tests and checks

Tests need a reachable PostgreSQL with pgvector; they create and use a throwaway database named `<DB>_test` on the same server, never the development database.

- Docker: `docker compose exec api pytest` and `docker compose exec api ruff check .`
- Native: from `BD_BACKEND/` with the virtualenv active and `DATABASE_URL` set, run `pytest` and `ruff check .`
- Single test: `pytest tests/test_health.py::test_health_ok`

The plan's root `make check` (ruff, pytest, tsc, ESLint, frontend tests) is still planned.

## Milestones

Details and acceptance criteria: [docs/plan.md](docs/plan.md) section 16.

| # | Milestone |
|---|---|
| M1 | Project setup and data model |
| M2 | Import, mapping, validation, quarantine, deduplication |
| M3 | Lead search, lead details, eligibility, opt-outs, exports |
| M4 | Knowledge base, embeddings, AI drafting, validation, review |
| M5 | Sending queue, mock sender, Outbox, scheduler, settings, dashboard |
| M6 | Reply handling, classification, notifications, SLA |
| M7 | Microsoft Graph integration |
| M8 | Compliance gate and controlled real sending |

## Documentation

- [CLAUDE.md](CLAUDE.md): rules and coding standards for Claude Code, and which document owns which topic
- [USERPROMPT.md](USERPROMPT.md): append-only history of development tasks
- [PROMPT.md](PROMPT.md): versioned registry of prompts used in AI calls
- [FILE_STRUCTURE.md](FILE_STRUCTURE.md): folder layout and where new files go
- [ARCHITECTURE.md](ARCHITECTURE.md): modules, data flow, API, database, AI integration
- [docs/plan.md](docs/plan.md): implementation plan, roadmap and open items
- [docs/requirements/Q-A.md](docs/requirements/Q-A.md): requirements and decisions
