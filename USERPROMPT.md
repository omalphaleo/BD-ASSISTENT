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
