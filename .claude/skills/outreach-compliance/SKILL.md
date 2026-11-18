---
name: outreach-compliance
description: Eligibility, suppression and sending rules for Alphaleo BD. Use when touching search, campaigns, drafting, scheduling, sending, the outreach_messages queue, opt-outs, the compliance module, or real-sending activation.
---

# Outreach compliance

## Eligibility
- One eligibility service (`compliance`) serves search, campaigns, drafting and sending.
- Each rule is defined once as a SQL expression plus a record check, with a parity test proving both agree.

## Sending queue
- The only outgoing queue is `outreach_messages`. Claim rows with `FOR UPDATE SKIP LOCKED`.
- Use idempotency keys. Anything that can run twice (jobs, sends, imports) must be idempotent.
- Recheck eligibility, opt-out and sending limits at send time, not only when queued.

## Suppression
- Opt-outs are stored per email address and are the only enforced suppression (D-066).
- Customer, partner and competitor are filterable status flags, not suppression.

## Sending gate
- Real sending stays blocked behind the compliance gate (D-081). Until then email goes only to the admin test-recipient list.
- Auto-send is out of scope (D-019, D-091).

## Audit
- Write an audit event for approval, export, merge, opt-out removal, erasure, settings change and real-sending activation.
