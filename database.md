<!--
database.md: beginner-friendly reference for every database model in BD Assistant.
Needed so a new developer can learn what each table stores without reading the code first.
Verified against the SQLAlchemy models under BD_BACKEND/app on 2026-11-20 (migrations 0001-0008).
-->

# BD Assistant database models

This file explains every database table ("model") that exists in the code today: what it is for, where it is defined, an example, and every column. It describes what is **built**. Tables that are only planned are listed at the end and are not documented field by field, because they do not exist yet.

## How to read this file

- **Model** = a Python class that SQLAlchemy maps to one PostgreSQL **table**. One row in the table is one object (one user, one company, ...).
- All models inherit from `Base` in `BD_BACKEND/app/db.py`.
- Migrations in `BD_BACKEND/migrations/versions/` create the tables. Rule: never edit a migration that was already applied; add a new one.
- Decision numbers like D-008 point to `docs/requirements/Q-A.md`.

### Conventions shared by most tables

| Convention | Meaning |
|---|---|
| `id` is a UUID | Every table has a random unique `id` made by the database with `gen_random_uuid()`. Helper: `uuid_pk()` in `BD_BACKEND/app/core/model_helpers.py`. |
| `created_at` / `updated_at` | Added by `TimestampMixin` (same helper file). Both are timestamps with time zone, set from `core.clock.now()` (never `datetime.now()`), and `updated_at` refreshes on every change. Tables that use the mixin list these two fields below as "(from `TimestampMixin`)". |
| Fixed-value columns | Columns such as `status` are stored as text plus a named CHECK constraint (not a PostgreSQL enum), so the list of allowed values can grow later. Helpers: `enum_column()` and `in_check()`. The one exception is `users.role`, which is a real PostgreSQL enum named `user_role`. |
| Foreign keys | `ondelete="CASCADE"` = deleting the parent also deletes this row. `SET NULL` = this row stays, the link becomes empty. `RESTRICT` = the parent cannot be deleted while this row exists. |
| Latest values only | Lead data keeps only the newest values, with no change history (D-008). |

## Table of contents

| # | Model | Table | File |
|---|---|---|---|
| 1 | [User](#1-user) | `users` | `app/core/models.py` |
| 2 | [UserSession](#2-usersession) | `sessions` | `app/core/models.py` |
| 3 | [Setting](#3-setting) | `settings` | `app/core/models.py` |
| 4 | [ClockOffset](#4-clockoffset) | `clock_offsets` | `app/core/models.py` |
| 5 | [JobLock](#5-joblock) | `job_locks` | `app/core/models.py` |
| 6 | [AuditLog](#6-auditlog) | `audit_log` | `app/audit/models.py` |
| 7 | [Company](#7-company) | `companies` | `app/leads/models.py` |
| 8 | [Person](#8-person) | `people` | `app/leads/models.py` |
| 9 | [PersonEmail](#9-personemail) | `person_emails` | `app/leads/models.py` |
| 10 | [PersonPhone](#10-personphone) | `person_phones` | `app/leads/models.py` |
| 11 | [SocialProfile](#11-socialprofile) | `social_profiles` | `app/leads/models.py` |
| 12 | [ContactChannel](#12-contactchannel) | `contact_channels` | `app/leads/models.py` |
| 13 | [QuarantineRecord](#13-quarantinerecord) | `quarantine_records` | `app/leads/models.py` |
| 14 | [DuplicateCandidate](#14-duplicatecandidate) | `duplicate_candidates` | `app/leads/models.py` |
| 15 | [MergeRecord](#15-mergerecord) | `merge_records` | `app/leads/models.py` |
| 16 | [Segment](#16-segment) | `segments` | `app/leads/models.py` |
| 17 | [LeadNote](#17-leadnote) | `lead_notes` | `app/leads/models.py` |
| 18 | [LeadEvent](#18-leadevent) | `lead_events` | `app/leads/models.py` |
| 19 | [Touch](#19-touch) | `touches` | `app/leads/models.py` |
| 20 | [LeadStatusFlag](#20-leadstatusflag) | `lead_status_flags` | `app/leads/models.py` |
| 21 | [IndustryMapping](#21-industrymapping) | `industry_mappings` | `app/leads/models.py` |
| 22 | [StateMapping](#22-statemapping) | `state_mappings` | `app/leads/models.py` |
| 23 | [SourceProfile](#23-sourceprofile) | `source_profiles` | `app/imports/models.py` |
| 24 | [ImportFile](#24-importfile) | `import_files` | `app/imports/models.py` |
| 25 | [ColumnMapping](#25-columnmapping) | `column_mappings` | `app/imports/models.py` |
| 26 | [RawRow](#26-rawrow) | `raw_rows` | `app/imports/models.py` |
| 27 | [ImportReport](#27-importreport) | `import_reports` | `app/imports/models.py` |
| 28 | [ImportChange](#28-importchange) | `import_changes` | `app/imports/models.py` |
| 29 | [OptOut](#29-optout) | `opt_outs` | `app/compliance/models.py` |
| 30 | [ComplianceGateStatus](#30-compliancegatestatus) | `compliance_gate_status` | `app/compliance/models.py` |
| 31 | [ComplianceChecklistItem](#31-compliancechecklistitem) | `compliance_checklist_items` | `app/compliance/models.py` |
| 32 | [ErasureRecord](#32-erasurerecord) | `erasure_records` | `app/compliance/models.py` |

All paths above are relative to `BD_BACKEND/`. The registry `BD_BACKEND/app/models.py` imports every module's `models.py` so Alembic and the tests see the whole schema.

## How the tables relate (big picture)

```
users ──< sessions
  │
  ├── owns ──> people ──> companies
  │              │
  │              ├──< person_emails / person_phones / social_profiles
  │              ├──< lead_notes / lead_events / touches / lead_status_flags
  │              ├──< duplicate_candidates, merge_records
  │              └──< raw_rows >── import_files ──< column_mappings
  │                                    │            └── source_profiles
  │                                    └── import_reports ──< import_changes
  └── quarantine_records ── raw_rows
```

`>`/`<` mean "many rows point to one row". Companies also own `contact_channels`.

The compliance tables stand apart on purpose: `opt_outs` is matched to people by email address (not by a link), and `erasure_records` keeps a plain person id with no link, so both outlive the person they refer to. `compliance_gate_status` and `compliance_checklist_items` only point to `users`.

---

# Core module (`app/core/models.py`)

## 1. User

**Model Overview:** A person who can sign in to BD Assistant (a sales rep, a manager or an admin).

**File Location:** `BD_BACKEND/app/core/models.py` (class `User`, table `users`; enum `UserRole`).

**Purpose:** Stores the login identity and role. The role decides what the person may do (permissions are checked server-side). Example: `priya@alphaleo.example` with role `rep` signs in, and the leads she owns point to her `id`. Emails are stored lowercase and are unique ignoring case (a CHECK forces lowercase and a unique index on `lower(email)` blocks case-only duplicates). The table is named `users` because `user` is a reserved word in PostgreSQL.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the user, generated by the database. Other tables point to it. |
| `email` | String(320), required | Sign-in email. Always lowercase; unique regardless of case. |
| `password_hash` | Text, required | Argon2id hash of the password. The plain password is never stored. |
| `role` | PostgreSQL enum `user_role`, required | One of `rep`, `manager`, `admin`. Controls permissions. |
| `is_active` | Boolean, required, default `true` | `false` means the user was deactivated and cannot sign in (users who wrote notes are deactivated, not deleted). |
| `created_at` | DateTime (timezone), required | When the user was created (from `core.clock.now()`). |
| `updated_at` | DateTime (timezone), required | Last time the row changed; refreshes automatically. |

## 2. UserSession

**Model Overview:** One signed-in browser session of a user.

**File Location:** `BD_BACKEND/app/core/models.py` (class `UserSession`, table `sessions`). Named `UserSession` to avoid clashing with SQLAlchemy's `Session`.

**Purpose:** After login the server creates a random token, gives it to the browser in a cookie, and stores only the SHA-256 hash of it here. On each request the server hashes the cookie and looks the row up. A session is active while `revoked_at` is empty and `expires_at` is in the future. Example: Priya logs in on Monday at 09:00 and gets a session expiring in the evening; logging out sets `revoked_at`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the session. |
| `user_id` | UUID, required, foreign key to `users.id` (CASCADE) | The user who owns the session. Deleting the user deletes their sessions. |
| `token_hash` | String(64), required, unique | Hex SHA-256 of the session token (exactly 64 characters). The raw token is never stored. |
| `created_at` | DateTime (timezone), required | When the session started. |
| `expires_at` | DateTime (timezone), required | When the session stops being valid. Must be later than `created_at`. No default: the session service decides the lifetime. |
| `revoked_at` | DateTime (timezone), optional | Set when the session was ended early (logout). Empty means not revoked. |

## 3. Setting

**Model Overview:** One admin-editable configuration value (a key and its value).

**File Location:** `BD_BACKEND/app/core/models.py` (class `Setting`, table `settings`).

**Purpose:** Holds things admins can change without a code release: sending limits, AI model names, feature flags, personal-email-domain and generic-prefix lists. Which keys exist and what shape each value has is decided by the (planned) settings service, so a new setting needs no migration. No rows are seeded yet and no service uses the table yet. Example: key `email.blocked_domains` with value `["gmail.com", "yahoo.com"]`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the setting row. |
| `key` | String(128), required, unique | Name of the setting. Only lowercase letters, digits, underscores and dots (e.g. `email.blocked_domains`). |
| `value` | JSONB, required | The value: a string, number, boolean, list or object. |
| `version` | Integer, required, default `1` | Starts at 1 and must stay at least 1. The settings service (planned) increases it on every change. |
| `created_at` | DateTime (timezone), required | When the setting was created. |
| `updated_at` | DateTime (timezone), required | Last change time; refreshes automatically. |
| `updated_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Last user who changed the value. Stays empty-linked if that user is deleted. |

## 4. ClockOffset

**Model Overview:** The admin "test clock" offset, stored in at most one row.

**File Location:** `BD_BACKEND/app/core/models.py` (class `ClockOffset`, table `clock_offsets`).

**Purpose:** Lets an admin move the app's notion of "now" forward or back for testing scheduled sending. A missing row means offset zero. Today `core.clock` keeps its own in-memory offset and does not read this table yet. The offset must be zero before real sending is activated (decision record 0002). Example: `offset_seconds = 86400` makes the app think it is one day later.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the row. |
| `singleton` | Boolean, required, default `true` | Always `true`. Together with a unique constraint it limits the table to one row. |
| `offset_seconds` | BigInteger, required, default `0` | Signed seconds added to real time. Negative moves the clock back. |
| `updated_at` | DateTime (timezone), required | When the offset last changed. |
| `updated_by` | UUID, optional, foreign key to `users.id` (SET NULL) | The admin who last changed it. |

## 5. JobLock

**Model Overview:** A lock that says "one worker is currently doing this named piece of work".

**File Location:** `BD_BACKEND/app/core/models.py` (class `JobLock`, table `job_locks`).

**Purpose:** Stops two background workers doing the same thing at once where the job queue (Procrastinate) does not already guard it, e.g. polling the same mailbox. A row exists only while the lock is held: taking the lock inserts it, releasing deletes it. `expires_at` lets a lock left by a crashed worker be reclaimed. Acquire/release code is planned, not built. Example: name `poll_mailbox:42`, held by `worker-1`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the lock row. |
| `name` | String(255), required, unique | What is locked. Unique so only one worker can hold it. |
| `locked_by` | String(128), required | Identifier of the worker holding the lock. |
| `locked_at` | DateTime (timezone), required | When the lock was taken. |
| `expires_at` | DateTime (timezone), required | When the lock may be taken over. Must be later than `locked_at`. Indexed for cleanup. |

---

# Audit module (`app/audit/models.py`)

## 6. AuditLog

**Model Overview:** An append-only diary of sensitive actions (logins, role changes, approvals).

**File Location:** `BD_BACKEND/app/audit/models.py` (class `AuditLog`, table `audit_log`). Rows are written by `audit.services.record()`.

**Purpose:** Lets people review who did what and when. PostgreSQL triggers (migration 0004) reject UPDATE, DELETE and TRUNCATE, so history cannot be changed even by a bug. It is a "leaf" module with no foreign keys on purpose, so it never blocks deletes elsewhere. Example: a failed login for an unknown email creates a row with no `actor_user_id`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the event. |
| `occurred_at` | DateTime (timezone), required | When it happened. Indexed. |
| `actor_user_id` | UUID, optional | The user who did it. Plain UUID, deliberately not a foreign key. Empty when there is no user (e.g. failed login for an unknown email). Indexed. |
| `action` | String(64), required | Action name (allowed values live in the `AuditAction` class). Text, not a DB enum, because every milestone adds actions. Indexed. |
| `object_type` | String(64), optional | Kind of object affected, e.g. `user`. |
| `object_id` | String(64), optional | Id of the affected object, stored as text so any id style fits. |
| `summary` | JSONB, optional | Before/after summary. Never holds passwords or tokens (enforced in `record()`). |
| `ip_address` | String(45), optional | Client IP; 45 characters fit the longest IPv6 text. |

---

# Leads module (`app/leads/models.py`)

The leads tables are the "unified lead layer": the import module (M2) will write and merge them, and search and lead-detail screens (M3) will read them. No service reads or writes them yet.

## 7. Company

**Model Overview:** A target company that leads work for.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `Company`, table `companies`).

**Purpose:** Keeps the latest known facts about a company so BD can filter and segment (industry, size, technologies, location). Matching during import uses, in order, Apollo account id, then domain, then normalized name (D-077). Example: "Acme Corp", domain `acme.com`, industry "Software", technologies `["salesforce", "aws"]`, so `uses_salesforce` is `true`. Salesforce is only a filterable attribute, not an integration.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the company. |
| `apollo_account_id` | String(64), optional, unique | The company's id in Apollo (the lead source); first matching key. |
| `domain` | String(255), optional | Website domain, lowercase (CHECK). Second matching key. Indexed. |
| `name` | String(255), required | Company name as displayed. |
| `normalized_name` | String(255), required | Simplified name used for matching. Third matching key. Indexed. |
| `name_is_derived` | Boolean, required, default `false` | `true` when the name was guessed from the work-email domain (D-071). |
| `industry` | String(255), required, default `Unknown` | Standardized industry. Missing industry is stored as "Unknown", never quarantined (D-070). Indexed. |
| `naics` | String(16), optional | NAICS industry code. |
| `sic` | String(16), optional | SIC industry code. |
| `employee_count` | Integer, optional | Number of employees; must be 0 or more. |
| `annual_revenue` | Numeric(18,2), optional | Yearly revenue as given by the source (no currency recorded); 0 or more. |
| `funding_stage` | String(64), optional | Funding stage, e.g. "Series A". |
| `latest_funding_round_type` | String(64), optional | Type of the most recent funding round. |
| `total_funding` | Numeric(18,2), optional | Total money raised as given; 0 or more. |
| `latest_funding_date` | DateTime (timezone), optional | Date of the latest funding round. |
| `technologies` | Array of Text, required, default empty | Lowercased technology names used by the company. GIN-indexed for "contains" filters. |
| `keywords` | Array of Text, required, default empty | Lowercased keywords describing the company. GIN-indexed. |
| `uses_salesforce` | Boolean, required, default `false` | Derived from `technologies`; the leads service recomputes it whenever technologies change. |
| `hq_city` | String(128), optional | Headquarters city. |
| `hq_state` | String(128), optional | Headquarters state. Indexed together with `hq_country`. |
| `hq_country` | String(128), optional | Headquarters country. |
| `founded_year` | Integer, optional | Year founded. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 8. Person

**Model Overview:** A lead: one individual the BD team may contact.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `Person`, table `people`).

**Purpose:** The central lead record; emails, phones, notes, touches and flags attach to it. Example: "Dana Lee", VP Sales at Acme, owned by rep Priya, in Chicago. Only `first_name` is mandatory (D-069). "Possible duplicate" is not a column: it is derived from open `duplicate_candidates` rows (D-092). Rows are removed only by merge or erase-person (D-099), so there is no soft-delete column. App-specific lead states are derived from touches, flags and opt-outs (D-064, D-074), not stored here.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the person. |
| `source_record_id` | String(64), optional | The person's id in the source system (first matching key). Not unique: uncertain matches import as separate records until a manager merges them (D-092). Indexed. |
| `linkedin_url` | String(512), optional | LinkedIn profile URL (second matching key). Indexed. |
| `first_name` | String(128), required | First name (mandatory field, D-069). |
| `last_name` | String(128), optional | Last name. |
| `title` | String(255), optional | Job title. |
| `seniority` | String(64), optional | Seniority level (e.g. "VP"). Indexed. |
| `department` | String(128), optional | Department. |
| `city` | String(128), optional | City of the person. |
| `state` | String(128), optional | State of the person. |
| `country` | String(128), optional | Country. Indexed together with `state`. |
| `timezone` | String(64), optional | IANA time zone name (e.g. `America/Chicago`) used for scheduling; the rep's zone is used when empty (D-014, D-078). |
| `owner_id` | UUID, optional, foreign key to `users.id` (SET NULL) | The rep who owns the lead. Empty means the "Unassigned" pool for a manager to assign (D-075). Indexed. |
| `company_id` | UUID, optional, foreign key to `companies.id` (SET NULL) | The person's company. Indexed. |
| `source_status` | String(128), optional | Status exactly as imported (free text). |
| `source_stage` | String(128), optional | Stage exactly as imported (free text). |
| `lists` | Array of Text, required, default empty | Source lists the person belongs to, kept as tags (D-074). |
| `last_contacted_at` | DateTime (timezone), optional | When the person was last contacted. |
| `email_bounced` | Boolean, required, default `false` | `true` if an email to them bounced. |
| `replied_at` | DateTime (timezone), optional | When they last replied. |
| `intent_signals` | JSONB, optional | Buying-intent data from the source. Stored but unused in the MVP (D-074). |
| `qualify_contact` | Boolean, optional | Source flag saying whether to qualify the contact. Stored but unused in the MVP. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 9. PersonEmail

**Model Overview:** One email address belonging to a person.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `PersonEmail`, table `person_emails`; enums `EmailType`, `EmailVerificationStatus`).

**Purpose:** A person can have several addresses. Only `work` addresses are used for outreach (D-072). Unverified addresses stay eligible with a warning (D-042). Opt-out checks look addresses up by `normalized_address`. Example: `Dana.Lee@Acme.com` is stored as `address`, and `dana.lee@acme.com` as `normalized_address`. A person has at most one primary address. The same address is unique per person but not globally, because possible duplicates can share one until merged (D-092).

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id of the email row. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | Owner. Erase-person removes the person's addresses (D-099). |
| `address` | String(320), required | Address exactly as received, for display. |
| `normalized_address` | String(320), required | Lowercased, trimmed address for matching and opt-out lookups (D-066, D-077). Unique per person; indexed. |
| `type` | Text with CHECK (`work`, `personal`, `generic`), required | Kind of address. |
| `verification_status` | Text with CHECK (`verified`, `unverified`), required, default `unverified` | Whether the source verified it. |
| `is_primary` | Boolean, required, default `false` | `true` for the person's main address (at most one per person). |
| `is_invalid` | Boolean, required, default `false` | Set when the address bounced (D-073); an invalid address is never used. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 10. PersonPhone

**Model Overview:** A phone number of a person.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `PersonPhone`, table `person_phones`).

**Purpose:** Stores the person's phone numbers with the source's own label. Example: `+1 312 555 0100`, type `mobile`. The same number cannot be added twice for one person.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | Owner of the number. |
| `number` | String(64), required | The phone number. Unique per person. |
| `type` | String(32), optional | Free-text label such as `mobile` or `work` (the source's label list is not agreed). |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 11. SocialProfile

**Model Overview:** A social-network profile link of a person.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `SocialProfile`, table `social_profiles`).

**Purpose:** Keeps LinkedIn and other profile URLs so reps can open them from the lead page. Example: network `linkedin`, URL `https://linkedin.com/in/danalee`. The same URL cannot be added twice for one person.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | Owner of the profile. |
| `network` | String(32), required | Network name, lowercase by convention (`linkedin`, `twitter`, ...). |
| `url` | String(512), required | Profile URL. Unique per person. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 12. ContactChannel

**Model Overview:** A company-level contact channel that is not a named person's address.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `ContactChannel`, table `contact_channels`; enum `ContactChannelType`).

**Purpose:** Stores generic company contacts such as `info@acme.com` or the main phone line, kept apart from people. Example: company Acme, type `email`, value `info@acme.com`. The same (company, type, value) cannot repeat.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `company_id` | UUID, required, foreign key to `companies.id` (CASCADE) | Company that owns the channel. |
| `channel_type` | Text with CHECK (`email`, `phone`), required | Kind of channel. |
| `value` | String(320), required | The address or number. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 13. QuarantineRecord

**Model Overview:** An imported row held aside for a human to fix, release or discard.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `QuarantineRecord`, table `quarantine_records`; enum `QuarantineStatus`).

**Purpose:** Rows that fail checks (for example only a personal email, D-072) are not turned into leads; they wait here (D-068, D-107). BD edits the `payload` copy; the untouched original stays in `raw_rows` (D-099). Example: a row with only `dana@gmail.com` gets issues `["personal_email_only"]` and status `open`; a manager releases it, status `released`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `issues` | JSONB list, required, default `[]` | Reason codes found on the row, e.g. `["personal_email_only"]`. |
| `status` | Text with CHECK (`open`, `released`, `discarded`), required, default `open` | Where the record is in its lifecycle. Indexed. |
| `payload` | JSONB, required | The row's values as BD edits them. |
| `resolved_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who released or discarded it. |
| `resolved_at` | DateTime (timezone), optional | When it was resolved. Must be empty exactly when status is `open` (CHECK). |
| `raw_row_id` | UUID, optional, unique, foreign key to `raw_rows.id` (CASCADE) | Link to the untouched original row (added by migration 0007). Each raw row has at most one record. Deleted with the raw row because the payload holds the same personal data. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 14. DuplicateCandidate

**Model Overview:** A pair of people the system thinks might be the same person.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `DuplicateCandidate`, table `duplicate_candidates`; enum `DuplicateStatus`).

**Purpose:** When matching is uncertain, both records are kept and the pair is flagged for a manager to decide (D-092). The pair is stored once, with `person_a_id` smaller than `person_b_id`, so (A,B) and (B,A) cannot both exist. Example: two "Dana Lee" rows at `acme.com` flagged with reason `name_and_company_domain`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_a_id` | UUID, required, foreign key to `people.id` (CASCADE) | First person of the pair (the smaller id). |
| `person_b_id` | UUID, required, foreign key to `people.id` (CASCADE) | Second person of the pair. Indexed. |
| `reason` | String(255), required | Matching rule that raised the pair, e.g. `name_and_company_domain`. |
| `status` | Text with CHECK (`open`, `merged`, `not_duplicate`), required, default `open` | Review state. Indexed. |
| `decided_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Manager who decided. |
| `decided_at` | DateTime (timezone), optional | When decided. Empty exactly when status is `open` (CHECK). |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 15. MergeRecord

**Model Overview:** The history of one merge of two people.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `MergeRecord`, table `merge_records`).

**Purpose:** When two people are merged, the survivor stays and the other row is deleted; this table keeps a snapshot of what was absorbed (D-108). Example: Dana Lee #2 is merged into Dana Lee #1; the snapshot holds #2's old values. It has no `created_at`/`updated_at`; `merged_at` plays that role.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `survivor_id` | UUID, required, foreign key to `people.id` (CASCADE) | The person who remains. Erasing the survivor also removes the snapshot (it holds personal data). Indexed. |
| `absorbed_person_id` | UUID, required | Id of the person that was merged away. Deliberately not a foreign key because that row no longer exists. |
| `snapshot` | JSONB, required | The absorbed person's data at merge time. |
| `merged_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who performed the merge. |
| `merged_at` | DateTime (timezone), required | When the merge happened. |

## 16. Segment

**Model Overview:** A saved, named search filter.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `Segment`, table `segments`; enum `SegmentVisibility`).

**Purpose:** Lets a rep save a filter combination and reuse it, privately or shared with every BD user (D-009). The filters are stored as data that the search module turns into queries, never as raw SQL. Example: "US fintech, Salesforce users" with filters `{"industry": "Fintech", "uses_salesforce": true}`, visibility `shared`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `name` | String(255), required | Segment name. |
| `filters` | JSONB, required | The saved filter set. |
| `visibility` | Text with CHECK (`private`, `shared`), required, default `private` | Who can see the segment. |
| `owner_id` | UUID, optional, foreign key to `users.id` (SET NULL) | User who owns it. Indexed. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 17. LeadNote

**Model Overview:** A free-text note a colleague wrote about a lead.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `LeadNote`, table `lead_notes`).

**Purpose:** Lets reps share context. Notes are visible to every rep. Example: "Met at SaaStr, wants a demo in Q1." A user who wrote notes cannot be deleted (RESTRICT); deactivate them instead.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | The lead the note is about. Indexed. |
| `author_id` | UUID, required, foreign key to `users.id` (RESTRICT) | Who wrote it. |
| `body` | Text, required | The note text. Must not be blank (CHECK). |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 18. LeadEvent

**Model Overview:** One entry in a lead's timeline.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `LeadEvent`, table `lead_events`).

**Purpose:** Records things that happened to a lead (imported, merged, flagged, contacted) so the lead page can show a timeline. Example: event type `flag.set` with detail `{"flag": "partner"}`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | The lead the event belongs to. |
| `event_type` | String(64), required | Event code such as `flag.set`. Only lowercase letters, digits, underscores and dots (CHECK). The set grows with each module. |
| `detail` | JSONB, optional | Extra information about the event. |
| `actor_id` | UUID, optional, foreign key to `users.id` (SET NULL) | User who caused it, if any. |
| `occurred_at` | DateTime (timezone), required | When it happened. Indexed together with `person_id`. |
| `campaign_id` | UUID, optional | Related campaign. Plain UUID for now; the foreign key arrives with the campaigns migration. |
| `outreach_message_id` | UUID, optional | Related outreach message. Plain UUID for now; the foreign key arrives with the outreach migration. |

## 19. Touch

**Model Overview:** One contact with a lead on any channel (the shared contact history).

**File Location:** `BD_BACKEND/app/leads/models.py` (class `Touch`, table `touches`; enums `TouchChannel`, `TouchDirection`, `TouchStatus`).

**Purpose:** Lets everyone see how often and how a lead was contacted (D-026, D-034). Only the `email` channel exists in v1. Example: an outbound email sent by Priya with status `sent`; later an inbound one with status `replied`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | The lead contacted. |
| `channel` | Text with CHECK (`email`), required | How the contact happened. |
| `direction` | Text with CHECK (`outbound`, `inbound`), required | Whether the user contacted the lead or the lead contacted the user. |
| `rep_id` | UUID, optional, foreign key to `users.id` (SET NULL) | The rep who made the contact; history stays if the user is deleted. |
| `status` | Text with CHECK (`sent`, `opened`, `bounced`, `replied`, `demoed`), required | Engagement outcome (D-063). |
| `occurred_at` | DateTime (timezone), required | When it happened. Indexed together with `person_id`. |
| `campaign_id` | UUID, optional | Related campaign. Plain UUID until the campaigns migration adds the foreign key. |
| `outreach_message_id` | UUID, optional | Related outreach message. Plain UUID until the outreach migration adds the foreign key. |

## 20. LeadStatusFlag

**Model Overview:** A business flag currently set on a person.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `LeadStatusFlag`, table `lead_status_flags`; enum `LeadStatusFlagType`).

**Purpose:** Marks leads such as existing customers or competitors so campaigns can exclude them (D-022, D-065, D-101). Clearing a flag deletes the row (D-008); the audit log and lead timeline keep the set/clear history. Example: Dana has flag `in_conversation`, set by Priya. A person can have each flag at most once.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | The flagged person. |
| `flag_type` | Text with CHECK (`existing_customer`, `in_conversation`, `partner`, `competitor`, `qualified`, `handed_off_to_sales`), required | Which flag. Indexed. |
| `set_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who set it. |
| `set_at` | DateTime (timezone), required | When it was set. |

## 21. IndustryMapping

**Model Overview:** A lookup that turns a source's industry name into the standard industry.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `IndustryMapping`, table `industry_mappings`).

**Purpose:** Different sources name industries differently; this table standardizes them during import (D-076). Empty until M2 seeds it. Example: source name `information technology & services` maps to standard `Software`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `source_name` | String(255), required, unique | Industry text as found in the source, lowercased and trimmed (CHECK). |
| `standard_industry` | String(255), required | The standard industry name to store. |
| `naics_sector` | String(16), optional | NAICS sector code for that industry. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 22. StateMapping

**Model Overview:** A lookup that turns a state name or abbreviation into the standard name.

**File Location:** `BD_BACKEND/app/leads/models.py` (class `StateMapping`, table `state_mappings`).

**Purpose:** Standardizes state values during import (D-078), so `CA`, `Calif.` and `California` become one value. Empty until M2 seeds it. Example: country `United States`, source value `calif.`, standard name `California`, abbreviation `CA`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `country` | String(128), required | Country the state belongs to. Unique together with `source_value`. |
| `source_value` | String(128), required | State text as found in the source, lowercased and trimmed (CHECK). |
| `standard_name` | String(128), required | The standard state name to store. |
| `abbreviation` | String(16), optional | Short form, e.g. `CA`. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

---

# Imports module (`app/imports/models.py`)

These six tables back the Excel/CSV/Apollo import (M2). No service reads or writes them yet.

## 23. SourceProfile

**Model Overview:** A saved description of one kind of source file.

**File Location:** `BD_BACKEND/app/imports/models.py` (class `SourceProfile`, table `source_profiles`).

**Purpose:** Remembers default header-to-field mappings so the same kind of file is mapped the same way next time (D-049). Only admins edit profiles. Example: a profile "Apollo export" whose defaults map the header `Email` to the lead's email field. What was actually used for a given file is stored in `column_mappings`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `name` | String(255), required, unique | Profile name. |
| `layout` | String(64), required | Layout of the file. Free text because the three predefined layouts are not agreed yet; the import service validates it. |
| `mapping_defaults` | JSONB, required, default `{}` | Saved header-to-field defaults. |
| `is_active` | Boolean, required, default `true` | `false` hides the profile from new imports. |
| `created_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Admin who created it. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 24. ImportFile

**Model Overview:** One uploaded CSV or XLSX file.

**File Location:** `BD_BACKEND/app/imports/models.py` (class `ImportFile`, table `import_files`; enum `ImportStatus`).

**Purpose:** Tracks each upload and where it is in the import. Only the file's SHA-256 is stored, not the bytes. `sha256` is intentionally not unique: re-uploading the same content shows a warning and the user may import anyway (D-109). The 50,000-row and 20 MB limits (D-110) are checked by the import service, not the database. Example: `apollo-nov.csv`, status `processing`, 1,200 rows.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `sha256` | String(64), required | Lowercase hex SHA-256 of the file (64 characters, CHECK). Indexed for the duplicate-file warning. |
| `filename` | String(255), required | Original file name. |
| `uploaded_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Uploader; history stays if the user is deleted. Indexed. |
| `source_profile_id` | UUID, optional, foreign key to `source_profiles.id` (SET NULL) | Profile used for the file. Indexed. |
| `default_country` | String(128), optional | Country chosen for this import; leads with no location data fall back to it (D-078). |
| `worksheet` | String(255), optional | Sheet name for XLSX (one sheet per import, D-110); empty for CSV. |
| `status` | Text with CHECK (`uploaded`, `mapping`, `processing`, `completed`, `failed`), required, default `uploaded` | Lifecycle stage (`mapping` = headers being confirmed, D-049). |
| `row_count` | Integer, required, default `0` | Number of data rows; 0 or more. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 25. ColumnMapping

**Model Overview:** How one column of one file was mapped to a lead field.

**File Location:** `BD_BACKEND/app/imports/models.py` (class `ColumnMapping`, table `column_mappings`).

**Purpose:** Records the mapping actually used for a file (D-049). Example: column 3 with header `Work Email` was mapped to target field `email`; a column with no target is ignored. Position is stored too, because manual files can have no headers or repeated headers.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `import_file_id` | UUID, required, foreign key to `import_files.id` (CASCADE) | File the mapping belongs to. Unique together with `column_index`. |
| `column_index` | Integer, required | Zero-based column position; 0 or more. |
| `source_header` | String(512), optional | Header text from the file; may be empty for headerless files. |
| `target_field` | String(128), optional | Lead field the column maps to. Empty means the column is ignored. |
| `is_reassigned` | Boolean, required, default `false` | `true` when a user fixed or changed this mapping for the file (D-049). |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 26. RawRow

**Model Overview:** One uploaded row, kept exactly as received.

**File Location:** `BD_BACKEND/app/imports/models.py` (class `RawRow`, table `raw_rows`).

**Purpose:** The permanent untouched original of every imported row (D-099, D-008). A database trigger (migration 0007) rejects any UPDATE that changes the original columns; only `person_id` may change. Rows are removed only by erase-person. It has no `updated_at` because nothing about the original may change. Example: row 5 of `apollo-nov.csv` with `{"Email": "Dana@Acme.com", ...}`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `import_file_id` | UUID, required, foreign key to `import_files.id` (RESTRICT) | File the row came from. A file with stored rows cannot be deleted. Unique together with `row_number`. |
| `row_number` | Integer, required | One-based row number in the sheet; at least 1. |
| `original_values` | JSONB, required | Header (or column position) to cell value, exactly as received. |
| `email_normalized` | String(320), optional | Lowercased, trimmed email found in the row. Lets erase-person find rows never linked to a person (such as quarantined ones, D-099). Indexed. |
| `person_id` | UUID, optional, foreign key to `people.id` (SET NULL) | The lead this row created or updated; may change on release or merge. Indexed. |
| `created_at` | DateTime (timezone), required | When the row was stored. |

## 27. ImportReport

**Model Overview:** The totals for one import (one report per file).

**File Location:** `BD_BACKEND/app/imports/models.py` (class `ImportReport`, table `import_reports`).

**Purpose:** Shows what an import did: the seven totals of D-050 and why rows failed. All counts are 0 or more (CHECK). Example: received 1,000, imported 900, updated 50, quarantined 40, rejected 10, with `failure_reasons` `{"personal_email_only": 40}`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `import_file_id` | UUID, required, unique, foreign key to `import_files.id` (CASCADE) | The file the report is for (one report per file). |
| `received` | Integer, required, default `0` | Rows received. |
| `imported` | Integer, required, default `0` | New leads created. |
| `updated` | Integer, required, default `0` | Existing leads updated. |
| `unchanged` | Integer, required, default `0` | Rows that matched a lead with no changes. |
| `duplicates_found` | Integer, required, default `0` | Possible duplicate pairs flagged. |
| `quarantined` | Integer, required, default `0` | Rows sent to quarantine. |
| `rejected` | Integer, required, default `0` | Rows rejected. |
| `failure_reasons` | JSONB, required, default `{}` | Reason code to number of rows, e.g. `{"personal_email_only": 12}`. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 28. ImportChange

**Model Overview:** What one import changed on one updated lead.

**File Location:** `BD_BACKEND/app/imports/models.py` (class `ImportChange`, table `import_changes`).

**Purpose:** A transient summary so the report can show old and new values (D-050). It is not a permanent per-lead history (D-008). Because it holds personal values it is deleted with the person. No cleanup job exists yet; the retention period is still unresolved. Example: for Dana, `{"title": {"old": "Director", "new": "VP Sales"}}`. One row per (report, person).

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `import_report_id` | UUID, required, foreign key to `import_reports.id` (CASCADE) | The report this change belongs to. Unique together with `person_id`. |
| `person_id` | UUID, required, foreign key to `people.id` (CASCADE) | The lead that was updated. Indexed. |
| `changes` | JSONB, required | Field name to `{"old": ..., "new": ...}`. |
| `created_at` | DateTime (timezone), required | When the change was recorded. |

---

# Compliance module (`app/compliance/models.py`)

Added by migration 0008 (task A5). Tables only: the eligibility service, opt-out screens, erase-person and the real-sending gate that use them are planned (M3, M8).

## 29. OptOut

**Model Overview:** One "do not contact" event for an email address.

**File Location:** `BD_BACKEND/app/compliance/models.py` (class `OptOut`, table `opt_outs`).

**Purpose:** The only enforced suppression (D-066). It is stored per email address and deliberately has no link to `people`, so it still works after erase-person (D-099) and for addresses that have no lead yet. Removing an opt-out does not delete the row: it sets `removed_at` with a reason (manager/admin only). The same address can then opt out again as a new row, so the history stays. A partial unique index allows only one active row (`removed_at` empty) per address. Example: `dana@acme.com`, source `reply`, reason "Asked to stop in reply".

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `email_normalized` | String(320), required | Lowercase address (CHECK). Indexed; unique among active rows only. |
| `source` | Text, required, one of `manual`, `imported`, `reply` | Where the opt-out came from (`OptOutSource`). |
| `reason` | Text, optional | Why; imported opt-out lists may not have one. |
| `created_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who recorded it. Indexed. |
| `created_at` | DateTime (timezone), required | When it was recorded. |
| `removed_at` | DateTime (timezone), optional | When the opt-out was removed; empty while active. |
| `removed_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who removed it. Only allowed when `removed_at` is set. Indexed. |
| `removal_reason` | Text, optional | Required when `removed_at` is set; empty otherwise (CHECK). |

## 30. ComplianceGateStatus

**Model Overview:** The one row that says whether real sending is switched on.

**File Location:** `BD_BACKEND/app/compliance/models.py` (class `ComplianceGateStatus`, table `compliance_gate_status`).

**Purpose:** Real sending stays off until an admin passes the checklist (D-081); until then email goes only to the test-recipient list. There is exactly one row: migration 0008 creates it with real sending off, and a unique `singleton` flag (forced true by a CHECK) makes a second row impossible. Activation history lives in the audit log. A kill switch is not here yet (planned, M8). Example: `real_sending_enabled = false` today.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `singleton` | Boolean, required, default `true` | Always true and unique, so the table can hold only one row. |
| `real_sending_enabled` | Boolean, required, default `false` | Whether real sending is on. True exactly when `enabled_at` is set (CHECK). |
| `enabled_at` | DateTime (timezone), optional | When real sending was switched on. |
| `enabled_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Admin who switched it on. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 31. ComplianceChecklistItem

**Model Overview:** One of the four conditions that must pass before real sending.

**File Location:** `BD_BACKEND/app/compliance/models.py` (class `ComplianceChecklistItem`, table `compliance_checklist_items`).

**Purpose:** The D-081 checklist: Microsoft 365 sending connected, a tested unsubscribe option, saved footer wording, saved postal address. The four keys are fixed (CHECK, `ChecklistItemKey`) and seeded as "not passed" by migration 0008, so an item cannot be removed to weaken the gate. Example: `footer_saved`, passed by an admin on 2026-12-01 with the note "Footer v1".

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `item_key` | Text, required, unique, one of `m365_connected`, `unsubscribe_tested`, `footer_saved`, `postal_address_saved` | Which condition this row is. |
| `is_passed` | Boolean, required, default `false` | Whether the condition passed. True exactly when `passed_at` is set (CHECK). |
| `passed_at` | DateTime (timezone), optional | When it was marked passed. |
| `passed_by` | UUID, optional, foreign key to `users.id` (SET NULL) | User who marked it. Indexed. |
| `note` | Text, optional | Free note, for example what was tested. |
| `created_at` | DateTime (timezone), required | From `TimestampMixin`. |
| `updated_at` | DateTime (timezone), required | From `TimestampMixin`. |

## 32. ErasureRecord

**Model Overview:** Proof that a person was erased, with no personal data in it.

**File Location:** `BD_BACKEND/app/compliance/models.py` (class `ErasureRecord`, table `erasure_records`).

**Purpose:** Erase-person (D-099) removes the person's data everywhere but keeps their address in `opt_outs`. This row records that it happened. It has no foreign key to `people` because the person no longer exists, and it copies no name or address. Example: an admin erased person `7c1e...`, removing 2 raw rows and 1 stored email: `{"raw_rows": 2, "emails": 1}`.

| Field Name | Type | Description |
|---|---|---|
| `id` | UUID (primary key) | Unique id. |
| `former_person_id` | UUID, required | Id the person had (plain value, no foreign key). Indexed. |
| `erased_by` | UUID, optional, foreign key to `users.id` (SET NULL) | Admin who ran the erasure. Indexed. |
| `erased_at` | DateTime (timezone), required | When the erasure ran. |
| `reason` | Text, required | Why the person was erased. |
| `removed_counts` | JSONB, required, default `{}` | Area name to number of records removed, e.g. `{"raw_rows": 2}`. |

---

# Not built yet (no models to document)

These are not built yet. Most module packages exist only as header-only stubs in `app/<module>/models.py`, with no tables yet:

| Module | Planned tables (from the code comments and `CLAUDE.local.md`) |
|---|---|
| `app/compliance/` | `EligibilitySnapshot` (optional; skipped in task A5, planned for M3). The other four compliance tables are built, see section 29 onward. |
| `app/content/`, `app/campaigns/`, `app/outreach/`, `app/mail/`, `app/notifications/` | Owned by Developer B; tables not created yet |

When any of these are added, add their sections here in the same task.

# Keeping this file current

Whenever a `models.py` file or a migration changes a table or column, update the matching section here in the same task (see `CLAUDE.md`, "Workflow for every task").
