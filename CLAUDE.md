# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project and current state

Alphaleo BD is an internal, standalone web app that runs outbound business development: Apollo/Excel lead import, search, AI-drafted 3-step email sequences, human review, scheduled sending via Microsoft 365, and reply classification. Salesforce is only a filterable technology attribute, not an integration. What the project is and how to run it: `README.md`.

Status: M1 started. Only the backend skeleton exists (FastAPI app, `/health`, config, DB, Alembic, Procrastinate no-op worker, tests, Docker files); no business features and no frontend code yet (`BD_FRONTEND/` holds only an untested Dockerfile). Do not implement beyond what the user has approved, and when asked to "propose first", wait for approval before writing.

Docker (Compose) is now in scope for local development, overriding the "Docker deferred" wording in the plan; see `docs/decisions/0001-2026-11-12-docker-in-scope-for-local-dev.md`. Mac-native setup stays supported.

## Mandatory workflow for every task

### A. Log rules: apply ONLY to `USERPROMPT.md`

1. **Purpose.** `USERPROMPT.md` is an internal, append-only record of the user's original prompts and each task's summary and status. It is record-keeping only, never task context. Never read it for context and never load it at the start of a task or conversation. The only lookup allowed is when appending a new entry: Grep `^## T-` (headings only, never the whole file) to find the last ID and use that ID + 1.
2. **Open the log before starting** any code or documentation task. Append an entry with the next ID, today's date, the user's original prompt verbatim (replace any secret or credential with `[REDACTED]`), and `Status: In progress`. Skip logging for simple questions and explanations that need no work.
3. **Close the log after the work.** Append a 2–3 line `Summary` and a `Status update` line (Completed, Blocked or Needs input, with date). Follow-up prompts on the same task are appended as new lines under it or as a new entry.
4. **Never edit, overwrite, reorder or delete earlier entries.**

### B. Task rules: apply ONLY to the work itself (code and docs), never to the log

1. **Perform the task.** Understand the current request, inspect the relevant project files first, and change only what the task needs. Use the current prompt and project files as guidance, not `USERPROMPT.md`.
2. **Keep docs in sync** in the same task that changes the code (ownership table below).
 Documentation describes what exists; mark anything not built as "planned".
3. **Follow the approved stack.** Never add a dependency, tool, framework or service that the plan does not list without asking first. Exact version pins are still open (`docs/plan.md` U1); propose them, don't guess.

### C. Order of work

Open the log (A2), do the task (B1–B3), then close the log (A3).

## Documentation ownership (one home per topic; link, don't copy)

| Topic | Owner |
|---|---|
| Requirements and decisions (D-001…D-113) | `docs/requirements/Q-A.md` (wins over the plan if they disagree) |
| Roadmap, rationale, open items, risks, test and deploy plans | `docs/plan.md` |
| How the system is built (modules, data flow, API, DB, AI) | `ARCHITECTURE.md` |
| Where files live and where new ones go | `FILE_STRUCTURE.md` |
| Prompts sent to AI SDK/API calls, with versions | `PROMPT.md` |
| Development task history | `USERPROMPT.md` |
| Human entry point and setup | `README.md` |
| Rules for Claude and coding standards | this file |

Plan labels: `[AGREED]`, `[ASSUMPTION]`, `[SUGGESTION]`, `[UNRESOLVED]`. Never invent answers for `[UNRESOLVED]` items. Cite decision numbers (e.g. D-008) when changing requirement-driven behaviour.

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

**Layering (backend, Python 3.12, FastAPI)**
- Business logic lives in `services.py`. Route handlers (`api.py`) and Procrastinate tasks are thin wrappers that call services.
- Respect the module dependency direction in `ARCHITECTURE.md`; no upward imports. `audit` is a leaf that anything may call.
- Pydantic v2 schemas at the API boundary; SQLAlchemy 2.x models; type hints on public functions; `ruff` clean.
- Time comes only from `core.clock.now()`. Never call `datetime.now()` or read the system clock directly. Store UTC; convert to the prospect's zone only at scheduling.
- One eligibility service (`compliance`) for search, campaigns, drafting and sending. Each rule is defined once as a SQL expression plus a record check, with a parity test.
- Permissions are enforced server-side through the central permission module and re-checked in services (object-level). Hiding a button in the UI is never access control.
- Every model change has an Alembic migration. Never edit an applied migration; destructive changes use expand-then-contract.
- Anything that can run twice (jobs, sends, imports) must be idempotent. The only outgoing queue is `outreach_messages`: claim with `FOR UPDATE SKIP LOCKED`, use idempotency keys, and recheck eligibility, opt-out and limits at send time.
- Sensitive actions write an audit event (approval, export, merge, opt-out removal, erasure, settings change, real-sending activation).
- Config comes from environment variables via `config.py`, failing fast when missing. Logs are structured and never contain lead data, prompts with lead data, or credentials.

**AI calls**
- Only the `ai` adapter talks to a provider. Every call names a prompt **ID and version** from `PROMPT.md`; changing a prompt creates a new version, old versions stay. Log prompt ID, version, model, latency and token counts.
- Payloads are built from an allow-list: never email addresses, phone numbers or LinkedIn URLs. Output is schema-validated JSON; invalid JSON is a failure, never text to use.
- AI never writes SQL and its free text is never executed. Fixed email sections (greeting, call to action, signature, footer) are never AI-written or rep-editable, and the server rejects tampered edits.

**Frontend (`BD_FRONTEND`, Next.js + TypeScript)**
- No business rules. The API client is generated from the FastAPI OpenAPI schema; never hand-edit generated code.
- Generated email HTML (preview, Outbox) is shown in a sandboxed iframe or sanitised, never injected raw. CSV exports must neutralise formula injection.

**Data rules**
- Raw import rows are immutable; only erase-person removes them. Unified lead data keeps the latest values only, no change history (D-008).
- Opt-outs are stored per email address and are the only enforced suppression (D-066). Customer, partner and competitor are filterable status flags.
- Real sending stays blocked behind the compliance gate (D-081); until then email goes only to the admin test-recipient list. Auto-send is out of scope (D-019, D-091).

**Tests and Definition of Done**
- Every business rule has an automated test. Database tests run against real PostgreSQL with pgvector (not SQLite). Tests never call Gemini or Microsoft: use fakes or recorded responses. Test data is synthetic.
- A task is done when: code merged cleanly, `make check` green, tests for each rule touched, permission checks present and tested, audit events added, no secrets or personal data in code, logs or fixtures, migrations apply on an empty DB, and the owning docs are updated.

## Commands

Backend commands (Docker and native) are in `README.md`; single test: `pytest tests/test_health.py::test_health_ok`. The plan's root `Makefile` / `make check` (ruff, pytest, tsc, ESLint, frontend tests) is still planned.
