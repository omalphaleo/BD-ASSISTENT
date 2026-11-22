# 0002: Decisions guiding the A2 core tables (settings, test clock, job locks)

Status: Approved
Scope: M1 – Developer A – A2 implementation
Purpose: These decisions have been agreed upon and must guide the A2 implementation.

- Date: 2026-11-19
- Decided by: the project owner (task T-042)
- Applies to: `Setting`, `ClockOffset` and `JobLock` (migration `0005`, branch `m1/a-core-tables`).
- Related: `docs/plan.md` (section 6.2 `core` tables, section 8 background jobs, sections 11.3-11.4 sending safety and test clock, section 14 item C validation and quarantine), `docs/requirements/Q-A.md` (D-072, D-081, D-083, D-107), `milestone/m1.md` (A2).

This record does not define table columns. The column design for the three tables is a separate proposal that still needs approval. Where this record says "later", the work is outside A2.

---

## Decision 1: Personal email domains and generic email prefixes are admin-editable settings

### Context and problem
Lead import must decide whether an email is a usable work address. Two lists drive that decision: **personal/free-mail domains** (for example `gmail.com`, `yahoo.com`) and **generic role prefixes** (for example `info`, `sales`, `support`). D-072 and D-107 send such addresses to quarantine, where BD adds a work email, releases or discards the row. The plan marks the contents of both lists `[UNRESOLVED]` and suggests making them admin-editable settings. The lists will not stay fixed: new free-mail providers appear, and a prefix that is noise for one industry may be a real contact route for another.

### Approved decision
- Store both lists in the `Setting` table, as two settings with list values.
- Admins manage them through the settings screens (M5; the store exists from A2).
- Lead validation and eligibility checks read them from settings, never from constants in code.
- Ship sensible defaults in the initial configuration. The exact default entries are still to be agreed; the values in this record are illustrations only.

### Why this approach was selected
- Business rules change faster than releases. An admin should add `proton.me` to the list without a code change or deployment.
- It keeps one mechanism for configuration (the settings store with a version) instead of a hardcoded list per rule.
- Changes are auditable, because settings changes are an audited action (plan section 14, item S).
- Hardcoding would hide a business rule inside code, which `CLAUDE.md` rule 8 (avoid hardcoded values) discourages.

### Practical BD Assistant examples
- An Apollo export contains `jane.doe@gmail.com` as the only email. The domain is in the personal-domains list, so the row goes to quarantine, and BD can add Jane's work email.
- A row has `info@acme-consulting.com`. The prefix `info` is in the generic-prefix list, so the row is classified as a generic role address and goes to quarantine.
- The admin notices that leads from a new provider, `proton.me`, keep arriving as work emails. They add the domain in settings. The next import classifies those rows correctly, with no deployment.
- A salesforce partner firm uses `sales@partner.com` as the one real contact for the account. The admin can remove `sales` from the generic list, or BD can release the quarantined row. Either path needs no code change.

### Classification does not automatically mean rejection
Matching a list **classifies** the email. It does not reject the lead or the file:
- Files are never rejected as a whole (D-068).
- A matching row goes to quarantine, where BD can add a work email, release or discard it (D-072, D-107).
- Secondary and personal emails are still stored on the person. They are never used for outreach.
- Only a human decision (release or discard) or a later valid work email changes the outcome.

### Implementation implications and constraints
- A2 creates the `Setting` table only. **No seed rows in A2.** The default list contents are unresolved, and seeding belongs to the task that first reads them (M2 import validation).
- The value column must be able to hold a list (JSON-capable). The setting keeps a version, so a change is detectable.
- Reading the lists happens in a service (business logic lives in `services.py`). Validation and eligibility code never imports a constant list.
- Writing the lists is admin-only, server-side permission checked, and writes an audit event. The admin screen follows in M5.
- Compare domains and prefixes case-insensitively, and store normalized values (lowercase, trimmed). The settings service owns that normalization.
- The plan items for these lists (`docs/plan.md` section 14, item C) are to be updated from `[UNRESOLVED]` once the default contents are agreed.

---

## Decision 2: Test clock safety

### Context and problem
`core.clock.now()` is the only permitted source of the current time (CLAUDE.md). It applies an admin test offset so that follow-ups, cooling-off rules and send windows can be tested without waiting days. The same offset in a real mailbox environment is dangerous: an artificial clock changes scheduling, follow-up timing and cooling-off decisions that are meant for real recipients.

### Approved decision
- Admins may modify the test clock during development and testing.
- Changing the clock offset is blocked while real sending is active.
- The offset must be zero before real sending can be activated.
- All of these restrictions are enforced on the backend (service and API), never only in the UI.

### Why this approach was selected
- A shifted clock during real sending can send a follow-up too early, ignore a cooling-off period or send outside the allowed hours. These errors reach real people and cannot be taken back.
- Requiring a zero offset at activation gives one clear starting state: time is real when real mail goes out.
- Backend enforcement matters because hiding a button is not access control (CLAUDE.md, permissions rule).
- Test and demo flows still work. The plan's acceptance ("test clock advances follow-ups", M5 demo) depends on an adjustable clock in test mode.

### Practical BD Assistant examples
- **Testing (allowed):** in the M5 demo, an admin moves the clock forward 3 days. The follow-up 1 message becomes due and appears in the Outbox, with test recipients only (D-081).
- **Blocked:** real sending is active. An admin (or a stray API call) sets the offset to +5 days. The backend rejects it. Otherwise follow-up 2 for 200 contacts could become "due" days early, and the sequence would arrive in one burst.
- **Activation guard:** the offset is still +2 days from earlier testing when someone tries to activate real sending. Activation is refused until the offset is reset to zero. Otherwise "send between 09:00 and 17:00 in the prospect's zone" would be evaluated against the wrong time.
- **Cooling-off:** a prospect was contacted yesterday. A clock shifted +30 days would make them look eligible for a new campaign, breaking the cooling-off rule.

### Implementation implications and constraints
- A2 creates the `ClockOffset` table only. The rule is **not** enforced in A2, because it needs the real-sending flag and the compliance gate (M8), and the admin API and screen (M5).
- `core/clock.py` is **not** rewired to read the table in A2 (it keeps its in-memory offset). Loading the stored offset into `now()` is later work.
- When built, the offset change goes through a service that checks the real-sending state, requires the admin role, writes an audit event and returns a clear error. Real-sending activation checks the offset is zero in the same service layer.
- Only `core.clock.now()` applies the offset. Code must not read the table or call `datetime.now()` directly.
- Tests for the rule (blocked while active, zero required, admin-only) are part of the later task that builds it.

---

## Decision 3: Procrastinate, database idempotency and JobLock each have one job

### Context and problem
The system runs background work on a schedule and after crashes: scheduler ticks, mailbox polling, stuck-message recovery. Duplicate execution can send a duplicate email, record a reply twice or poll one mailbox from two workers. The plan lists three tools that could all be called "locking": Procrastinate queueing locks, database state checks and the `JobLock` table. Without clear roles they overlap and add complexity.

### Approved decision
- **Procrastinate** runs queued jobs and prevents the same queued job from being executed twice (queueing locks keyed on the object).
- **Database idempotency checks** prevent the same business operation from being applied twice, even after retries or crashes.
- **`JobLock`** is used only for application-level coordination, such as preventing overlapping mailbox polling.
- Do **not** build another generic locking mechanism where Procrastinate already provides the needed job-level locking.

### Why this approach was selected
Each mechanism answers a different question:

| Mechanism | Question it answers | Fails safely when |
|---|---|---|
| Procrastinate queueing lock | Is this job already queued or running? | A task is enqueued twice |
| Database idempotency check | Was this operation already applied? | A job reruns after a crash or retry |
| `JobLock` | Is another worker already doing this app-level task? | Two workers start the same poll cycle |

Keeping them separate avoids a home-made lock framework with its own bugs (stale locks, no expiry) and keeps each piece simple to test.

### Practical BD Assistant examples
- **Procrastinate:** the scheduler task for one outreach message is queued twice by a retry. The queueing lock keyed on the message ID lets only one run.
- **Database idempotency:** a worker sends a message to Microsoft 365, then crashes before committing. On retry the service checks the stored message state and Graph ID, and does not send a second email (plan section 11.3).
- **Database idempotency:** a reply is fetched twice. The service sees the message ID already stored and does not create a second reply record or a second classification.
- **`JobLock`:** `poll_mailboxes` runs every 3 minutes, and a slow poll for mailbox A is still running at the next tick. The lock named for mailbox A makes the second run skip A, while mailbox B is polled normally.
- **Not `JobLock`:** claiming due messages uses `SELECT … FOR UPDATE SKIP LOCKED` on the message rows. This is row-level locking in the database, not a use of `JobLock`.

### Implementation implications and constraints
- A2 creates the `JobLock` table only, and keeps it small. It must support an owner and an expiry, so a crashed worker cannot hold a lock forever. The exact columns are a separate proposal.
- A2 does **not** build a locking helper, decorator or framework. The code that uses `JobLock` (for example mailbox polling) comes with the task that needs it.
- Do not use `JobLock` to guard per-message or per-object work that Procrastinate or a row lock already covers.
- Every task is idempotent by design: it checks the current state in the database before it acts, so correctness never depends on a lock alone.
- If a future need does not fit these three, raise it as a new decision. Do not extend `JobLock` into a general mechanism.

---

## Follow-ups outside A2
- Record these decisions in `docs/requirements/Q-A.md` (it wins over the plan on conflict) and update the related `[UNRESOLVED]` and `[SUGGESTION]` labels in `docs/plan.md`, in a separate docs task.
- Agree the default contents of the two email lists before M2 import validation.
- Build the clock-offset service and the real-sending guard with the M5 settings screens and the M8 compliance gate.
