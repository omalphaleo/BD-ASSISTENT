# 0001: Docker is in scope for local development

- Date: 2026-11-12
- Status: Accepted (decided by the project owner in task T-006)
- Overrides: `docs/plan.md` section 5.1 ("Mac-native for MVP ... Docker deferred") and the "Docker deployment" item in section 3.2, as far as *local development* is concerned. `docs/plan.md` is not edited; this record is the override.

## Decision
Docker (Docker Compose) is now in scope for local development: PostgreSQL 17 with pgvector (`pgvector/pgvector:pg17`), the API and the worker (one backend image, two start commands) run from a root `docker-compose.yml`. The frontend has a Dockerfile and an optional compose profile, untested until the Next.js skeleton exists.

## Unchanged
- The Mac-native setup (Homebrew PostgreSQL 17 + pgvector, Python virtualenv, Node.js) remains a supported alternative; the README covers both.
- Docker for staging/production deployment is still governed by plan section 23 and open decision 25.8; this record does not decide it.
- Rules that still apply to the Docker setup: no secrets in Dockerfiles or compose (values come from git-ignored `.env` files), and the database is published on `127.0.0.1` only.

## Why
Faster, reproducible onboarding on any host (the first working environment was built on Windows, where Homebrew is unavailable), and the same image for API and worker.
