# Alphaleo BD

Alphaleo BD is an internal, standalone web app that runs a company's outbound business development from lead list to reply handling: import Apollo or Excel lead files, search and filter leads, create campaigns, have AI draft a three-email sequence per lead, review and approve it, send on a controlled schedule through Microsoft 365, and classify replies. A human approves every email; there is no auto-send. Salesforce is only a searchable attribute on companies, not an integration.

## Status

Planning. The plan and requirements are written; **no application code exists yet** and the setup and run steps below are the intended ones, to be verified and corrected when milestone M1 creates the tooling. Open items are tracked in [docs/plan.md](docs/plan.md) section 17.

## Technology stack

Python 3.12 · FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL 17 with pgvector · Procrastinate (job queue on PostgreSQL) · Next.js + TypeScript · Google Gemini (behind a provider adapter) · Microsoft Graph for sending and reading mail · pytest, ruff, tsc, ESLint, Vitest, Playwright. Exact versions are not pinned yet (open item U1).

## Folder layout

```
BD_BACKEND/    FastAPI API, worker and migrations (empty until M1)
BD_FRONTEND/   Next.js frontend (empty until M1)
docs/          plan.md and requirements/
```

Full structure and where new files go: [FILE_STRUCTURE.md](FILE_STRUCTURE.md).

## Prerequisites (macOS)

Homebrew, PostgreSQL 17 with the pgvector extension, Python 3.12, and a current Node.js LTS. A Gemini API key (free tier for development on test data; paid before any real prospect data) and, from M7, a Microsoft 365 app registration. Secrets go in git-ignored `.env` files; each side gets a `.env.example`.

## Setup, clone to running app (planned, verify in M1)

1. Clone the repository.
2. Create the database and enable pgvector; set `DATABASE_URL` in `BD_BACKEND/.env`.
3. Create a Python 3.12 virtualenv and install the backend dependencies from `BD_BACKEND/pyproject.toml`.
4. Apply migrations with Alembic.
5. Install the frontend dependencies in `BD_FRONTEND/` and set the API base URL in `BD_FRONTEND/.env.local`.

## Running (planned, verify in M1)

Three processes, each in its own terminal:

- **API:** Uvicorn serving `app.main:app` from `BD_BACKEND/`.
- **Worker:** the Procrastinate worker from `app.worker`.
- **Frontend:** the Next.js dev server from `BD_FRONTEND/`.

The exact commands will be recorded here when they exist.

## Tests and checks

From the repository root, `make check` (planned, M1) runs ruff, pytest against a real PostgreSQL with pgvector, tsc, ESLint and the frontend tests. How to run a single test will be recorded here once the tooling exists.

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
