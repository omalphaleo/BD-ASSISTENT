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

## T-007: Clarify task vs USERPROMPT.md in CLAUDE.md workflow
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > (Follow-ups on the "Mandatory workflow for every task" section of CLAUDE.md.) like the 3 and 4th point is saying about the task not the userprompt.md that is confusing
  > its confusing , to add between that , add that one clearly at the last point
  > make claude.md edit like add that in thr last point of last and somwehat crtly write give this is wrt to userprompt.md wrt to task like that specify correctly everything which u write
- Summary: Added point 8 at the end of the "Mandatory workflow" list in CLAUDE.md. It states which steps are about the task (3, 6, 7) and which are about the USERPROMPT.md log (1, 2, 4, 5), and that step 4 means finishing the work and then closing its log entry. Steps 1-7 are unchanged.
- Status update (2026-11-13): Completed

## T-008: Stop auto-reading USERPROMPT.md in CLAUDE.md workflow
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > Read USERPROMPT.md first (at least the last few entries) for context and the next task ID. this is in the claude.md if it read the entries everytime the context memory will get full, and have not specified the entries also, is this the crt way to write or any change needed?
  > the read point which we gave in claude.md no need of that, dont want to read that for evry task, it is only for the userprompt.md, dont load that one in everytask and every convo
  > The read point specified in CLAUDE.md is not required for every task or conversation. It should apply only to userprompt.md. Do not load or read userprompt.md automatically for every task or conversation
- Summary: Replaced workflow step 1 in CLAUDE.md. USERPROMPT.md is no longer read for context or loaded at the start of a task or conversation. The only allowed lookup is a Grep of `^## T-` headings when appending a new entry, to get the next ID. Other steps and the step 8 references are unchanged.
- Status update (2026-11-13): Completed

## T-009: Split CLAUDE.md workflow into log rules vs task rules
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > 1. **USERPROMPT.md purpose:** This file is an internal, append-only log used to store the user's original prompts and task completion summaries. It is only for record-keeping, not task context.
  > 2. **Log tasks:** Before starting any code or documentation task, append a new entry with the next ID, today's date, the user's original prompt verbatim (redact secrets as `[REDACTED]`), and `Status: In progress`. Skip logging for simple questions and explanations.
  > 3. **Update task status:** After completing the work, append a brief 2–3 line summary and update the status to `Completed`, `Blocked`, or `Needs input`, with the date. Never edit existing entries.
  > 4. **Perform tasks:** Understand the current request, inspect relevant project files, and make only the necessary changes.
  > 5. **Keep documentation in sync:** Update relevant documentation whenever code changes affect it. Describe implemented functionality accurately and mark unfinished features as `Planned`.
  > 6. **Follow the approved technology stack:** Do not introduce dependencies, tools, frameworks, or services outside the project plan without asking the user. Exact version pins remain open under `docs/plan.md` U1; propose versions rather than assuming them.
  > 7. **Separate task execution and logging:** Use the current prompt and project files to guide implementation. `USERPROMPT.md` is only for recording prompts, summaries, and task statuses.
  > c this it is crt only specify which file belong to what dont mix up the instructions specific whih=ch instruction for what and then there should not be any ambuiguity for this
- Summary: Rewrote the "Mandatory workflow" section of CLAUDE.md into A (log rules, only for USERPROMPT.md), B (task rules, only for the work itself) and C (order: open log, do task, close log). The old mixed numbered list and step 8 are removed. No other CLAUDE.md section changed.
- Status update (2026-11-13): Completed

## T-010: Add general coding rules to CLAUDE.md coding standards
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > in the coding standards of claude.md like general stnadards general rules are not specified ## General Coding Standards (12 rules: Readable Code, Comments and Docstrings, Single Responsibility, Reusability, Type Safety, Error Handling, Consistency, Maintainability, No Dead Code, Minimal Changes, Code Review, No Assumptions) ... some of these are needed? to specify which are needed
  > in the coding standards only specify general rules and add those
- Summary: Added a "General rules (all code)" block (12 one-line rules) at the top of "Coding standards" in CLAUDE.md. Existing Layering, AI, Frontend, Data and Tests blocks are unchanged.
- Status update (2026-11-13): Completed

## T-011: Add general coding standards to CLAUDE.md (re-do of T-010; block not present in CLAUDE.md)
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > generaal rules are not specified in claude.md in coding standards ## General Coding Standards
  > 1. **Readable Code:** Write clean, simple, and self-explanatory code. Use meaningful names for variables, functions, classes, and files.
  > 2. **Comments and Docstrings:** Add comments wherever logic is complex, non-obvious, or involves important business decisions. Add docstrings to public functions, classes, and modules where they clarify purpose, parameters, return values, or behaviour. Do not comment every line or repeat what the code already explains.
  > 3. **Single Responsibility:** Each function, class, and module should have one clear responsibility. Avoid unnecessarily large functions and classes.
  > 4. **Reusability:** Avoid duplicate code. Extract common logic into reusable functions or modules instead of repeating implementations.
  > 5. **Type Safety:** Avoid unnecessary `Any`, untyped functions, and implicit assumptions. Define clear input and return types.
  > 6. **Error Handling:** Handle expected errors explicitly. Do not use broad exception handling unless necessary. Never silently suppress errors or expose internal stack traces to users.
  > 7. **Consistency:** Follow existing project naming conventions, formatting, patterns, and API response structures. Do not introduce a new pattern when an established one already exists.
  > 8. **Maintainability:** Avoid hardcoded values, magic numbers, deeply nested conditions, unnecessary abstractions, and overly complicated logic. Use named constants and configuration where appropriate.
  > 9. **No Dead Code:** Remove unused imports, variables, functions, commented-out code, temporary debugging statements, and unnecessary dependencies.
  > 10. **Minimal Changes:** Modify only what is required for the task. Avoid unrelated refactoring, duplicate implementations, or unnecessary file creation.
  > 11. **Code Review:** Before completing a task, review the changes for correctness, readability, security, consistency, and unintended side effects.
  > 12. **No Assumptions:** Do not invent functionality, business rules, API contracts, or database behaviour. Refer to the approved project plan and existing implementation. Ask for clarification when requirements are unclear.like these
- Summary: Added a "General (all code)" block with the 12 supplied rules (verbatim) at the top of "Coding standards" in CLAUDE.md; project-specific blocks unchanged and win on conflict. T-010 had logged this as completed but the block was not in CLAUDE.md.
- Status update (2026-11-13): Completed

## T-012: Review general rules in CLAUDE.md and remove unnecessary ones
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > c all the general rules written crtly if u c this is unnesseray u can remove that general rule
- Summary: Reviewed the 12 general rules against CLAUDE.md. Removed "Minimal Changes" (duplicate of B1) and "No Assumptions" (duplicate of the status paragraph and the [UNRESOLVED] rule); renumbered Code Review to 10. Ten general rules remain.
- Status update (2026-11-13): Completed

## T-013: Clarify queue flow (no service-to-worker arrow) in ARCHITECTURE.md
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > FastAPI → Service layer: Starts an operation. Service layer → Procrastinate: Queues a background job. Worker → Service layer: Executes the actual background operation. Service layer → Database: Reads and saves information.
  > is this the floe to srchitecture.md shape pf the system but here there is no arroe from service to worker process?
- Summary: Confirmed the §1 diagram is correct (PostgreSQL is the queue, so no service-to-worker arrow). Added a one-line "Queue" bullet under the diagram in ARCHITECTURE.md explaining enqueue-as-DB-write and worker polling. Diagram unchanged.
- Status update (2026-11-13): Completed

## T-014: Show enqueue -> worker -> service loop in ARCHITECTURE.md diagram
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > here c here in the shape of the syatem from service layer the data shoulf go to procastinate worker process then come back to service layer the process is Browser – Next.js frontend. You select John and click Compose Email. [10-step compose-email walkthrough: Next.js -> FastAPI -> Campaign Service enqueues job via Procrastinate -> FastAPI returns "queued" -> worker claims job -> service gathers lead info -> AI module -> validators -> PostgreSQL saves draft -> browser displays draft]
- Summary: Replaced the single `W --> SVC` edge in the ARCHITECTURE.md §1 diagram with three labelled edges (1. enqueue job to the DB queue, 2. worker claims job, 3. worker calls service) so the service -> worker -> service loop is visible. The 10-step walkthrough was not added to the docs (some details are unconfirmed decisions).
- Status update (2026-11-13): Completed

## T-015: Show AI result returning to the service layer in ARCHITECTURE.md diagram
- Date: 2026-11-13
- Status: In progress
- Original prompt:
  > like the composed mail from gemini api is never sending back to service layer or postgress database y?
  > ok
- Summary: Made the AI edges in the ARCHITECTURE.md §1 diagram two-way (service <-> AI adapter labelled "request / validated result", AI adapter <-> Gemini) so the generated draft visibly returns to the service layer, which then saves it to PostgreSQL. No other changes.
- Status update (2026-11-13): Completed
