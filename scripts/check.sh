#!/usr/bin/env bash
# The "is it green" check: backend lint and tests, then frontend type check, lint and unit tests (B5).
# Needed so both developers run the same checks before every push; `make check` is a thin wrapper
# around this script, and it also runs directly (bash scripts/check.sh) where make is unavailable.
# Playwright is not included: it needs the full running stack and backend CORS (A8).
set -euo pipefail

# Run from the repository root no matter where the script is called from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { printf '\n==> %s\n' "$1"; }

# Backend steps run in the compose image because pytest needs PostgreSQL with pgvector
# (the tests create a throwaway <DB>_test database, never the development one).
step "Backend: start the database"
docker compose up -d --wait db

# The backend image copies the code at build time (no bind mount), so rebuild it first;
# otherwise ruff and pytest would check a stale snapshot instead of the working tree.
step "Backend: build the image"
docker compose build api

step "Backend: ruff"
docker compose run --rm --no-deps -T api ruff check .

step "Backend: pytest"
docker compose run --rm -T api pytest

# Frontend steps run natively; dependencies must already be installed (npm ci in BD_FRONTEND).
if [ ! -d BD_FRONTEND/node_modules ]; then
  echo "BD_FRONTEND/node_modules is missing: run 'npm ci' in BD_FRONTEND first." >&2
  exit 1
fi

step "Frontend: tsc"
(cd BD_FRONTEND && npm run typecheck)

step "Frontend: ESLint"
(cd BD_FRONTEND && npm run lint)

step "Frontend: Vitest"
(cd BD_FRONTEND && npm test)

printf '\nAll checks passed.\n'
