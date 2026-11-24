# Alphaleo BD

Alphaleo BD is an internal, standalone web app that runs a company's outbound business development from lead list to reply handling: import Apollo or Excel lead files, search and filter leads, create campaigns, have AI draft a three-email sequence per lead, review and approve it, send on a controlled schedule through Microsoft 365, and classify replies. A human approves every email; there is no auto-send. Salesforce is only a searchable attribute on companies, not an integration.

## Status

M1 started. The backend skeleton exists (FastAPI app with `/health`, settings, database connection, Alembic migrations with pgvector, Procrastinate no-op worker, tests) together with Docker files. No business features yet; `BD_FRONTEND/` holds a runnable Next.js + TypeScript skeleton (placeholder page only; API client, login and tests come in later M1 tasks). The Docker path below was verified; the Mac-native path is documented but not yet verified. Open items are tracked in [docs/plan.md](docs/plan.md) section 17.

## Technology stack

Python 3.12 · FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL 17 with pgvector · Procrastinate (job queue on PostgreSQL) · Next.js + TypeScript · Google Gemini (behind a provider adapter) · Microsoft Graph for sending and reading mail · pytest, ruff, tsc, ESLint, Vitest, Playwright. Exact versions are not pinned yet (open item U1).

## Folder layout

```
BD_BACKEND/         FastAPI API, worker, migrations, tests, Dockerfile
BD_FRONTEND/        Next.js + TypeScript frontend skeleton
docker-compose.yml  local dev: db (pgvector), api, worker, optional frontend
docs/               plan.md, requirements/, decisions/
```

Full structure and where new files go: [FILE_STRUCTURE.md](FILE_STRUCTURE.md).

## Prerequisites

Pick one path. Both use the same code and environment variables (see `docs/decisions/0001-2026-11-12-docker-in-scope-for-local-dev.md`).

- **Docker path:** Docker with Compose v2. Nothing else is needed for the backend.
- **Native path (Mac):** Homebrew, PostgreSQL 17 with the pgvector extension, Python 3.12, and and Node.js 22 LTS (needed only for the frontend; Node 24 also works).

Later: a Gemini API key (free tier for development on test data; paid before any real prospect data) and, from M7, a Microsoft 365 app registration. Secrets go in git-ignored `.env` files; each side gets a `.env.example`.

## Setup and running: Docker path (verified)

1. Clone the repository.
2. `cp .env.example .env` and fill in `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (compose refuses to start if any is empty).
3. `docker compose up -d --build db api worker`. The API container applies Alembic migrations on start; the worker applies the Procrastinate schema and starts with no tasks.
4. Check: `curl http://localhost:8000/health` returns `{"status":"ok","database":"ok"}` (503 if the database is down). API docs: `http://localhost:8000/docs`.
5. PostgreSQL is published on `127.0.0.1:5432` only. Logs: `docker compose logs -f api worker`. Stop: `docker compose down` (add `-v` to delete the database volume).
6. The `frontend` service is behind the `frontend` profile (`docker compose --profile frontend up --build`, then open `http://localhost:3000`). The compose-built frontend is verified: `/login` returns 200 and `/leads` redirects to `/login` when signed out.

## Setup and running: Mac-native path (documented, not yet verified)

1. Install and start PostgreSQL 17 with pgvector (`brew install postgresql@17 pgvector`), then create a role and a database.
2. `cd BD_BACKEND`, create a Python 3.12 virtualenv, `pip install -e ".[dev]"`.
3. `cp .env.example .env` and set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/DBNAME`.
4. `alembic upgrade head` (the migration runs `CREATE EXTENSION vector`, which needs a role allowed to create extensions).
5. API: `uvicorn app.main:app --reload`. Worker (separate terminal): `procrastinate --app=app.worker.app schema --apply` once, then `procrastinate --app=app.worker.app worker`.
6. Frontend: `cd BD_FRONTEND`, `cp .env.local.example .env.local` (public values only), `npm install`, then `npm run dev` and open `http://localhost:3000`. Checks: `npm run typecheck`, `npm run lint`, `npm run build`. The API client in `src/lib/api/` is generated from `BD_BACKEND/openapi.json` and never hand-edited: run `npm run generate:api` after the backend schema changes, and `npm run check:api` to confirm the committed client is up to date (it needs Node 22.18 or newer). `openapi.json` is read-only for the frontend; pages import the API from `src/lib/api-client.ts`. Signing in: open `http://localhost:3000`; signed-out visitors are sent to `/login`, and after login you see the app shell with empty screens. The Next.js server checks the session itself, so inside Docker set `API_INTERNAL_URL` (compose does this for the `frontend` profile); outside Docker it falls back to `NEXT_PUBLIC_API_BASE_URL`. Logging in from the browser also needs the backend to allow cross-origin requests from the frontend origin (planned backend task A8); until then the login form cannot reach the API.

## Tests and checks

Tests need a reachable PostgreSQL with pgvector; they create and use a throwaway database named `<DB>_test` on the same server, never the development database.

- Docker: `docker compose exec api pytest` and `docker compose exec api ruff check .`
- Native: from `BD_BACKEND/` with the virtualenv active and `DATABASE_URL` set, run `pytest` and `ruff check .`
- Single test: `pytest tests/test_health.py::test_health_ok`

API contract: the frontend client is generated from the committed `BD_BACKEND/openapi.json`. After any endpoint or schema change, run `python -m app.export_openapi` from `BD_BACKEND/` (`--check` only verifies); a test fails while the file is stale.

**Frontend tests** (from `BD_FRONTEND/`):
- `npm test` runs the Vitest component tests in `tests/unit/` (login form, app shell, menu by role). The API client and router are faked, so no backend is needed.
- `npm run test:e2e` runs the Playwright login journey in `tests/e2e/` in Chromium. It needs the real stack, so it is not part of `make check`:
  1. Start PostgreSQL, apply the migrations and start the API (see the setup sections above). The backend must allow the frontend origin (planned task A8); until then the browser login is blocked.
  2. Create two fake test accounts in the test database, one `rep` and one `admin`, and set `E2E_REP_EMAIL`, `E2E_REP_PASSWORD`, `E2E_ADMIN_EMAIL` and `E2E_ADMIN_PASSWORD` in `BD_FRONTEND/.env.local` (git-ignored) or in your shell. Never use real users or passwords.
  3. Once per machine, install the browser: `npx playwright install chromium`. If that download is blocked, set `E2E_BROWSER_CHANNEL=msedge` (or `chrome`) to use an installed browser instead.
  4. Run `npm run test:e2e`. Playwright starts `npm run dev` itself unless the frontend is already running on `http://localhost:3000` (override with `E2E_BASE_URL`).

**All checks in one command** (from the repo root): `make check`, or `bash scripts/check.sh` where make is unavailable (it is the same script). It starts the database, rebuilds the backend image, then runs ruff and pytest in Docker and tsc, ESLint and Vitest in `BD_FRONTEND/` (run `npm ci` there first), stopping at the first failure. Playwright is not included.

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
