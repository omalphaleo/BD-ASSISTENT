# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository.

## Project

Alphaleo BD is an internal, standalone web app for outbound business development: Apollo/Excel lead import, search, AI-drafted 3-step email sequences, human review, scheduled sending via Microsoft 365, and reply classification. Salesforce is only a filterable technology attribute, not an integration. Overview and setup: `README.md`. Status and roadmap: `docs/plan.md`.

Do not implement beyond what the user has approved. When asked to "propose first", wait for approval before writing. Docker Compose is in scope for local dev (`docs/decisions/0001-2026-11-12-docker-in-scope-for-local-dev.md`).

## Workflow for every task

### Log (`USERPROMPT.md` only)
1. `USERPROMPT.md` is an append-only record of prompts and task summaries. Never read it for context. The only lookup allowed: Grep `^## T-` (headings only) to find the last ID, then use ID + 1.
2. Before any code or documentation task, append an entry: next ID, today's date, the user's prompt verbatim (replace secrets with `[REDACTED]`), `Status: In progress`. Skip logging for plain questions and explanations.
3. After the work, append a 2-3 line `Summary` and a `Status update` (Completed, Blocked or Needs input, with date). Follow-up prompts go under the same entry or a new one.
4. Never edit, overwrite, reorder or delete earlier entries.

### Task (code and docs)
1. Inspect the relevant project files first, and change only what the task needs. Use the current prompt and project files as guidance.
2. Update the owning docs (table below) in the same task. Docs describe what exists; mark anything unbuilt as "planned".
3. Use only the approved stack. Ask before adding a dependency, tool, framework or service the plan does not list. Version pins are still open (`docs/plan.md` U1): propose, don't guess.

## Documentation ownership (one home per topic; link, don't copy)

| Topic | Owner |
|---|---|
| Requirements and decisions (D-001...D-113) | `docs/requirements/Q-A.md` (wins over the plan on conflict) |
| Roadmap, rationale, open items, risks, test and deploy plans | `docs/plan.md` |
| How the system is built (modules, data flow, API, DB, AI) | `ARCHITECTURE.md` |
| Where files live and where new ones go | `FILE_STRUCTURE.md` |
| Prompts sent to AI SDK/API calls, with versions | `PROMPT.md` |
| Development task history | `USERPROMPT.md` |
| Human entry point and setup | `README.md` |
| Rules for Claude and coding standards | this file |

Plan labels: `[AGREED]`, `[ASSUMPTION]`, `[SUGGESTION]`, `[UNRESOLVED]`. Never invent answers for `[UNRESOLVED]` items. Cite decision numbers (e.g. D-008) when changing requirement-driven behaviour.

## Skills (load before touching these areas)
- `ai-adapter`: any AI/LLM call, `ai` module, or `PROMPT.md`.
- `outreach-compliance`: eligibility, opt-outs, campaigns, drafting, sending, the `outreach_messages` queue, real-sending activation.

## Coding standards

**General (all code).** These apply to every file; the blocks below add project-specific rules, which win on conflict.
1. **Readable Code:** Write clean, simple, and self-explanatory code. Use meaningful names for variables, functions, classes, and files.
2. **Comments and Docstrings:** Add comments wherever logic is complex, non-obvious, or involves important business decisions. Add docstrings to public functions, classes, and modules where they clarify purpose, parameters, return values, or behaviour. Do not comment every line or repeat what the code already explains.
3. **Single Responsibility:** Each function, class, and module should have one clear responsibility. Avoid unnecessarily large functions and classes.
4. **Reusability:** Avoid duplicate code. Extract common logic into reusable functions or modules instead of repeating implementations.
5. **Type Safety:** Avoid unnecessary `Any`, untyped functions, and implicit assumptions. Define clear input and return types.
6. **Error Handling:** Handle expected errors explicitly. Do not use broad exception handling unless necessary. Never silently suppress errors or expose internal stack traces to users.
7. **Consistency:** Follow existing project naming conventions, formatting, patterns, and API response structures. Do not introduce a new pattern when an established one already exists.
8. **Maintainability:** Avoid hardcoded values, magic numbers, deeply nested conditions, unnecessary abstractions, and overly complicated logic. Use named constants and configuration where appropriate.
9. **Code Review:** Before completing a task, review the changes for correctness, readability, security, consistency, and unintended side effects.

**All code**
- Clear names, type hints on public functions, no unnecessary `Any`. Follow existing patterns; don't introduce a new one when one exists.
- Docstrings and comments only where they explain non-obvious logic or business decisions.
- One responsibility per function and module; extract shared logic instead of duplicating it.
- Handle expected errors explicitly. No broad `except`, no silent suppression, no stack traces shown to users.
- Named constants and config instead of magic numbers.

**Backend (Python 3.12, FastAPI)**
- Business logic lives in `services.py`. Route handlers (`api.py`) and Procrastinate tasks are thin wrappers.
- Follow the module dependency direction in `ARCHITECTURE.md`; no upward imports. `audit` is a leaf anything may call.
- Pydantic v2 at the API boundary, SQLAlchemy 2.x models, `ruff` clean.
- Time comes only from `core.clock.now()`, never `datetime.now()`. Store UTC; convert to the prospect's zone only at scheduling.
- Permissions are enforced server-side via the central permission module and re-checked in services (object-level). Hiding a UI button is not access control.
- Every model change has an Alembic migration. Never edit an applied migration; destructive changes use expand-then-contract.
- Sensitive actions write an audit event.
- Config comes from environment variables via `config.py` and fails fast when missing. Logs are structured and never contain lead data or credentials.

**Frontend (`BD_FRONTEND`, Next.js + TypeScript)**
- No business rules. The API client is generated from the OpenAPI schema; never hand-edit generated code.
- Email HTML is shown in a sandboxed iframe or sanitised, never injected raw. CSV exports neutralise formula injection.

**Data**
- Raw import rows are immutable; only erase-person removes them. Unified lead data keeps the latest values only, no change history (D-008).

## Tests and Definition of Done
- Every business rule has an automated test. DB tests run against real PostgreSQL with pgvector, not SQLite. Tests never call Gemini or Microsoft (use fakes or recorded responses). Test data is synthetic.
- Done means: changes reviewed for correctness, security and side effects; `ruff` and `pytest` green (and `make check` once it exists); tests for each rule touched; permission checks present and tested; audit events added; no secrets or personal data in code, logs or fixtures; migrations apply on an empty DB; owning docs updated.

## Documentation standards

Applies to every file you create or change. Where it is stricter than the general comment and docstring rules under Coding standards, this section wins. Use the codebase's existing conventions: Python 3.12, Google-style docstrings (`Raises:` sections), Alembic migrations, pytest.

**File header (mandatory, all files: source, tests, migrations).** Start every file with a 2–3 line header (module docstring in Python, comment in other languages) that says **what** the file does, **why** the system needs it, and **how** it helps (what depends on it or what workflow it enables). Keep it short; do not restate the code.

```python
"""Argon2id password hashing and verification.

Needed so no plaintext password is ever stored; the login flow and user creation
call hash_password()/verify_password() and never touch the hashing library directly.
"""
```

**Backend functions and logic**
- Every backend function, method and class has a docstring covering purpose, parameters (when not obvious from names and types), return value, and `Raises:` for each exception it raises on purpose.
- Add inline comments that explain **why** non-obvious logic exists: business rules (cite decision numbers, e.g. D-066), edge cases, authentication and login flows, and workarounds. Do not comment self-explanatory lines.

**Tests**
- Every test file has the file header above.
- Every test function has a one-line docstring or comment stating the scenario and the expected outcome (for example `"""Wrong password: verify_password returns False and does not raise."""`).
- Comment non-trivial fakes, mocks, fixtures and setup, saying what they stand in for and why.

**Migrations**
- Every migration starts with a header summarizing the schema or data change and why it is needed (the existing revision docstring is the place for it).
- Comment each significant step (new table, column, index, enum, constraint, data backfill) with its purpose, and note reversibility, locking and data-loss risks, including what `downgrade()` cannot restore. An applied migration is never edited (see Layering), so write these notes when the migration is first created.

**Keep it in sync.** When you change a file's behaviour, update its header and the docstrings and comments of every function you touched in the same task. Documentation that no longer matches the code counts as a defect during the code review in General rule 9.

## Commands
Backend commands (Docker and native) are in `README.md`. Single test: `pytest tests/test_health.py::test_health_ok`. The root `Makefile` / `make check` (ruff, pytest, tsc, ESLint, frontend tests) is planned, not built.
