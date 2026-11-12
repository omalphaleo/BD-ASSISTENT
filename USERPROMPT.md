# USERPROMPT.md

Task history for development prompts given to Claude Code. **Append-only**: never overwrite, reorder or delete earlier records. The workflow that Claude must follow is in `CLAUDE.md`. AI SDK prompts do not belong here; they live in `PROMPT.md`.

## Entry format

```
## T-NNN: <short title>
- Date: YYYY-MM-DD
- Status: In progress
- Original prompt:
  > <the user's prompt, verbatim; secrets replaced with [REDACTED]>
- Summary: <added when finished: 2–3 lines on what was done>
- Status update (YYYY-MM-DD): Completed | Blocked | Needs input — <reason if not Completed>
```

Rules: add the entry before starting work with `Status: In progress`. When finished, append the `Summary` and `Status update` lines below it. Follow-ups on the same task are appended as `- Follow-up prompt (date): ...` lines. IDs are sequential and never reused. Entries from before this file existed were backfilled on 2026-11-12 and are marked as such.

---

## T-001: Read the plan and BD answers (backfilled)
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > read '/Users/omsaraswat/Desktop/BD ASSISTANT/plan_v0.3.md' and '/Users/omsaraswat/Desktop/BD ASSISTANT/BD-Ans-2026-10-23-R1.docx'
- Summary: Read both files in full and summarized them, listing where the BD answers conflicted with the plan and which plan items they resolved. No files changed.
- Status update (2026-11-12): Completed

## T-002: Read Q-A as reference (backfilled)
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > read '/Users/omsaraswat/Desktop/BD ASSISTANT/Q-A 1.md' for your reference
  > (repeated once as: '/Users/omsaraswat/Desktop/BD ASSISTANT/Q-A 1.md' read for your references)
- Summary: Read the consolidated Q&A (D-001 to D-113), retracted conflicts it resolved, and listed the remaining conflicts and open items. Flagged that Q-A claimed M2/M3 were built while the plan said no code exists.
- Status update (2026-11-12): Completed

## T-003: Revise the plan from Q-A (backfilled)
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > there is no code we have to start from scratch, treat q-a 1.md as an requirements and you can change plan_v0.3.md
- Summary: Edited the plan in place to v0.4 so it follows Q-A: removed lead change history, added Touch and status flags, aligned erasure, sending, reply, import, validation and permission rules, and rewrote the open-items and decisions sections.
- Status update (2026-11-12): Completed

## T-004: Initialize CLAUDE.md (backfilled)
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > /init (the standard "analyze this codebase and create a CLAUDE.md" initialization prompt)
- Summary: Found no code, so wrote CLAUDE.md covering the planning-phase state, document precedence, planned architecture and cross-cutting rules, with no invented commands.
- Status update (2026-11-12): Completed

## T-005: Establish development guidelines and documentation set
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > I want to establish standardized development guidelines and documentation for this project.
  > Please implement the following:
  > CLAUDE.md: Add coding standards and mandatory instructions that Claude Code must follow while working on this project.
  > USERPROMPT.md: Create a centralized task management file where every development prompt or task I provide to Claude Code is recorded. Claude Code must read the task, understand the requirements, implement them, and append a concise 2–3 line summary of what was completed. Maintain a history of original prompts, execution summaries, task status, and dates. Never overwrite or delete previous task records.
  > PROMPT.md: Create a centralized prompt management and versioning system for all prompts used inside AI SDK/API calls. Maintain each prompt's unique ID, version, system prompt, user prompt/template, input schema, expected output schema, purpose, model compatibility, and version change history. Every SDK call must reference a specific prompt ID and version. Any prompt modification must create a new version while preserving previous versions.
  > FILE_STRUCTURE.md: Document the complete project folder structure and explain the responsibilities of important directories and files. Define where new files, modules, services, and tests should be created.
  > ARCHITECTURE.md: Document the overall application architecture, module responsibilities, service interactions, data flow, API communication, database relationships, and AI integration.
  > 6. README.md: Create the project's entry-point document for humans. It must explain what Alphaleo BD is, the current project status, the technology stack, the high-level folder layout, prerequisites, setup steps (clone to running app), how to run the API, worker and frontend, how to run tests and checks (`make check`), and the milestone list (M1–M8). It must link to CLAUDE.md, USERPROMPT.md, PROMPT.md, FILE_STRUCTURE.md, ARCHITECTURE.md and docs/plan.md instead of repeating their content.
  > Important instructions: First inspect the existing project structure, codebase, and documentation. Follow the existing technology stack and architectural decisions. Do not modify existing application logic unnecessarily. Do not introduce unnecessary dependencies. Keep documentation consistent with the actual implementation. Avoid duplicating information across documentation files. Ensure these standards are practical and can be followed by all developers working on the project. Ensure USERPROMPT.md and PROMPT.md have separate responsibilities: the former tracks development tasks, while the latter manages AI SDK prompts and their versions.
  > Execution approach: First analyze the existing codebase and propose the documentation structure and implementation plan. Wait for approval before implementing. After approval, create or update only the required documentation and coding-standard files. Do not modify application code.
- Follow-up prompt (2026-11-12): approved, use your recommendations for all five (move docs under docs/, keep BD_BACKEND / BD_FRONTEND, rename CLAUDE.MD to CLAUDE.md, seed PROMPT.md with draft entries, backfill USERPROMPT.md).
- Summary: Moved the plan, Q&A and docx under docs/ (plan paths and folder names updated to BD_BACKEND / BD_FRONTEND), renamed CLAUDE.MD to CLAUDE.md, and rewrote it with the mandatory workflow, doc-ownership table and coding standards. Created USERPROMPT.md (backfilled T-001 to T-005), PROMPT.md (three draft prompt entries), FILE_STRUCTURE.md, ARCHITECTURE.md and README.md. No application code touched.
- Status update (2026-11-12): Completed

## T-006: Backend initialization (FastAPI) plus Docker setup
- Date: 2026-11-12
- Status: In progress
- Original prompt:
  > Read docs/plan.md (v0.3) and CLAUDE.md.
  > We are starting the Alphaleo BD project from scratch. There is no existing repository structure or backend implementation.
  > Objective: Basic Backend Initialization plus Docker setup
  > Set up the backend using FastAPI, following the technology stack, folder structure (section 5.4), and M1 backend setup requirements defined in docs/plan.md.
  > Scope:
  > 1. Initialize the FastAPI project.
  > 2. Create the required backend folder structure.
  > 3. Configure dependencies and environment variables.
  > 4. Create the application entry point.
  > 5. Add a basic /health endpoint.
  > 6. Configure database connectivity and migration tooling.
  > 7. Set up basic testing configuration.
  > 8. Docker setup, separate for backend and frontend:
  >    - backend/Dockerfile for the API and worker (same image, different start command), with a .dockerignore.
  >    - frontend/Dockerfile with its own .dockerignore. The frontend does not exist yet, so create only the Dockerfile and mark it as untested until the Next.js skeleton is added later.
  >    - A docker-compose.yml at the project root for local development with these services: PostgreSQL 17 with pgvector (use the pgvector/pgvector:pg17 image), api, worker, and frontend (the frontend service must be optional or commented out until the frontend exists).
  >    - Environment variables come from .env files. Never put secrets in Dockerfiles or compose.
  >    - The database must not be exposed beyond localhost.
  > Restrictions:
  > - No business logic or application feature implementation.
  > - No frontend application code, only its Dockerfile.
  > - Nothing from M2 or later.
  > - Do not assume existing code or files beyond the provided documentation.
  > - The plan and CLAUDE.md defer Docker to staging. I am overriding that now. Record this change as a dated entry in docs/decisions/ and add one line to CLAUDE.md saying Docker is now in scope for local development. Do not edit docs/plan.md.
  > - Mac-native setup (Homebrew PostgreSQL, virtualenv) must still work as an alternative, and the README setup steps should cover both.
  > Workflow: 1. Read and understand the documentation. 2. Show me a short implementation plan. 3. Wait for my approval before making changes. 4. After approval, initialize the backend and Docker files. 5. Verify application startup, /health, migrations, tests, and `docker compose up` for the database, api and worker. 6. Provide a concise summary of created files and verification results. Do not create or modify any files before my approval.
- Follow-up prompt (2026-11-12): plan approved (keep BD_BACKEND / BD_FRONTEND, pydantic-settings accepted by approval).
- Summary: Created the FastAPI backend skeleton in BD_BACKEND (config, DB, Alembic with a pgvector migration, /health, Procrastinate no-op worker, 5 tests), backend and frontend Dockerfiles, and a root docker-compose.yml (db pg17+pgvector bound to 127.0.0.1, api, worker, frontend behind a profile). Recorded the Docker override in docs/decisions/0001 and CLAUDE.md; updated README (Docker and Mac-native paths) and FILE_STRUCTURE.
- Status update (2026-11-12): Completed. Verified in Docker: compose up (db, api, worker), /health 200 and 503, migrations, 5 tests, ruff. Not verified: frontend Dockerfile (no app yet) and the Mac-native path (host has no Python 3.12 or psql).
