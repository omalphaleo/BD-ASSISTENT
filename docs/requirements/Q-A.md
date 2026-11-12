# Salesforce BD Assistant — Requirements Q&A

Last updated: 2026-11-02
Status counts: 3 Open · 109 Answered · 8 Parked · 3 Withdrawn (123 total)

This is the single tracked Q&A record for this project's requirements
discovery. It consolidates and supersedes the earlier separate files
`round-1-questions.md` and the first draft of this file — those are now
superseded; this file is the source of truth going forward.

---

## 1. Apollo.io Data & Ingestion (DATA)

**Q-DATA-01** — What exact fields come in the Apollo export (industry,
company size, revenue, job title, seniority, tech stack, location, LinkedIn
URL, email verification status, phone, notes, tags, lead/engagement score,
last-contacted date)?
Why it matters: filtering, personalization, and de-dup logic can only use
fields we actually have.
Suggested default: none — need a sample export or field list.
Status: Answered
Answer: BD initially pointed to a file ("Agentic Databse.xlsx" — BD's
spelling) that wasn't received. The user then provided the actual field
list directly: Last Name, Title, Company Name, Company Name for Emails,
Email, Email Status, Primary Email Source, Primary Email Verification
Source, Email Confidence, Primary Email Catch-all Status, Primary Email
Last Verified At, Seniority, Departments, Sub Departments, Contact Owner,
Work Direct Phone, Home Phone, Mobile Phone, Corporate Phone, Other Phone,
Do Not Call, Stage, Lists, Last Contacted, Account Owner, # Employees,
Industry, Keywords, Person Linkedin Url, Website, Company Linkedin Url,
Facebook Url, Twitter Url, City, State, Country, Company Address, Company
City, Company State, Company Country, Company Phone, Technologies, Annual
Revenue, Total Funding, Latest Funding, Latest Funding Amount, Last Raised
At, Subsidiary of, Subsidiary of (Organization ID), Email Sent, Email
Open, Email Bounced, Replied, Demoed, Number of Retail Locations, SIC
Codes, NAICS Codes, Apollo Contact Id, Apollo Account Id, Apollo Record
Id, Secondary Email (+ its Source/Status/Verification Source), Tertiary
Email (+ its Source/Status/Verification Source), Primary/Secondary Intent
Topic & Score, Qualify Contact.
Note: this list has no "First Name" column — clarified under Q-IMPORT-01
that first-name data does exist but the header was missing in the manual
export, which became an important general design input (see Q-IMPORT-01
and D-049). Full field mapping, mandatory-field rules, and import handling
are worked out under the new "14. Data Import & Validation" theme below.
Answered by: User | Date: 2026-10-28

**Q-DATA-02** — What's the export format and frequency (CSV/API,
daily/weekly, manual trigger)?
Why it matters: determines whether ingestion is a scheduled job or an
on-demand upload.
Suggested default: manual/on-demand upload to start, scheduled automation
later.
Status: Answered
Answer: Manual/on-demand upload for v1. A BD/admin user manually exports
from Apollo and uploads the file into the app when needed; scheduled
automated API pull deferred to a later phase.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "CSV file, uploaded manually
to start; automate later."

**Q-DATA-03** — What uniquely identifies a lead across refreshes — email
address, Apollo's internal contact ID, or name+company?
Why it matters: critical for de-dup and change detection; email alone
breaks if Apollo re-verifies/corrects an email.
Suggested default: Apollo contact ID if present, falling back to
normalized email.
Status: Answered
Answer: Apollo's internal contact ID, falling back to normalized email if
the ID isn't present in the export.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "Apollo's internal contact
ID, falling back to the normalized email address if the ID is missing."

**Q-DATA-04** — When a refreshed dump changes or removes a lead's data for
a lead with an email already queued (not yet sent), what should happen?
Why it matters: affects personalization accuracy vs. operational
complexity; ties into the "generic emails hurt reply rates" problem.
Suggested default: flag for BD review rather than silently update or send
stale content.
Status: Answered
Answer: No special handling. Cold-outreach emails send as originally
composed regardless of minor data changes (e.g., title change) —
designation/detail accuracy doesn't matter much at the cold-outreach stage.
Relies on existing bounce/failure status tracking to catch genuinely
invalid addresses, not proactive staleness detection. Once a reply is
received, accuracy matters more and BD handles follow-up manually with
current context (covered by the reply-handling flow, Q-REPLY-02). Already
sent or already-replied history is never affected by later data changes.
User's own words: "designation doesn't really matter as these are cold
reachouts emails, if there is response from the customer then in the next
step we need to be more careful. If stale data is not much of significance
then no point re-working on it."
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed, with added detail — "Send the
email as originally written, even if small details like the contact's
designation change. The app should not send emails to invalid email
addresses or contacts who have unsubscribed." Existing sent emails and
replies should remain unchanged. (The invalid-address/unsubscribed check
ties to the do-not-contact handling in Q-LEADS-04 and Q-RULES-02.)

**Q-DATA-05** — Do we keep every historical snapshot of a lead, a
changelog, or only the latest version?
Why it matters: storage/audit-trail trade-off.
Suggested default: latest + changelog.
Status: Answered
Answer: Latest version only, no change history. Matches the Q-DATA-04
decision that staleness doesn't matter for cold outreach; simplest option,
no field-level audit trail between refreshes.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "Keep only the latest lead
data. A history of previous changes is not needed for the first version of
the app."

**Q-DATA-06** — Apollo.io capability inventory: what does BD actually use
in Apollo today beyond data export (saved searches/lists, sequences, email
templates, open/click tracking, Apollo's own analytics)?
Why it matters: needed for the Apollo-replacement mapping (what this app
must replace in v1 vs. what Apollo stays used for vs. what gets dropped).
Status: Answered
Answer: BD currently uses Apollo for prospect database searches, filtering
contacts by industry, company, job title, and location; building lead
lists; accessing contact details; exporting prospect data; and using email
sequences and templates.
Answered by: BD team | Date: 2026-10-27

**Q-DATA-07** — Should BD be able to export data from the app to CSV in
the MVP (Apollo export is one of the things the app replaces, D-024)?
Why it matters: BD exports prospect lists from Apollo today; without
export the app doesn't fully replace that use.
Suggested default: CSV export of lead search results and campaign
results, open to all roles within what each can already see, with every
export logged.
Status: Answered
Answer: Yes, in the MVP. Two exports: (1) lead search results for the
current filter, with key person and company fields plus eligibility and
opt-out status; (2) campaign results, one row per recipient, with each
email step's status and date and the reply category. All roles can
export, each limited to what they can already see. Every export is
logged (who, when, which filter, how many rows), which supports GDPR
accountability (D-033).
Answered by: User | Date: 2026-10-31

---

## 2. Lead Selection & List Building (LEADS)

**Q-LEADS-01** — Besides industry, company name, size, region, job
title/role, and tech stack — what other Apollo fields does BD filter on
today (funding stage, hiring signals, existing Salesforce usage if
detectable, intent score)?
Status: Answered
Answer: Funding stage and existing Salesforce usage. Hiring signals and
intent score were not called out as currently used.
Answered by: BD team | Date: 2026-10-27

**Q-LEADS-02** — Should BD be able to save a filter combination as a named
segment to reuse across campaigns?
Suggested default: yes.
Status: Answered
Answer: Yes, saved/reusable segments.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "Yes, we should be able to
save filter combinations as named lists and reuse them for future
campaigns to save time."

**Q-LEADS-03** — How should BD select leads to add to a campaign after
filtering — individually, select-all-matching in bulk, or both?
Status: Answered
Answer: Both: pick individually or select-all-matching.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — both.

**Q-LEADS-04** — Should a standing do-not-contact list (prior
unsubscribes, existing customers, competitors) exclude leads automatically
at search time, or only block them at send time?
Suggested default: exclude at search time.
Status: Answered
Answer: Exclude at search time — do-not-contact leads never appear in
filtered results.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed, with added detail —
unsubscribed contacts, existing customers, and competitors (where
applicable) should be excluded from both search results and campaigns, and
the app should re-check these contacts again right before sending as a
safety net.

**Q-LEADS-05** — BD asked for a "funding stage" filter (D-025), but the
Apollo column holding the funding round type ("Latest Funding") was left
unmapped in the agreed data model. Should it be mapped so the filter can
work?
Why it matters: without it, the funding-stage filter has no data.
Suggested default: map it into the company record and offer it as a
filter.
Status: Answered
Answer: Yes. The latest funding round type (e.g., Seed, Series A) is
stored on the company and offered as a funding-stage filter, alongside
total funding and latest funding amount/date.
Answered by: User | Date: 2026-10-29

**Q-LEADS-06** — Who can see and use a saved segment (D-009)?
Why it matters: shared segments save time, but a rep's working lists
shouldn't clutter everyone's view.
Suggested default: private to the owner, with a "share with team"
option.
Status: Answered
Answer: Saved segments are private to the rep who created them by
default; the owner can mark one "shared with team" so other users can
see and reuse it.
Answered by: User | Date: 2026-11-02

**Q-LEADS-07** — Which leads does lead search show by default?
Why it matters: BD also uses search to look up contact details (D-024),
not only to build campaigns.
Suggested default: all leads except opted-out ones, with badges for
anything that blocks outreach.
Status: Answered
Answer: Lead search shows every lead except opted-out ones by default,
with badges for cooling-off, replied, possible duplicate and unverified
email. An "Eligible only" filter is available but off by default, and
"Show opted-out" reveals opted-out leads with their badge (D-067). The
campaign builder always excludes ineligible leads automatically.
Answered by: User | Date: 2026-11-02

---

## 3. Lead Ownership & Conflict Handling (OWNERSHIP)

**Q-OWN-01** — Can the same lead be contacted by two different reps? If
not, how is ownership established — first rep to send claims it, first
rep to add to a list claims it, manager assigns, or no restriction in v1?
Suggested default offered: first rep to actually send wins (not first to
add to a draft list), to avoid lead hoarding.
Status: Answered
Answer: No restriction in v1 — any rep can contact any lead; no automatic
claim or lock. Revisit if this causes real-world duplicate-contact
problems.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "No restrictions are needed
in v1. Any BD representative can contact any lead." Added: reps should be
able to see contact history to help identify and avoid duplicate outreach
(see Q-OWN-02).

**Q-OWN-02** — Given "no restriction in v1" (Q-OWN-01), should other reps
at least get passive visibility into a lead's contact history (e.g., "Rep X
already emailed this lead on [date]") even without a hard restriction?
Status: Answered
Answer: Yes — all reps should be able to see who contacted a lead, when
they contacted them, and the current contact status, to avoid duplicate
outreach.
Answered by: BD team | Date: 2026-10-27

**Q-OWN-03** — Same-company, different-contact: if Rep A emails the CFO
and Rep B wants to email the CTO at the same company, is that allowed?
Suggested default: allowed, but surfaced in UI so B knows a colleague is
already engaging that account.
Status: Answered
Answer: Yes, allowed — different reps can contact different people at the
same company, but the app should show a note if another rep is already
contacting that account to avoid duplicate outreach.
Answered by: BD team | Date: 2026-10-27

**Q-OWN-04** — Who can mark a lead "Qualified" or "Handed Off to Sales"
(D-022)?
Why it matters: the status stops follow-ups and feeds reporting, so it
should be easy to set but traceable.
Suggested default: any rep, on any lead, with every change logged.
Status: Answered
Answer: Any BD user can set or change the status on any lead,
consistent with no ownership lock (D-001). Every change is recorded with
who and when.
Answered by: User | Date: 2026-11-02

---

## 4. Personalization Process (PERSONALIZATION)

(Content-specific personalization questions — what to actually say, which
Alphaleo offerings/industries/case studies to reference — live under
section 13, CONTENT, since they need BD/Sales subject-matter answers
rather than product-process answers.)

**Q-PERS-01** — Should BD be able to rate or edit an AI draft in a way
that improves future drafts (structured feedback loop), or is
editing-before-send enough for v1?
Suggested default: editing is enough for v1; structured feedback loop is a
Should-have, not a Must-have.
Status: Answered
Answer: Editing the draft before sending is enough for v1. A feedback or
rating feature can be considered in the future if needed.
Answered by: BD team | Date: 2026-10-27

---

## 5. Sending & Scheduling (SENDING)

**Q-SEND-01** — What should the per-mailbox daily/hourly send cap be —
known Microsoft 365 limits/policy, or a configurable value with a
conservative default?
Suggested default: configurable, start ~20–50/day/mailbox; real ceiling is
also a Phase 2 technical question (tenant policy).
Status: Answered
Answer: BD wants the system to support sending around 800–1,000 emails per
day per mailbox at a controlled pace, subject to Microsoft 365 limits and
email deliverability policies — covering both initial outreach and
follow-up emails, with the goal of completing a full campaign (including
follow-ups) within one week. The system should support campaign scheduling
and follow-up tracking to help hit this target while minimizing the risk
of Outlook throttling or being marked as spam.
⚠ Flagged for Phase 2 (architecture): 800–1,000/day/mailbox is far above
typical safe sending volumes for cold B2B outreach from a Microsoft 365
mailbox (industry guidance for a sender without an established reputation
is usually tens per day, not hundreds) and needs explicit technical
validation against actual Microsoft 365 tenant policy and deliverability
best practice before being locked in as a hard requirement — sending at
this volume without validation risks mailboxes being throttled or flagged
as spam, which would undermine the whole project's goal of fixing
deliverability. Recommend confirming the real ceiling with Microsoft
365/network-exchange expertise before committing to this number.
Answered by: BD team | Date: 2026-10-27

**Q-SEND-02** — What should the sending identity be — whose mailbox do
outreach emails go out from (each rep's own O365 mailbox, one shared
outreach mailbox, or admin decides per campaign)?
Status: Answered
Answer: Admin decides per campaign — configurable, not fixed to one model.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "The admin should be able to
choose the sending mailbox for each campaign based on the team's needs. It
should not be fixed to one mailbox option."

**Q-SEND-02b** — When an admin doesn't explicitly configure sending
identity for a campaign, what should the default be?
Status: Answered
Answer: Each rep's own mailbox — matches natural reply routing and spreads
sending across multiple mailboxes' caps.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed.

**Q-SEND-03** — Should outreach emails respect the prospect's local time
zone for sending windows, or the sending rep's time zone?
Status: Answered
Answer: Prospect's time zone when inferable from location data, falling
back to rep's time zone otherwise.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed.

**Q-SEND-04** — If a rep pauses a campaign mid-send, should the remaining
queued emails require an explicit resume, or auto-resume after some
condition?
Status: Answered
Answer: Explicit resume required; no auto-resume.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — manual resume only, campaign
should not restart automatically.

**Q-SEND-05** — When a send fails (technical failure, not a bounce), how
many retries, over what time window, before marking it "failed" and
surfacing to BD?
Status: Answered
Answer: A few retries with backoff (e.g. 2–3 attempts with increasing
delay over about a day), then stop and surface to BD as "failed" rather
than retry indefinitely.
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — 2–3 retries with increasing
delay over about a day, then mark failed and notify BD as a follow-up
action.
Refined (2026-11-02): exact retry timing set — see Q-SEND-09 (D-097).

**Q-SEND-06** — What is the default follow-up sequence, and how does it
fit the contact limits (D-020: 3 emails per 30 days; D-073: 90-day
cooling-off)?
Why it matters: follow-ups are part of every campaign (D-029) and must
not break the contact limits.
Suggested default: first email plus 2 follow-ups, all counting toward
the 3-in-30 limit, admin-configurable.
Status: Answered
Answer: One default sequence for all campaigns: the first email, then
follow-up 1 on business day 3 and follow-up 2 on business day 7 (counted
from the first email). Follow-ups count toward the contact limit of 3
emails per person in 30 days. The 90-day cooling-off applies before a
person can enter a new campaign, not to follow-ups within the same
campaign. Remaining follow-ups stop on any reply, bounce, opt-out, or a
"Qualified" / "Handed Off to Sales" status. When a mailbox's daily cap is
reached, due follow-ups go out before new first emails (then oldest
first); the rest moves to the next sending window. Only the admin can
change these settings (see Q-RULES-04); BD users cannot override them
per campaign in the MVP.
Note: with these defaults the last follow-up goes out about 9 calendar
days after the first email, so BD's "full campaign within one week"
target (D-029) cannot be met; the campaign completion estimate will show
this.
Answered by: User | Date: 2026-10-31
Refined (2026-11-02): out-of-office auto-replies do not stop the
sequence (Q-REPLY-06, D-093).

**Q-SEND-07** — When are follow-up emails drafted and reviewed: all at
campaign start, or each shortly before it is due?
Why it matters: affects how often reps must review, and whether a late
review can delay a follow-up.
Suggested default: draft all three emails per lead at campaign start and
review them together.
Status: Answered
Answer: All three emails in a lead's sequence are drafted when the
campaign starts and reviewed together as one sequence. Follow-ups that
are no longer needed (reply, bounce, opt-out, Qualified/Handed Off) are
cancelled automatically.
Answered by: User | Date: 2026-11-02

**Q-SEND-08** — How should bounced emails be treated?
Why it matters: repeated sending to dead addresses harms mailbox
reputation; temporary problems (e.g., a full mailbox) shouldn't
permanently remove a good contact.
Suggested default: permanent bounce → invalid at once; temporary bounce
→ one retry, then invalid.
Status: Answered
Answer: A permanent bounce marks the email address invalid immediately
and stops the sequence. A temporary bounce (e.g., mailbox full) gets one
retry on the next business day; if it bounces again, the address is
marked invalid.
Answered by: User | Date: 2026-11-02

**Q-SEND-09** — What exact retry timing applies to failed sends (D-018
says 2–3 attempts over about a day)?
Why it matters: sets when BD hears about a failed email.
Suggested default: retry after 30 minutes, 4 hours and 20 hours.
Status: Answered
Answer: Retry after 30 minutes, 4 hours and 20 hours; then mark the
email "Failed" and notify the rep.
Answered by: User | Date: 2026-11-02

**Q-SEND-10** — Is real Microsoft 365 sending and reply monitoring part
of the MVP, or does the MVP end with the "draft only" sender?
Why it matters: defines when the MVP counts as done.
Suggested default: yes — the MVP is done when real Microsoft 365
sending and reply checking work with test recipients.
Status: Answered
Answer: Yes. The MVP is complete when sending and reply checking through
Microsoft 365 work end to end with test recipients. Switching on real
sending to prospects follows as soon as the go-live items are settled
(paid AI key, footer wording, postal address, unsubscribe test,
retention period).
Answered by: User | Date: 2026-11-02

---

## 6. Reply Handling & Auto-Response (REPLY)

**Q-REPLY-01** — What reply categories matter to BD beyond
interested/not interested/not now/wrong person/out-of-office/unsubscribe
(e.g., forwarded to someone else, asked a question)?
Status: Answered
Answer: The six listed categories are sufficient for v1.
Answered by: BD team | Date: 2026-10-27

**Q-REPLY-02** — What should v1 do when a reply arrives — classify +
notify BD only (no auto-reply), classify + tailored auto-reply + notify,
or simple notify with no classification?
Status: Answered
Answer: Classify + notify BD only, no auto-reply, in v1. Auto-response
generation is an explicit fast-follow once classification accuracy is
proven, not v1 scope.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "The app should classify
incoming replies and notify the BD team. It should not send automatic
replies in v1."

**Q-REPLY-03** — Confirm OOO, negative/not-interested, and unsubscribe
replies never trigger an automated reply, only a notification (unsubscribe
also triggers do-not-contact + opt-out processing). Are there other
situations where auto-reply must never fire (e.g., reply from a different
domain than the original recipient, indicating forwarding)?
Status: Answered
Answer: The three listed situations are enough for v1. For v1, the app
should not send automatic replies to out-of-office, not-interested, or
unsubscribe responses; unsubscribe replies should also mark the contact as
do-not-contact. No additional forwarding/domain-mismatch rule requested
for v1.
Answered by: BD team | Date: 2026-10-27

**Q-REPLY-04** — Should reply detection be scoped to "same email thread"
only, or also catch a different person at the same company replying
outside that thread?
Status: Answered
Answer: Same email thread only for v1; a fresh email from a different
person at the same company (outside the thread) is not auto-linked to the
original outreach.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "should detect and link
replies within the original email thread only in v1."

**Q-REPLY-05** — The "Unsubscribe" button in each email opens a
pre-filled email (see Q-COMP-04). That email arrives as a new message,
not a reply in the original thread, so the same-thread rule (D-016) would
miss it. Should unsubscribe emails be an exception?
Why it matters: a missed unsubscribe means emailing someone who opted
out.
Suggested default: yes, an exception for unsubscribe only.
Status: Answered
Answer: Yes, for unsubscribe only. Any new email with the subject
"Unsubscribe" arriving in a BD mailbox from an address the app has
emailed opts out that sender's address, and also the address named in
the email body. This is a fixed rule, not an AI judgement. All other
replies still follow the same-thread rule (D-016).
Answered by: User | Date: 2026-10-31

**Q-REPLY-06** — Should an out-of-office auto-reply stop the remaining
follow-ups (D-082 says any reply stops them)?
Why it matters: an auto-reply is not a real response; stopping would
lose follow-ups for people who were simply away.
Suggested default: no — record it and continue the sequence.
Status: Answered
Answer: No. Out-of-office replies are recorded on the lead's timeline and
the sequence continues as planned. All other reply categories still stop
it.
Answered by: User | Date: 2026-11-02

**Q-REPLY-07** — What happens when the AI is unsure how to classify a
reply?
Why it matters: a wrong label could hide an interested prospect or
miss an unsubscribe.
Suggested default: below a confidence of 0.7, mark it "Unclear – please
check", stop the sequence and notify the rep.
Status: Answered
Answer: Replies classified with confidence below 0.7 are marked
"Unclear – please check"; the sequence stops and the rep is notified to
label the reply. The admin can change the 0.7 threshold. If the AI is
unavailable, the reply is saved as "Unclassified" with the same safe
handling.
Answered by: User | Date: 2026-11-02

**Q-REPLY-08** — Where do reps answer a prospect's reply: in the app or
in Outlook?
Why it matters: replying from the app would need an email editor and
more sending rules; Outlook is already familiar.
Suggested default: in Outlook; the app shows the reply and links to it.
Status: Answered
Answer: Reps reply in Outlook. The app shows the reply with its thread
and a link to open the email in Outlook, but does not send manual
replies in the MVP. The rep then marks the reply "handled" in the app,
which closes the same-day follow-up check (D-032).
Answered by: User | Date: 2026-11-02

---

## 7. Notifications & Follow-up (NOTIFY)

**Q-NOTIFY-01** — What notification channel should alert BD when a reply
arrives — email-only, also Microsoft Teams, or admin-configurable?
Status: Answered
Answer: Email only for v1; Teams as a possible fast-follow.
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — "Email notifications are
enough for the first version. Microsoft Teams notifications can be
considered in the future."

**Q-NOTIFY-02** — What's the expected time-to-notify after a reply
arrives, and the expected BD follow-up SLA to track/report on?
Status: Answered
Answer: Notify BD within minutes of a reply arriving; track a
same-business-day follow-up SLA.
Answered by: BD team | Date: 2026-10-27

**Q-NOTIFY-03** — After a positive reply, should there be an in-app "mark
as qualified / hand off to Sales" step, or does that happen entirely
outside this tool (since Alphaleo doesn't use Salesforce internally)?
Status: Answered
Answer: Simple in-app status tag — BD marks the lead
"qualified"/"handed off" in-app for tracking and reporting, even though
the actual handoff happens elsewhere (no Salesforce integration needed).
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed, with added detail — the exact
status labels should be "Qualified" or "Handed Off to Sales"; the actual
handoff can happen outside the app.

**Q-NOTIFY-04** — Who receives the alert when a reply arrives?
Why it matters: the lead's owner and the rep who sent the email may be
different people (D-001, D-075).
Suggested default: the sending rep, plus the lead owner if different.
Status: Answered
Answer: The rep whose campaign sent the email is notified, and the
lead's owner too if that is someone else (in-app and by email). Managers
see all replies on their overview but don't receive individual alerts.
Answered by: User | Date: 2026-11-02

---

## 8. Roles, Permissions & Approval (ROLES)

**Q-ROLES-01** — Confirming three roles: BD rep (builds lists,
reviews/sends own emails), BD manager (visibility across reps, can
reassign/manage), Admin (manages knowledge base, sending limits,
integrations). Correct, or is a role missing/different (e.g. a
Sales/handoff role)?
Status: Answered
Answer: Confirmed as described. No separate Sales/handoff role added for
v1.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "The three roles are enough
for v1: BD rep, BD manager, and Admin. A separate Sales/handoff role is
not needed."

**Q-ROLES-02** — Who can turn on auto-send (skip-review) for a campaign —
manager grants it per rep, open to every rep by default, or admin-only
globally toggled?
Status: Answered
Answer: A BD manager explicitly grants auto-send capability per rep
(earned/trust permission) — not open to every rep by default, not
admin-only/global.
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — "The BD manager should grant
auto-send permission to individual reps based on trust. It should not be
enabled for everyone by default."

**Q-ROLES-03** — Can a BD manager edit another rep's draft
emails/campaigns, or only view their status?
Status: Answered
Answer: View only — manager sees status/progress across all reps but can't
modify another rep's drafts; keeps ownership clear.
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — managers can view status and
progress of all reps' campaigns/drafts, but cannot edit another rep's
drafts.

**Q-ROLES-04** — Can a rep approve several AI drafts at once, or must
each be approved individually?
Why it matters: reviewing hundreds of drafts one by one is slow, but
every email goes out under the rep's name; auto-send without review is
deferred (D-019).
Suggested default: bulk approval only for drafts that passed all checks
with no warnings.
Status: Answered
Answer: A rep may bulk-approve drafts that passed every automatic check
with no warnings, after seeing them in the list view. Drafts with
warnings or marked "Needs attention" must be opened and approved one at
a time. This is not auto-send: a person still approves every email.
Answered by: User | Date: 2026-11-02

**Q-ROLES-05** — Who can upload import files and manage source mappings?
Why it matters: BD reps receive lead files, but saved mapping profiles
affect every future import of that source.
Suggested default: any BD user can upload using an existing profile;
only admins create or edit saved profiles and mappings.
Status: Answered
Answer: Any BD user (rep, manager or admin) can upload a file using an
existing source profile and fix or reassign headers for that file
(D-049). Only admins can create or edit saved source profiles and the
industry and state mappings.
Answered by: User | Date: 2026-11-02

**Q-ROLES-06** — Who can fix, release or discard quarantined import
rows?
Why it matters: releasing makes a row a usable lead; discarding loses it
from the working data (the raw row is still kept, D-063).
Suggested default: any BD user can fix and release; discard only by the
importer, a manager or an admin.
Status: Answered
Answer: Any BD user can fix and release a quarantined row. Discarding is
limited to the user who ran that import, a BD manager, or an admin.
Answered by: User | Date: 2026-11-02

---

## 9. Business Rules & Guardrails (RULES)

**Q-RULES-01** — Should there be a default contact-frequency limit (max
emails to the same lead in a time window) in v1?
Status: Answered
Answer: Yes, admin-configurable with a sensible default (e.g. default
~3 touches per lead within 30 days, with a minimum gap between sends;
admin can tune the exact numbers).
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — "a default limit of around 3
emails per lead within 30 days, with a minimum gap between emails. The
admin should be able to change these limits."

**Q-RULES-02** — Should an unsubscribe/opt-out apply to just that
individual, or the whole company domain?
Status: Answered
Answer: Individual contact only — matches standard CAN-SPAM/GDPR practice;
other contacts at the same company remain contactable.
Answered by: User | Date: 2026-10-21
BD team confirmation (2026-10-27): Confirmed — "the app should stop sending
emails to that person only. Other contacts at the same company can still
be contacted."

**Q-RULES-03** — Is there a current Alphaleo customer list that should
never receive cold outreach, and where does it live today?
Status: Answered
Note: BD's first submitted answer for this question was identical to their
Q-RULES-02 answer (about individual-only unsubscribe scope) and did not
address the actual question — flagged as a likely copy/paste mismatch and
re-asked directly.
Answer: No existing customer list exists today. Starting fresh — the
suppression list will be built and tracked over time as the application
begins sending cold outreach, rather than seeded from a pre-existing
system of record.
Answered by: User | Date: 2026-10-27

**Q-RULES-04** — Who controls the sending and contact limits, what are
the defaults, and what happens when they conflict?
Why it matters: the limits protect prospects and mailbox reputation, and
settings that contradict each other would make campaigns behave
unpredictably.
Suggested default: admin-only global settings with sensible defaults,
checked for conflicts when saved.
Status: Answered
Answer: All limits are global admin settings that apply to all
campaigns; BD users cannot override them per campaign in the MVP.
Defaults:
- Contact limit: 3 emails per person in 30 days; minimum gap between
  emails to the same person: 2 business days.
- Cooling-off before a person can enter a new campaign: 90 days.
- Company limit: at most 2 people at the same company contacted per day.
- Mailbox limits: 30 emails per day and 8 per hour per mailbox, raised
  gradually by the admin (BD's 800–1,000/day target, D-029, still needs
  validation).
- Sending window: Monday to Friday, 09:00–17:00 in the prospect's time
  zone (D-014); no holiday calendar in the MVP.
- Follow-up sequence and send order as in Q-SEND-06.
When the admin saves settings that conflict (e.g., a sequence longer
than the contact limit, or a follow-up gap shorter than the minimum
gap), the app warns and asks for confirmation before saving. A campaign
completion estimate uses these settings and warns when a target end date
can't be met. Opt-outs are always enforced, whatever the settings.
Answered by: User | Date: 2026-10-31

---

## 10. Compliance & Deliverability (COMPLIANCE)

**Q-COMP-01** — Which jurisdictions do prospects fall under — GDPR in
scope (any EU/UK prospects), primarily US/CAN-SPAM, or both?
Status: Answered
Answer: Prospects may be from the US as well as the EU/UK, so the app
should support both CAN-SPAM and GDPR requirements.
Answered by: BD team | Date: 2026-10-27

**Q-COMP-02** — Is there a standard unsubscribe/opt-out footer and a
documented process for honoring opt-outs within the legally required time
window, or does this need to be drafted?
Status: Answered
Answer: No standard unsubscribe/opt-out footer or documented process
exists today — one needs to be created.
Answered by: User | Date: 2026-10-28

**Q-COMP-03** — Is there any known contractual/Apollo.io terms-of-service
constraint on exporting and using their data outside the Apollo platform
that should be flagged as a legal risk to check?
Status: Parked
Note: BD is checking Apollo.io's terms and conditions as part of an
in-progress contract renewal, and offered to provide a knowledge-transfer
(KT) on Apollo.io once available. No definitive answer yet.
Answered by: BD team (partial) | Date: 2026-10-27
Follow-up (2026-10-28): Re-checked with the user — no update yet; kept
Parked until the Apollo.io renewal terms or KT session are available.

**Q-COMP-04** — How do prospects unsubscribe in the MVP, given the app
runs only inside the office network and has no public web address for an
unsubscribe page?
Why it matters: CAN-SPAM and GDPR (D-033) require a working opt-out in
every outreach email.
Suggested default: reply-based unsubscribe for the MVP; a web page once
the app is publicly hosted.
Status: Answered
Answer: No public web unsubscribe page in the MVP; it comes in a later
phase once public hosting is set up. In the MVP:
- Every email footer says: "Reply with 'unsubscribe' to opt out." Reply
  classification detects these replies and records the opt-out.
- Every email also has an "Unsubscribe" button that opens a pre-filled
  email ("Unsubscribe" subject, the recipient's address in the body) to
  the sending rep's own mailbox, processed the same way (see Q-REPLY-05).
  This works with Microsoft Graph sending. If it ever did not work, the
  button would be a placeholder only and real sending would stay blocked
  (see Q-COMP-07).
- Later phase: point the button at a web unsubscribe page. Also later:
  the built-in "unsubscribe" link that Outlook and Gmail show at the top
  of an email, which the Microsoft Graph sending method can't set today.
Answered by: User | Date: 2026-10-31

**Q-COMP-05** — What is the final wording of the email footer (opt-out
text and any company/legal text)?
Why it matters: the footer appears in every email and is part of
CAN-SPAM/GDPR compliance (D-033, D-051). Required before any real
(non-test) email is sent.
Suggested default: "Alphaleo Technologies, <postal address>. Reply with
'unsubscribe' to opt out, or click Unsubscribe." — to be confirmed by BD
or leadership.
Status: Open
Answer:
Answered by: | Date:

**Q-COMP-06** — What postal address should appear in the email footer?
Why it matters: CAN-SPAM requires a valid physical postal address in
commercial emails. Required before any real (non-test) email is sent.
Suggested default: Alphaleo's registered office address.
Status: Open
Answer:
Answered by: | Date:

**Q-COMP-07** — Should the app block real (non-test) sending until the
compliance basics are in place?
Why it matters: prevents real prospects from receiving emails without a
working opt-out, footer, or postal address.
Suggested default: yes; send only to an approved test list until then.
Status: Answered
Answer: Yes. Until the admin switches on "real sending", the app sends
only to a test-recipient list maintained by the admin (e.g., internal
Alphaleo mailboxes). The switch can only be turned on when all of these
are true: Microsoft 365 sending is connected (not the "draft only"
sender), a working unsubscribe option exists and has been tested, the
footer wording is saved (Q-COMP-05), and Alphaleo's postal address is
saved (Q-COMP-06). Turning it on is recorded with who and when.
Answered by: User | Date: 2026-10-31

**Q-COMP-08** — How does the app handle a request from a prospect to have
their personal data erased (GDPR, D-033)?
Why it matters: GDPR gives EU/UK prospects the right to erasure, but
the app must still remember never to email them again.
Suggested default: an admin-only "Erase person" action in the MVP that
keeps only the opted-out address.
Status: Answered
Answer: The MVP includes an admin-only "Erase person" action. It removes
the person's details from the lead database, the original imported
rows, and stored emails and replies, but keeps their email address on
the opt-out list so they are never contacted again. Each erasure is
recorded in the audit log.
Answered by: User | Date: 2026-11-02

**Q-COMP-09** — Should the app store the full text of prospects' replies,
and for how long?
Why it matters: BD needs the reply text to follow up; storing personal
correspondence also carries a GDPR duty to keep it only as long as
needed.
Suggested default: store full text of replies to app emails only; no
automatic deletion in the MVP; review retention before go-live.
Status: Answered
Answer: The app stores the full text of replies to its own emails only;
other messages in BD mailboxes are never stored. There is no automatic
deletion in the MVP; a retention period is to be agreed before go-live.
Answered by: User | Date: 2026-11-02

**Q-COMP-10** — Who can download the import files that contain personal
data (quarantined rows, change summaries)?
Why it matters: downloaded files leave the app's controls (GDPR,
D-033).
Suggested default: the importer, managers and admins, with every
download logged.
Status: Answered
Answer: The user who ran the import, BD managers and admins can download
the quarantined-rows and change-summary files. Each download is
recorded in the audit log.
Answered by: User | Date: 2026-11-02

---

## 11. Reporting & Success Metrics (REPORT)

**Q-REPORT-01** — Should reporting/analytics be available to every BD rep
for their own activity, or only to managers/admins?
Status: Answered
Answer: Both — each rep gets a personal dashboard (their own
sends/replies/metrics); managers/admins get an aggregate view across the
team.
Answered by: User | Date: 2026-10-22
BD team confirmation (2026-10-27): Confirmed — "Each BD rep should have a
dashboard to track their own emails, replies, and performance. Managers
and admins should be able to view the overall team's activity and
performance."

**Q-REPORT-02** — What is the current Apollo.io cost figure (monthly/
annual spend) to use as the cost-reduction baseline metric?
Status: Parked
Note: BD needs to confirm the current Apollo.io subscription cost with
Finance/Procurement before providing a figure. No number yet.
Answered by: BD team (partial) | Date: 2026-10-27
Follow-up (2026-10-28): Re-checked with the user — no figure yet; kept
Parked (not needed to build the MVP, only to report savings afterwards).

**Q-REPORT-03** — Should reporting (D-023) be part of the MVP, given the
MVP scope (D-052) doesn't list it?
Why it matters: BD and managers need basic visibility from day one, but
full dashboards add build time.
Suggested default: a simple activity page in the MVP; charts and trends
later.
Status: Answered
Answer: Yes, a simple activity page in the MVP: each rep sees their own
figures and managers see team totals — emails sent, replies by category,
drafts awaiting review, failed sends, and missed same-day follow-ups.
Charts, trends and richer dashboards come later.
Answered by: User | Date: 2026-11-02

---

## 12. Multi-Channel Note — future, not v1 (CHANNEL)

**Q-CHAN-01** — Should the lead/contact history model be built
generically (a "contact" can have multiple channels, each outreach is one
"touch" regardless of channel) even though only email exists in v1?
Suggested default: yes — low cost now, avoids a painful remodel later for
WhatsApp/LinkedIn.
Status: Answered
Answer: Yes — should be designed to track contact history across different
channels (email, WhatsApp, LinkedIn), even though only email will be
available in v1, to make it easier to add other channels later.
Answered by: BD team | Date: 2026-10-27

---

## 13. Email Content Strategy — for BD/Sales team input (CONTENT)

Context: the AI agent personalizes each email by mapping Apollo data
(industry, company size, role, tech stack, hiring signals, funding events)
to a specific Alphaleo angle and a piece of proof (case study/result). It
can only do that credibly with real answers to the questions below — this
needs BD/Sales subject-matter knowledge, not a product decision.

**Q-CONTENT-01** — Which Salesforce offerings does Alphaleo actually
provide (new implementation, migration from another CRM, optimization/
health-check of existing orgs, custom development/integrations/managed
support, other)? Select all that apply.
Why it matters: determines which "angle" the AI can credibly pitch per
lead — it must never pitch a service Alphaleo doesn't actually offer.
Status: Answered
Answer: All four apply — Alphaleo provides Salesforce implementation,
migration from other CRM platforms, optimization of existing Salesforce
setups, and custom development, integrations, and managed support
services.
Answered by: BD team | Date: 2026-10-27

**Q-CONTENT-02** — What company size/segment does Alphaleo actually want
to target with this outreach — SMB, mid-market, enterprise, or all?
Why it matters: shapes tone, formality, and which pain points the email
leads with.
Status: Answered
Answer: All three — SMB, mid-market, and enterprise — targeted based on
each account's specific Salesforce requirements and business needs, not a
single fixed segment.
Answered by: BD team | Date: 2026-10-27

**Q-CONTENT-03** — What industries does Alphaleo primarily serve, or want
to go after, with the strongest track record/proof?
Why it matters: drives which industry-specific angle and case study the AI
references for a given lead.
Status: Answered
Answer: Candidate target industries: Manufacturing, Real Estate,
Hospitality, Healthcare, and IT/Services. Final priority order still to be
confirmed with leadership.
Answered by: BD team | Date: 2026-10-27

**Q-CONTENT-04** — Does Alphaleo have verified case studies/client results
with real, approved numbers that can be referenced in outreach emails? If
yes, list them (industry, company size if shareable, problem, solution,
result/number). If not yet documented, note that a case-study library
needs to be built before the AI can include concrete proof points.
Why it matters: a hard guardrail already agreed is that the AI must never
fabricate a case study or result — it can only reference what's real and
approved.
Status: Parked
Note: BD needs to confirm with leadership which case studies/client
results are approved for use before any can be referenced in outreach — no
approved list exists yet. The existing guardrail stands in the meantime:
the AI must not generate or reference unverified case studies or results.
Answered by: BD team (partial) | Date: 2026-10-27

**Q-CONTENT-05** — What is Alphaleo's core differentiator versus other
Salesforce partners (e.g., speed of delivery, deep vertical expertise,
specific certifications, pricing model, post-launch support quality, team
seniority)?
Why it matters: becomes the one value proposition each email should lead
with — cold emails that make one case convert better than vague "we help
companies grow" messaging.
Status: Answered
Answer: Candidate differentiators: Salesforce expertise, customized
solutions, integration capabilities, and ongoing support. The single
primary differentiator to lead with in email messaging should be confirmed
with leadership before finalizing.
Answered by: BD team | Date: 2026-10-27

**Q-CONTENT-06** — Is there existing brand voice/tone guidance, or example
outreach emails from top-performing reps today, that the AI should model
its tone after?
Status: Parked
Note: BD agreed to provide existing outreach email examples and brand tone
guidelines so the AI can match Alphaleo's communication style, but the
actual materials have not been provided yet.
Answered by: BD team (partial) | Date: 2026-10-27

**Q-CONTENT-07** — How much of each email is a fixed template and how
much is written by the AI?
Why it matters: a consistent layout keeps quality and compliance under
control, while lead-specific content is what earns replies. This also
covers the "templates" use that the app replaces from Apollo (D-024).
Suggested default: a hybrid structure — fixed sections inserted by the
app, AI-written sections for lead-specific content.
Status: Answered
Answer: Hybrid. The app ships with a default structure for each email in
the sequence, with each section marked fixed or AI-written; the admin
can edit the structures. Fixed parts (greeting, call to action,
signature, footer) are inserted by the app, never by the AI. Defaults:
- First email (80–120 words): subject (AI, 60 characters or fewer);
  greeting "Hi {first name}," (fixed); opening, 1–2 sentences specific
  to the lead (AI); relevance, 2–3 sentences linking one Alphaleo
  offering to the lead's likely need (AI); proof point from approved
  knowledge-base content only (AI, optional — left out until case
  studies are approved, Q-CONTENT-04); call to action, e.g. "Would a
  15-minute call next week be useful?" (fixed); signature with the rep's
  name, title, Alphaleo and phone (fixed); footer (fixed).
- Follow-up 1 (70 words or fewer): sent in the same email thread;
  greeting (fixed); a new angle or benefit that doesn't repeat the first
  email (AI); a softer call to action (fixed); signature; footer.
- Follow-up 2 (50 words or fewer): same thread; greeting (fixed); a short
  close (AI); fixed line "If this isn't a priority, just let me know and
  I won't follow up."; signature; footer.
Answered by: User | Date: 2026-10-31

**Q-CONTENT-08** — How should the AI adjust its writing for different
segments (company size and industry)?
Why it matters: Alphaleo targets SMB, mid-market and enterprise
(D-036) across several industries (D-037); one generic tone fits none of
them well.
Suggested default: editable guidance profiles per size band and per
industry, combined for each lead.
Status: Answered
Answer: Segment guidance with defaults the admin can edit:
- Global voice: company description, differentiator, tone, and banned
  words. Until leadership confirms, the differentiator defaults to the
  candidate list in D-038 (Q-CONTENT-05) and the tone to "clear,
  practical, peer-to-peer" (Q-CONTENT-06 materials pending).
- Size profiles by employee count: SMB 1–200, mid-market 201–1,000,
  enterprise above 1,000.
- Industry profiles for Manufacturing, Real Estate, Hospitality,
  Healthcare and IT/Services (D-037), plus a "General" fallback.
- Each profile holds: which leads it applies to, typical pain points,
  the offering(s) to lead with (from D-035), tone and formality, things
  to avoid, optional example phrases, and the approved knowledge-base
  items it may draw on. A lead's size profile and industry profile are
  combined.
Answered by: User | Date: 2026-10-31

**Q-CONTENT-09** — What guardrails stop the AI from writing inaccurate or
risky emails, and how are drafts checked before BD reviews them?
Why it matters: an agreed rule is that the AI must never invent case
studies or results (Q-CONTENT-04); every email also goes out under a
rep's name.
Suggested default: AI uses only lead data and approved knowledge-base
content; every draft passes automatic checks before review.
Status: Answered
Answer: The AI uses only the lead's own data and approved knowledge-base
content, never invented claims, and never sees other leads' data. Every
draft is checked automatically before review:
1. All required sections present; fixed parts unchanged.
2. Length limits met; subject 60 characters or fewer.
3. No leftover placeholders (e.g., "{…}", "[Company]").
4. First name and company match the lead; no other lead's or company's
   name appears.
5. Numbers, percentages, client names and "case study" claims appear
   only if they come from the lead data or the approved knowledge-base
   items supplied.
6. Only Alphaleo's four agreed offerings (D-035) are mentioned; no
   phrase from the admin-editable banned list (e.g., "guarantee",
   "100%", spam-trigger words).
7. No links or attachments in AI-written parts.
8. No ALL-CAPS words (acronyms allowed), at most one exclamation mark.
9. Opt-out and eligibility re-checked.
Outcome: passes go to the review queue; warnings go to the review queue
with the warning shown; failures are regenerated once automatically, then
go to the review queue marked "Needs attention".
Answered by: User | Date: 2026-10-31

**Q-CONTENT-10** — What goes into the Alphaleo knowledge base for the
MVP, given that no case studies are approved yet (Q-CONTENT-04)?
Why it matters: the AI may only reference approved knowledge-base
content.
Suggested default: start with solution descriptions only; add case
studies once leadership approves them.
Status: Answered
Answer: Start with solution descriptions of Alphaleo's four offerings
(D-035) only. Each knowledge-base item has an approval status, and only
approved items are given to the AI. Case studies are added once
leadership approves them.
Answered by: User | Date: 2026-10-29

**Q-CONTENT-11** — When BD edits a draft before approving it, what can
they change?
Why it matters: the fixed parts (greeting, call to action, signature,
footer with the unsubscribe line) keep every email consistent and
compliant; reps still need to tailor the lead-specific wording.
Suggested default: reps edit only the AI-written parts; fixed parts stay
as set in the email structure, and every edit is re-checked.
Status: Answered
Answer: BD must be able to customise emails. Reps edit the AI-written
parts of each email (subject of the first email, opening, relevance,
follow-up text). The greeting, call to action, signature and footer stay
intact as set in the email structure; only an admin changes them, by
editing the email structures. Every edit is re-checked automatically
before approval, and a failed check blocks approval. Admins can edit the
default email structures, the voice and the segment guidance (tone, key
points) from the app's defaults, and restore those defaults.
Answered by: User | Date: 2026-11-04

**Q-CONTENT-12** — Should length and call to action vary by segment (e.g.
a shorter email or different call to action for enterprise)?
Why it matters: today they're set per email in the sequence and shared by
all segments (D-084); per-segment versions add setup for admins.
Suggested default: keep one length and call to action per email
structure for the MVP; segments vary tone and key points only (D-085).
Status: Parked – later phase
Answer:
Answered by: | Date:

**Q-CONTENT-13** — Can BD reps see the writing settings the admin sets
(voice, segment guidance, email structures, knowledge items)?
Why it matters: reps judge each draft's tone and fit; seeing the guidance
the AI wrote to makes that review better.
Suggested default: yes, read-only; only admins edit.
Status: Answered
Answer: Yes. Every BD user can view the voice, segment guidance, email
structures and knowledge items, read-only. Only admins edit or restore
them (D-112). The review screen also shows the guidance that applies to
each lead (voice tone plus the lead's size and industry profiles).
Answered by: User | Date: 2026-11-04

**Q-CONTENT-14** — How long should the first outreach email be? The
agreed target is 80–120 words (D-084), but in the first test drafts the
AI wrote 59–74 words for most first emails. Should we keep 80–120 and
tell the AI to write longer, or lower the target to suit shorter emails?
Why it matters: length affects reply rates and how personal the email
feels. Shorter cold emails are often read more fully, while very short
ones can feel generic. Today, emails outside the range get a warning
(not a block) in review.
Suggested default: aim for 60–100 words for the first email (closer to
what reads naturally), keeping follow-ups at 70 and 50 words or fewer.
Status: Open (for the BD team)
Answer:
Answered by: | Date:

---

## 14. Data Import & Validation (IMPORT)

Context: triggered by reviewing the real Apollo export field list (see
Q-DATA-01). Covers the internal lead data model, how Apollo fields (and
future non-Apollo sources) map to it, mandatory-field checks, and import
reporting. This theme also explicitly plans for future sources beyond
Apollo (other data providers, event lists, manual spreadsheets), which
won't share Apollo's exact field names/structure.

**Q-IMPORT-01** — The Apollo field list has no "First Name" column, only
"Last Name." Is that accurate, or was it cut off from the pasted list?
Status: Answered
Answer: First name data does exist in the source, but the column header
was missing in this manual export. Flagged by the user as a general
design lesson: when a source is a manually-prepared spreadsheet, headers
themselves can be missing or wrong (not just values) — the app's import
design needs to account for this, not just assume headers are reliable.
See D-049.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-02** — Apollo has three ID fields (Contact Id, Account Id,
Record Id). D-006 uses "Apollo's internal contact ID" as the dedup key —
confirm which field that is and what Record Id represents.
Status: Answered
Answer: Apollo Contact Id is the person-level key (the dedup key per
D-006). Apollo Account Id is the company-level key. Apollo Record Id is
Apollo's own internal record identifier and is not used by this app.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-03** — Generic/role-based emails (info@, sales@, support@) —
how should these be handled on import?
Status: Answered
Answer: Quarantine — excluded from outreach eligibility, since they don't
reach a specific named person; still visible for BD review.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-04** — Emails marked "unverified" by Apollo (not confirmed
deliverable) — how should these be treated?
Status: Answered
Answer: Eligible for outreach, with a warning shown to BD that
deliverability isn't confirmed — not blocked outright.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-05** — If Industry is missing but the company's website/domain
is known, should the app attempt automatic inference, or require manual
entry?
Status: Answered
Answer: Mark the lead incomplete and require manual entry or an admin
override — no automatic industry inference in v1.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-06a** — When the same person appears via two sources/exports
with conflicting field values, how should the app resolve it?
Status: Answered
Answer: Most-recent-source-wins, per field.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-06b** — Within one import file containing both good and bad
rows, should bad rows block the whole file?
Status: Answered
Answer: No — good rows import normally, only the specific bad rows are
quarantined (partial file success). This is distinct from the file-level
check: if a mandatory *column* is entirely missing from the file, the
whole file is still rejected.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-07** — Apollo's own engagement history (Email Sent/Open/
Bounced/Replied/Demoed, Last Contacted) reflects activity that happened in
Apollo before this app existed — import and show to BD, or ignore?
Status: Answered
Answer: Import as read-only reference context for BD (e.g., "already
emailed 3x in Apollo"); it does not drive the app's own ownership/status
logic, which runs independently.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-08** — Apollo's Intent data (Primary/Secondary Intent Topic &
Score) is present in every export at no extra cost, even though not
explicitly requested in Q-LEADS-01 — add it as an available filter?
Status: Answered
Answer: Yes, add as an optional filter/sort field since the data is
already present.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-09** — What does Apollo's "Qualify Contact" field represent,
and should the app use it?
Status: Answered
Answer: It's an Apollo-side qualification flag — import it and use it as a
filter/signal for BD.
Answered by: User | Date: 2026-10-28

**Q-IMPORT-10** — Apollo's "Stage" and "Lists" fields (Apollo's own
pipeline stage and saved-list membership) — import as reference, or
ignore?
Status: Answered
Answer: Import as read-only reference context; the app runs its own
independent status/segment model regardless.
Answered by: User | Date: 2026-10-28

Context (2026-10-29): the BD team shared a sample non-Apollo customer
file ("Agentic Databse.xlsx", 7 sheets in 3 different layouts, about
5,900 unique emails). Profiling showed: no industry column in 3 sheets,
company name missing in about 62% of the largest sheet, no source record
IDs, about 16% personal/free-mail addresses, websites that often don't
match the email domain, and one hand-made sheet that isn't import-ready.
The questions below settle how such sources are handled, keeping the MVP
as simple as possible.

**Q-IMPORT-11** — Which fields should the unified lead database keep, and
what happens to the rest?
Why it matters: keeping too many fields adds work; dropping data loses it.
Suggested default: keep only fields the app uses; drop the rest.
Status: Answered
Answer: "Drop" means not mapped into the unified model — every row is
still kept exactly as received in the source layer, so unmapped fields
can be mapped later without re-importing. Kept in the unified model:
- Person: internal ID; source references (Apollo Contact Id, source,
  file); first name, last name, job title, seniority, department;
  primary work email with verification status (including catch-all);
  secondary and tertiary emails (stored, not used for outreach);
  personal/free-mail emails (stored, flagged personal, never used for
  outreach); all phone numbers (stored, not used in MVP); person
  LinkedIn URL and other social profiles; city, state, country (used for
  time zone); BD owner.
- Company: internal ID; Apollo Account Id; company name; website/domain;
  industry (as received plus a standardized value); SIC and NAICS codes;
  employee count; annual revenue; total funding; latest funding amount
  and date; technologies used; keywords/description; founded year; HQ
  city, state, country; company phone; company LinkedIn, Facebook,
  Twitter.
- Engagement history from the source: last contacted date; sent,
  opened, bounced, replied, demoed/meeting flags; source stage/status
  (including do-not-contact/unsubscribed); source lists (as tags);
  intent signals (stored, not used in MVP).
- Not mapped (source layer only): street address lines, retail
  locations, subsidiary-of, email source/confidence details, Apollo
  Record Id, export-only columns.
- MVP selection filters: industry, company size, location, job title,
  tech stack, annual revenue, and funding.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-12** — Is the BD sample file (Sheet1 / AE 1) a source of truth
for who has already been contacted?
Status: Answered
Answer: No. It is sample data shared by BD for understanding. If a row
carries an explicit status (e.g., contacted, replied, do-not-contact),
use it; otherwise treat the lead as not yet contacted.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-13** — Do we need a separate suppression list for business
cases (existing customers, partners, competitors)?
Status: Answered
Answer: No. Use status flags BD can filter on (e.g., existing customer,
in conversation, partner, competitor). The only enforced suppression is
opt-outs (Q-IMPORT-14).
Answered by: User | Date: 2026-10-29

**Q-IMPORT-14** — How are opt-outs (unsubscribe / do-not-contact)
stored and enforced?
Status: Answered
Answer: Stored per email address, with date, reason, and source (reply,
import, or manual). A check at send time blocks opted-out addresses
across all sources and future imports; BD cannot override it. Any BD
user can add an opt-out; only a manager or admin can remove one, with a
recorded reason.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-15** — How should opt-outs be visible in the app?
Status: Answered
Answer: An "Opted out" badge in lead search, with an opt-out status
filter (opted-out leads hidden by default, shown on request); a banner
on the lead detail page with date and reason; automatic exclusion in the
campaign builder with a visible count (e.g., "14 excluded (opted out)");
and an Opt-outs page listing all opted-out addresses, searchable, with
date, reason, and source.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-16** — What happens to rows with incomplete or invalid data,
and can a whole file be rejected?
Status: Answered
Answer: Never reject a whole file. Valid rows are imported; rows missing
mandatory fields or with invalid values go to quarantine, where BD can
review them, fill in key fields, and release them into the lead
database, or discard them. Quarantine is about the data (fix before
use); opt-out is about the person (valid data, must not be emailed).
Answered by: User | Date: 2026-10-29

**Q-IMPORT-17** — Which fields are mandatory for a row to enter the lead
database?
Suggested default: a valid work email plus first name.
Status: Answered
Answer: Only two: a valid work email (correct format, not a personal or
free-mail address) and a first name (needed for personalization).
Everything else is optional. Rows whose only email is personal go to
quarantine, where BD can add a work email or discard the row.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-18** — What happens when industry is missing (whole column or
individual values)?
Status: Answered
Answer: Set industry to "Unknown". Do not quarantine for this; BD decides
whether to use these leads. Industry is not a mandatory field.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-19** — What happens when company name is missing?
Status: Answered
Answer: Derive it from the official (non-free-mail) email domain and mark
it as derived.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-20** — How are personal, secondary, and generic email
addresses handled?
Suggested default (generic): import, flag, no outreach.
Status: Answered
Answer: Personal/free-mail addresses and secondary/tertiary emails are
stored but never used for outreach in the MVP; personal addresses are
flagged as personal, with no approval path. Generic role addresses
(info@, sales@, support@) go to quarantine for BD review (the user chose
quarantine over the suggested default), consistent with D-042.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-21** — How should engagement history from a source affect
outreach?
Status: Answered
Answer: Do-not-contact/unsubscribed → recorded as an opt-out. Bounced →
email marked invalid. Replied → excluded from new campaigns and flagged
for the BD owner. Last contacted within the cooling-off period (default
90 days) → not eligible until it ends. For emails sent by the app, the
app's own records win; otherwise the most recent date wins.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-22** — How are lead owners from source files handled?
Status: Answered
Answer: Map source owner fields to app users where names match;
unmatched leads go to an "Unassigned" pool for a BD manager to assign.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-23** — How are industry names standardized across sources?
Status: Answered
Answer: A standard industry list based on NAICS sectors, using SIC/NAICS
codes where present and the industry text where not, with an admin
screen to map new industry names.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-24** — How are records identified and matched when a source
has no record ID?
Suggested default (companies): Apollo Account Id, then domain, then name.
Status: Answered
Answer: Do not generate an ID from source + email (it would change when
the email changes). Every record gets an internal ID. People without a
source ID are matched by the agreed order: email, then LinkedIn URL, then
name plus company domain. Companies are matched by Apollo Account Id,
then company domain (from the work email, website as fallback), then
normalized company name. Uncertain matches go to review.
Answered by: User | Date: 2026-10-29

**Q-IMPORT-25** — How is country handled when a source only gives a state
(needed for sending in the prospect's time zone)?
Suggested default: a default country per import.
Status: Answered
Answer: The person importing sets a default country for the file (e.g.,
India), and state names/abbreviations are standardized (e.g., KA →
Karnataka). Leads with no location use the BD rep's time zone (D-014).
Answered by: User | Date: 2026-10-29

**Q-IMPORT-26** — What happens to records the import can't confidently
match ("uncertain matches", D-077) while they wait for review?
Why it matters: holding them back stalls imports; using them freely
risks emailing the same person twice.
Suggested default: import them as separate records flagged "Possible
duplicate", kept out of campaigns until reviewed.
Status: Answered
Answer: Uncertain matches are imported as separate records flagged
"Possible duplicate". They are excluded from campaigns until a BD manager
or admin either merges them with the existing record or marks them "not
a duplicate" on a review screen. Imports never wait for this review.
Answered by: User | Date: 2026-11-02

**Q-IMPORT-27** — When a manager merges two duplicate records, which
values are kept?
Why it matters: the merged record is what BD will email.
Suggested default: most recent source pre-selected per field, editable;
all email addresses kept.
Status: Answered
Answer: For each field, the value from the most recent source is
pre-selected (D-046) and the manager can choose the other value. Email
addresses from both records are kept, with their types. Campaign history
and timelines are combined on the surviving record.
Answered by: User | Date: 2026-11-02

**Q-IMPORT-28** — What happens if the same file is uploaded again?
Why it matters: accidental re-imports create noise and confusing
reports.
Suggested default: warn with the earlier import's date and user; allow
"import anyway".
Status: Answered
Answer: The app recognises a file with identical content, warns with
the date and user of the earlier import, and lets the user cancel or
import anyway.
Answered by: User | Date: 2026-11-02

**Q-IMPORT-29** — What file types and sizes can be imported?
Why it matters: sets expectations for BD and keeps the office machine
responsive.
Suggested default: CSV or XLSX, up to 50,000 rows or 20 MB, one sheet
per import.
Status: Answered
Answer: CSV or XLSX files, up to 50,000 rows or 20 MB per import, one
sheet per import; other sheets of the same workbook are imported
separately.
Answered by: User | Date: 2026-11-02

**Q-IMPORT-30** — In the hand-made layout (AE 2), the company name appears
only on a company's first row. Should blank rows take the company from
the row above instead of deriving it from the email domain?
Why it matters: carrying the name down gives the real company name;
deriving gives a name like "Tata Test" from the domain.
Suggested default: derive from the email domain (D-071) as now; consider
carry-down for hand-made files later.
Status: Parked – later phase
Answer:
Answered by: | Date:

**Q-IMPORT-31** — When a newer file differs from a stored name only in
capitalisation (e.g., "ANIL RAO" vs "Anil Rao"), should that count as an
update?
Why it matters: the import report's "updated" count and change summary
include these.
Suggested default: keep most-recent-wins (D-046) and count it; revisit if
reports are too noisy.
Status: Parked – later phase
Answer:
Answered by: | Date:

**Q-IMPORT-32** — The BD sample sheet named "Hospitality" has industry
"hospital & health care" on every row, so its companies standardize to
Health Care. Is that sheet really hospitals rather than hotels?
Why it matters: industry filters and segment guidance (D-085) depend on it.
Suggested default: trust the data as received; BD to confirm when they
next export.
Status: Parked – later phase
Answer:
Answered by: | Date:

---

## 15. App Design & Platform (DESIGN)

Context: on 2026-10-28 the Q&A rounds were briefly paused to sketch an
overall app design, so the remaining questions could be answered with
better context. These scoping questions were asked at the start of that
discussion. The design itself is not yet drafted (see D-052–D-054).
Update (2026-10-31): the design is now under way in plan-mode/App-Design.md
(Sections 1, 1A and 2A agreed; Section 2, backend components, in
progress).
Note (2026-10-29): these technical scoping questions were recorded here
before the business/technical split. New technical questions and all
technical decisions are now kept in plan-mode/App-Design.md.

**Q-DESIGN-01** — Where should the app be hosted?
Why it matters: drives the tech stack, Microsoft 365 integration approach,
and running cost.
Suggested default: Azure (closest fit with Microsoft 365/Outlook).
Status: Answered
Answer: For the MVP, run it on a local machine. Hosting on a server is
planned for later.
Answered by: User | Date: 2026-10-28

**Q-DESIGN-02** — What is the build team's main technical comfort?
Why it matters: picks a stack the team can maintain.
Suggested default: Python-leaning, with a lightweight web frontend.
Status: Answered
Answer: Python-leaning (accepted the suggested default).
Answered by: User | Date: 2026-10-28

**Q-DESIGN-03** — How many BD reps (sending mailboxes) and what monthly
volume should the MVP be sized for?
Why it matters: sizes the sending queue, storage, and AI usage cost.
Suggested default: small — about 5 reps, a few thousand emails/month.
Status: Answered
Answer: Small — about 5 reps, a few thousand emails per month (accepted
the suggested default). Note: this is far below BD's per-mailbox target
in Q-SEND-01 (800–1,000/day/mailbox); the gap is already flagged for
Phase 2 validation.
Answered by: User | Date: 2026-10-28

**Q-DESIGN-04** — How cost-sensitive is the project for ongoing hosting
and AI usage spend?
Why it matters: the app replaces a paid tool (Apollo.io), so running cost
is part of the business case.
Suggested default: cost-conscious — minimize ongoing spend, accepting more
build effort.
Status: Answered
Answer: Cost-conscious — minimize ongoing spend (accepted the suggested
default).
Answered by: User | Date: 2026-10-28

**Q-DESIGN-05** — What existing infrastructure, accounts, or tools should
the design reuse (e.g., Microsoft 365 tenant/admin access, an existing
server or cloud account, an Anthropic/Claude account, source control)?
Why it matters: avoids designing around things we already have, and
identifies access we must request early (especially Microsoft 365 admin
consent for sending and reply monitoring).
Suggested default: assume Microsoft 365 accounts exist for each rep and
nothing else; confirm admin access for app registration.
Note: as actually asked in the session, this question focused on the two
MVP integrations — what is the current state of access to Microsoft 365
(sending/reading mail via Microsoft Graph) and to an AI API?
Status: Answered
Answer: Every BD rep already has an Outlook / Microsoft 365 email
account. Microsoft Graph access (app registration and mail permissions)
is not set up yet and needs to be. For the MVP, the Gemini API will be
used for writing emails and other AI tasks, instead of the Claude/
Anthropic API assumed in the design brief.
Explanation given: an Outlook account lets a person send mail by hand.
For the app to send and read mail on a rep's behalf it must use
Microsoft Graph, Microsoft's official API for Microsoft 365 mail (older
password-based SMTP sending is being retired). A Microsoft 365 admin
registers the app once in the company tenant (free), grants send-mail
and read-mail permissions, and each rep then signs in once.
Answered by: User | Date: 2026-10-28

**Q-DESIGN-06** — Who is the Microsoft 365 admin who can register the app
in Alphaleo's tenant and approve its mail permissions?
Why it matters: without admin approval, the app cannot send or read mail
through Microsoft Graph, which blocks both sending and reply detection.
Suggested default: Alphaleo's IT/Microsoft 365 owner, to be identified
before the build starts.
Status: Answered
Answer: The user has Microsoft 365 admin access, so the team can register
the app and grant the Graph permissions itself. Registration will happen
when development reaches the Microsoft 365 integration step, not now.
Until then, everything else is built and tested with a mock / "draft
only" sender (see D-057, D-058).
Answered by: User | Date: 2026-10-28

**Q-DESIGN-07** — Should we use the paid tier of the Gemini API rather
than the free tier?
Why it matters: lead personal data (names, roles, companies, email
replies) is sent to the AI. On the free tier, Google may use submitted
data to improve its products, which is a privacy/GDPR concern; the paid
tier does not use it that way.
Suggested default: paid tier — at a few thousand emails per month the
cost stays low.
Status: Answered
Answer (Superseded 2026-10-29): Both, by stage. Development and testing use the Gemini free tier
with test data only: real email addresses are replaced with test
addresses, and other personal details (names, phone numbers, LinkedIn
URLs) are replaced or masked; company-level details (industry, size,
tech stack) stay realistic so email quality can be judged. Before any
real prospect data is processed (pilot or production), switch to a paid
Gemini tier. The tier/key is a configuration setting, and the app refuses
to process real (non-test) lead data when set to a free-tier key. The
provider's data-use terms are a compliance check before go-live (D-061).
Answered by: User | Date: 2026-10-28
Answer (current): Simplified. Development and testing use a free-tier
Gemini API key, set as a configuration setting. Testing runs only on a
test dataset selected by hand with the app's own filters (e.g., test
industry values and test email addresses). No masking, test-data
generator, or test/real flagging is needed in the MVP. A paid Gemini tier
is used later, before any real prospect data is processed; switching only
requires changing the API key setting (D-062).
Answered by: User | Date: 2026-10-29

**Q-DESIGN-08** — How does the app tell test data from real data, and a
free-tier key from a paid one, so the safeguard in D-061 can work?
Why it matters: the AI provider's API does not reliably report which tier
a key belongs to, and a real dump looks the same as a test dump unless
it's labelled.
Suggested default: (a) only datasets created by the test-data generator
are marked "test"; every other import is treated as real. (b) The key's
tier is declared in configuration ("free" or "paid"); if it's missing,
the app assumes "free". Real data is blocked unless the tier is "paid".
Status: Withdrawn — no longer needed after D-062 (no masking, test/real
flagging, or safeguard in the MVP). Withdrawn 2026-10-29.
Answer:
Answered by: | Date:

**Q-DESIGN-09** — What should replace real email addresses in test data?
Why it matters: once the real Microsoft 365 sender is connected, any
test email that slips through must land somewhere safe, never at a real
prospect.
Suggested default: addresses on a reserved test domain that cannot
receive mail (e.g., lead0001@example.com), plus a few real internal
Alphaleo test mailboxes for end-to-end sending tests. The sender refuses
to send to any address outside an allow-list while in test mode.
Status: Withdrawn — no longer needed after D-062 (no masking, test/real
flagging, or safeguard in the MVP). Withdrawn 2026-10-29.
Answer:
Answered by: | Date:

**Q-DESIGN-10** — In masked test data, should company names and website
domains stay real, or be replaced too?
Why it matters: they are company-level (useful for judging email
quality), but a real company name plus a real job title can sometimes
identify a specific person.
Suggested default: keep company name, domain, industry, size and tech
stack real; replace person name, email, phone and LinkedIn URL; keep job
title but drop it when the company is very small (e.g., under 20
employees).
Status: Withdrawn — no longer needed after D-062 (no masking, test/real
flagging, or safeguard in the MVP). Withdrawn 2026-10-29.
Answer:
Answered by: | Date:

---

## Decisions Log

**D-001** (2026-10-21, Q-OWN-01) — Lead ownership/conflict handling: no
restriction in v1. Any rep can contact any lead; no automatic claim or
lock. Revisit if this causes real-world duplicate-contact problems.
Confirmed by BD team, 2026-10-27.
Related (2026-10-29): D-075 adds a BD owner and an Unassigned pool for
assignment and notifications; still no lock.

**D-002** (2026-10-21, Q-SEND-02) — Sending identity control model: admin
decides per campaign — configurable, not fixed to either per-rep or shared
mailboxes. Confirmed by BD team, 2026-10-27.

**D-003** (2026-10-21, Q-REPLY-02) — Reply handling v1 scope: classify +
notify BD only, no auto-reply, in v1. Auto-response generation is an
explicit fast-follow, not v1 scope. Confirmed by BD team, 2026-10-27.

**D-004** (2026-10-21, Q-RULES-02) — Opt-out scope: individual contact
only — unsubscribe suppresses just that person, not the whole company
domain. Confirmed by BD team, 2026-10-27.
Related (2026-10-29): refined by D-066 — opt-outs are stored and
enforced per email address.

**D-005** (2026-10-21, Q-DATA-02) — Export delivery: manual/on-demand
upload for v1, not a scheduled automated API pull. Confirmed by BD team,
2026-10-27.

**D-006** (2026-10-21, Q-DATA-03) — Lead identifier for de-dup: Apollo
contact ID, falling back to normalized email. Confirmed by BD team,
2026-10-27.

**D-007** (2026-10-21, Q-DATA-04) — Stale-data handling for queued
cold-outreach emails: no special handling — send as composed regardless of
minor data changes; rely on bounce/failure tracking, not proactive
staleness detection. Accuracy matters more post-reply, handled manually by
BD at that stage. Confirmed by BD team, 2026-10-27, with the added
requirement that the app must never send to invalid addresses or
unsubscribed contacts.

**D-008** (2026-10-21, Q-DATA-05) — Lead history: latest version only, no
change history/changelog. Confirmed by BD team, 2026-10-27.

**D-009** (2026-10-21, Q-LEADS-02) — Saved filters: yes — BD can save a
named filter combination as a reusable segment. Confirmed by BD team,
2026-10-27.

**D-010** (2026-10-21, Q-LEADS-03) — Lead selection method: both —
individual pick and select-all-matching supported. Confirmed by BD team,
2026-10-27.

**D-011** (2026-10-21, Q-LEADS-04) — Do-not-contact exclusion timing:
exclude at search time — do-not-contact leads never appear in filtered
results. Confirmed by BD team, 2026-10-27, with the added requirement that
the app re-check do-not-contact status again immediately before sending.

**D-012** (2026-10-21, Q-ROLES-01) — Roles: confirmed as described — BD
rep, BD manager, Admin; no separate Sales/handoff role in v1. Confirmed by
BD team, 2026-10-27.

**D-013** (2026-10-21, Q-SEND-02b) — Default sending identity when an
admin doesn't explicitly configure a campaign: each rep's own mailbox.
Confirmed by BD team, 2026-10-27.

**D-014** (2026-10-21, Q-SEND-03) — Sending windows: prospect's local time
zone when inferable, falling back to rep's time zone. Confirmed by BD
team, 2026-10-27.

**D-015** (2026-10-21, Q-SEND-04) — Pause/resume: explicit resume
required, no auto-resume. Confirmed by BD team, 2026-10-27.

**D-016** (2026-10-21, Q-REPLY-04) — Reply detection scope: same email
thread only for v1. Confirmed by BD team, 2026-10-27.
Related (2026-10-31): D-080 adds an exception for unsubscribe emails
only; all other replies stay same-thread.

**D-017** (2026-10-22, Q-NOTIFY-01) — Notification channel: email only
for v1. Confirmed by BD team, 2026-10-27.

**D-018** (2026-10-22, Q-SEND-05) — Failed-send retries: a few retries
with backoff (~2–3 attempts, increasing delay, over about a day), then
surface to BD as "failed." Confirmed by BD team, 2026-10-27.
Related (2026-11-02): exact timing set by D-097 (30 min, 4 h, 20 h).

**D-019** (2026-10-22, Q-ROLES-02) — Bulk/auto-send permission: manager
grants it per rep (earned/trust permission), not open-by-default or
admin-only/global. Confirmed by BD team, 2026-10-27.

**D-020** (2026-10-22, Q-RULES-01) — Contact frequency limit: yes,
admin-configurable default (e.g. ~3 touches per lead per 30 days with a
minimum gap). Confirmed by BD team, 2026-10-27.

**D-021** (2026-10-22, Q-ROLES-03) — Manager edit rights: view only — a
BD manager can see status/progress across all reps but cannot edit another
rep's drafts or campaigns. Confirmed by BD team, 2026-10-27.

**D-022** (2026-10-22, Q-NOTIFY-03) — Post-reply lead handoff: a simple
in-app status tag ("Qualified"/"Handed Off to Sales") for tracking and
reporting; the actual handoff itself happens outside the tool, no
Salesforce integration needed. Confirmed by BD team, 2026-10-27, with exact
label wording specified.

**D-023** (2026-10-22, Q-REPORT-01) — Reporting scope: both — individual
BD reps see their own activity dashboard; managers/admins see an aggregate
view across the team. Confirmed by BD team, 2026-10-27.

**D-024** (2026-10-27, Q-DATA-06) — Apollo-replacement scope: BD currently
uses Apollo for prospect database search, filtering (industry/company/
title/location), building lead lists, viewing contact details, exporting
data, and email sequences/templates — this new app must replace all of
these in v1 for it to actually displace Apollo usage.
Related (2026-10-31): sequences → D-082; templates → D-084 (hybrid
structures); export → D-087.

**D-025** (2026-10-27, Q-LEADS-01) — Additional v1 filter fields: funding
stage and existing Salesforce usage, alongside the core fields (industry,
company, size, region, role, tech stack). Hiring signals and intent score
not requested for v1.

**D-026** (2026-10-27, Q-OWN-02) — Lead contact-history visibility:
visible to all reps (who contacted a lead, when, and current status) to
help avoid duplicate outreach, even without a hard ownership restriction
(see D-001).

**D-027** (2026-10-27, Q-OWN-03) — Same-company multi-contact: allowed for
different reps to contact different people at the same company, but the
app shows a note when a colleague is already engaging that account.

**D-028** (2026-10-27, Q-PERS-01) — AI draft feedback loop: editing the
draft before sending is sufficient for v1; a structured rating/feedback
feature is deferred, to be considered later if needed.

**D-029** (2026-10-27, Q-SEND-01) — Per-mailbox daily sending volume: BD
wants to support ~800–1,000 emails/day/mailbox at a controlled pace
(covering initial outreach plus follow-ups), aiming to complete a full
campaign including follow-ups within one week; app should support campaign
scheduling and follow-up tracking toward that goal. ⚠ Flagged for Phase 2
technical validation against real Microsoft 365 tenant limits and cold-
email deliverability best practice before being treated as locked-in — see
the note under Q-SEND-01.
Related (2026-10-31): MVP mailbox defaults are 30/day and 8/hour (D-083).
With the default sequence (D-082) the last follow-up goes out about 9
calendar days after the first email, so the one-week target can't be
met; the completion estimate shows this. Not changed, flagged only.

**D-030** (2026-10-27, Q-REPLY-01) — Reply categories: the six originally
proposed categories (interested, not interested, not now, wrong person,
out-of-office, unsubscribe) are sufficient for v1.

**D-031** (2026-10-27, Q-REPLY-03) — Auto-reply suppression: the three
listed situations (out-of-office, not-interested, unsubscribe) are
sufficient auto-reply blockers for v1; no additional forwarding/domain-
mismatch rule needed yet. Unsubscribe replies also mark the contact
do-not-contact (reaffirms D-004).

**D-032** (2026-10-27, Q-NOTIFY-02) — Reply notification SLA: notify BD
within minutes of a reply arriving; track a same-business-day follow-up
SLA.

**D-033** (2026-10-27, Q-COMP-01) — Compliance jurisdiction: both US
(CAN-SPAM) and EU/UK (GDPR) apply, since prospects may be in either
region; the app must support both compliance regimes.

**D-034** (2026-10-27, Q-CHAN-01) — Multi-channel data model: build lead/
contact history generically now to support multiple channels (email,
WhatsApp, LinkedIn) even though only email ships in v1.

**D-035** (2026-10-27, Q-CONTENT-01) — Alphaleo's Salesforce offerings:
new implementation, migration from another CRM, optimization/health-check
of existing orgs, and custom development/integrations/managed support —
all four are real, current offerings the AI can credibly reference.

**D-036** (2026-10-27, Q-CONTENT-02) — Target segment: SMB, mid-market,
and enterprise are all viable targets, tailored by each account's specific
Salesforce requirements and business needs — no single segment focus.

**D-037** (2026-10-27, Q-CONTENT-03) — Target industries (draft list,
final priority pending leadership): Manufacturing, Real Estate,
Hospitality, Healthcare, and IT/Services.

**D-038** (2026-10-27, Q-CONTENT-05) — Candidate differentiators (final
single lead-with message pending leadership confirmation): Salesforce
expertise, customized solutions, integration capabilities, and ongoing
support.

**D-039** (2026-10-27, Q-RULES-03) — Existing-customer suppression list:
none exists today. The app needs a feature letting BD/admin build and
maintain this list from scratch as outreach begins, rather than importing
it from an existing source — there isn't one.
Superseded (2026-10-29) by D-065 — status flags replace a
business-case suppression list.

**D-040** (2026-10-28, Q-DATA-01) — Internal lead data model: contact,
company, and source/metadata field groups, with Apollo fields mapped into
them (e.g. Technologies → tech-stack personalization input, Website →
derived company domain, # Employees → size band). Future non-Apollo
sources get their own admin-maintained mapping profile, matched by column
*name* (never column position), each with a declared format so values
normalize into one canonical format regardless of source.

**D-041** (2026-10-28, Q-IMPORT-02) — Lead identity/dedup design: each
lead gets an internal `internal_lead_id` linked to one or more
`{source_system, source_record_id}` pairs. For Apollo specifically: Apollo
Contact Id is the person-level dedup key (reaffirms D-006), Apollo Account
Id is the company-level key (useful for same-company visibility, Q-OWN-03),
and Apollo Record Id is not used by the app.

**D-042** (2026-10-28, Q-IMPORT-03, Q-IMPORT-04) — Email outreach
eligibility: generic/role-based emails (info@, sales@, support@) are
quarantined and excluded from outreach. Emails marked "unverified" by
Apollo are still outreach-eligible but shown to BD with a deliverability
warning, not blocked.
Related (2026-10-29): generic emails still go to quarantine (D-072);
the unverified-email warning stays.

**D-043** (2026-10-28) — Mandatory fields for outreach eligibility: email,
industry, a record identifier, and company name (adding company name to
the user's original three). Company domain is strongly recommended but not
hard-mandatory. File-level import check: confirm all mandatory columns
exist (via the source's mapping profile) before importing anything — if
any are missing, reject the whole file. Record-level check: confirm
mandatory values are present and valid per row.
Superseded (2026-10-29) by D-069 (mandatory = work email + first name)
and D-068 (never reject a whole file).

**D-044** (2026-10-28, Q-IMPORT-06b) — Import failure handling, tiered:
missing/invalid hard-mandatory field → quarantine the row (fixable, not
discarded); missing a strongly-recommended field (e.g. unmapped industry,
no company domain) → import as incomplete, excluded from outreach until
fixed or admin-overridden; missing a mandatory column at the file level →
reject the entire file. Within one file, only the specific bad rows are
quarantined — good rows still import normally (partial file success).
Superseded (2026-10-29) by D-068 — no whole-file rejection; invalid
rows go to quarantine.

**D-045** (2026-10-28, Q-IMPORT-05) — Missing industry with a known
company domain: mark the lead incomplete and require manual entry or an
admin override; no automatic industry inference in v1.
Superseded (2026-10-29) by D-070 — missing industry is set to
"Unknown".

**D-046** (2026-10-28, Q-IMPORT-06a) — Cross-source/duplicate conflict
resolution: most-recent-source wins, applied per field (not whole-record).
Related (2026-10-29): for engagement dates, D-073 applies (app's own
records win, otherwise most recent date).

**D-047** (2026-10-28, Q-IMPORT-07, Q-IMPORT-10) — Apollo's own
engagement history (Email Sent/Open/Bounced/Replied/Demoed, Last
Contacted) and its Stage/Lists fields are imported as read-only reference
context for BD, but do not drive the app's own ownership, status, or
segment logic — that runs independently per this project's own decisions.
Superseded (2026-10-29) by D-073 — engagement history now drives
defined eligibility rules.

**D-048** (2026-10-28, Q-IMPORT-08, Q-IMPORT-09) — Apollo's Intent data
(Primary/Secondary Intent Topic & Score) and the "Qualify Contact" flag
are both imported and surfaced as optional filters/signals for BD, even
though neither was explicitly requested in Q-LEADS-01 — the data is
already present in every export at no extra cost.
Superseded (2026-10-29) by D-074 — intent and Qualify Contact stored
but not used in the MVP.

**D-049** (2026-10-28, Q-IMPORT-01) — Manual/spreadsheet-source design
principle: a manually-prepared export can have missing or mislabeled
column headers, not just missing values (e.g., First Name data existing
without a proper header). The import/mapping design must let an admin
manually correct or reassign column headers during the mapping step,
rather than only matching against whatever header text is already present.

**D-050** (2026-10-28) — Import report design: after each import, show
totals (received, imported, updated, unchanged, duplicates found,
quarantined, rejected), a reason-coded breakdown of failures, and a
downloadable list of the specific failed/quarantined rows. For updated
leads, also show a one-time "what changed in this import" summary — a
transient, per-import report, which does not conflict with the
no-ongoing-changelog decision (D-008) since it isn't a permanent per-lead
history.

**D-051** (2026-10-28, Q-COMP-02) — Unsubscribe/opt-out footer and process:
none exists today. One needs to be created (standard footer text plus a
documented process for honoring opt-outs within the legally required
window) as part of this project.

**D-052** (2026-10-28, app-design brief) — Phased delivery, MVP first. MVP
scope: import dumps with validation and de-duplication, filter leads,
generate personalized emails, BD review and edit, queued sending via
Outlook within daily limits, email history, and reply detection with BD
alerts. Everything else is in later phases.

**D-053** (2026-10-28, app-design brief) — Lead data lives in a structured
database and is filtered exactly. RAG/vector search is used only for the
Alphaleo knowledge base (case studies, solution descriptions) and
optionally for semantic search on text fields. Natural-language searches
are converted into exact filters that are shown to the user. The design
must allow adding WhatsApp and LinkedIn later without major rework
(consistent with Q-CHAN-01).

**D-054** (2026-10-28, Q-DESIGN-01, Q-DESIGN-02, Q-DESIGN-03, Q-DESIGN-04)
— MVP design inputs: runs on a local machine first (server hosting later),
Python-leaning stack, sized for about 5 reps and a few thousand emails per
month, cost-conscious on ongoing hosting and AI spend. These are inputs to
the app design, to be confirmed when the design is agreed.
Technical — these design inputs drove the choices maintained in
App-Design.md (TD-001 to TD-010, TD-014).

**D-055** (2026-10-28, Q-DESIGN-05) — Microsoft 365 integration goes
through Microsoft Graph. For the MVP, each rep signs in once (delegated
access), so the app can only use that rep's own mailbox for sending and
reply detection. Registering the app in the Microsoft 365 tenant is an
MVP setup step.
Superseded (2026-10-28) by D-057 — the user chose application
permissions with admin consent instead of per-rep sign-in.
Technical — superseded; the current version is maintained in
App-Design.md as TD-011.

**D-056** (2026-10-28, Q-DESIGN-05) — The Gemini API is the AI provider
for the MVP (email writing, reply classification, search interpretation).
AI calls go through a thin provider layer so the model can be swapped
later. This replaces the Claude-specific options (Claude Agent SDK /
Managed Agents) mentioned in the original design brief.
Refined (2026-10-28) by D-060, which defines the provider-neutral AI
layer in detail.
Technical — maintained in App-Design.md as TD-009 and TD-013.

**D-057** (2026-10-28, Q-DESIGN-05, Q-DESIGN-06) — Microsoft 365 access
uses Microsoft Graph application permissions (Mail.Send, Mail.ReadWrite)
with admin consent, restricted to a mail-enabled security group of BD
mailboxes. The restriction uses Exchange Online's current method (RBAC
for Applications); the older application access policies are the
fallback. Emails are sent from each BD rep's own mailbox. The user has
admin access; registration happens when development reaches the
Microsoft 365 integration step. Supersedes D-055.
Technical — maintained in App-Design.md as TD-011.

**D-058** (2026-10-28, Q-DESIGN-06) — Until Microsoft 365 is integrated,
the app uses a mock / "draft only" sender that saves emails instead of
sending them. Sending sits behind one interface so the real Graph sender
can be plugged in later without changing the rest of the app.
Technical — maintained in App-Design.md as TD-005.

**D-059** (2026-10-28) — Secrets (tenant ID, client ID, client secret,
AI API keys) are supplied only through environment variables / a .env
file excluded from source control. They are never stored in code, plan
files, or this document.
Technical — maintained in App-Design.md as TD-008 and TD-012.

**D-060** (2026-10-28, Q-DESIGN-05) — Provider-neutral AI layer: the rest
of the app calls only this layer (e.g., "generate email", "classify
reply", "interpret search"), never a provider's API directly. Provider
and model are chosen by configuration, per task, so providers can be
switched or mixed (e.g., Gemini, Claude, OpenAI) without code changes
elsewhere. Prompts and output formats are provider-independent. The
provider and model used are logged for every generated email, to compare
quality and cost later. Google Gemini is the initial provider.
Technical — maintained in App-Design.md as TD-009, TD-010 and TD-013.

**D-061** (2026-10-28, Q-DESIGN-07) — AI data protection by stage:
development and testing use the Gemini free tier with test data only
(personal fields replaced or masked, company-level fields realistic). The
app includes a tool that generates a test dataset from a real dump with
personal fields replaced. Before any real prospect data is processed
(pilot or production), switch to a paid Gemini tier; the tier/key is a
configuration setting, and the app refuses to process real lead data
with a free-tier key. The AI provider's data-use terms are a compliance
check before go-live.
Superseded (2026-10-29) by D-062 — the user simplified the approach.
Technical — superseded; the current approach is maintained in
App-Design.md as TD-013.

**D-062** (2026-10-29, Q-DESIGN-07) — AI testing approach for the MVP:
development and testing use a free-tier Gemini API key, set as a
configuration setting. Testing runs only on a test dataset selected by
hand with the app's own filters (e.g., test industry values and test
email addresses). No masking, test-data generator, or test/real flagging
or safeguard is built in the MVP. A paid Gemini tier is used before any
real prospect data is processed; switching only requires changing the API
key setting. Kept from D-061: review the AI provider's data-use terms
before go-live. Supersedes D-061.
Business part stays here (paid tier before any real prospect data;
review the provider's data-use terms before go-live). Technical setup is
maintained in App-Design.md as TD-013.

**D-063** (2026-10-29, Q-IMPORT-11) — Unified lead model keeps only the
listed person, company, and engagement-history fields; every source row
is still stored as received, so other fields can be mapped later without
re-importing. Annual revenue and funding join industry, size, location,
title, and tech stack as MVP selection filters.

**D-064** (2026-10-29, Q-IMPORT-12) — BD sample data is not a source of
truth for outreach status: explicit row statuses are used; otherwise the
lead counts as not yet contacted.

**D-065** (2026-10-29, Q-IMPORT-13) — No business-case suppression list;
BD-filterable status flags instead (existing customer, in conversation,
partner, competitor). Supersedes D-039.

**D-066** (2026-10-29, Q-IMPORT-14) — Opt-outs are the only enforced
suppression: stored per email address with date, reason, and source; a
send-time check blocks them across all sources and future imports with
no BD override; any BD user can add one; only a manager/admin can remove
one, with a recorded reason. Refines D-004 (opt-out is per address).

**D-067** (2026-10-29, Q-IMPORT-15) — Opt-out visibility: badge and
filter in lead search (hidden by default), banner on lead detail,
automatic exclusion with a visible count in the campaign builder, and a
searchable Opt-outs page.

**D-068** (2026-10-29, Q-IMPORT-16) — Never reject a whole file. Valid
rows import; rows missing mandatory fields or with invalid values go to
quarantine, where BD can fix and release them, or discard them.
Supersedes the file-rejection parts of D-043 and D-044.

**D-069** (2026-10-29, Q-IMPORT-17) — Mandatory fields: a valid work email
and a first name only. Rows whose only email is personal go to
quarantine. Supersedes D-043.

**D-070** (2026-10-29, Q-IMPORT-18) — Missing industry is set to
"Unknown"; not quarantined, not mandatory. Supersedes D-045.

**D-071** (2026-10-29, Q-IMPORT-19) — Missing company name is derived from
the official (non-free-mail) email domain and marked as derived.

**D-072** (2026-10-29, Q-IMPORT-20) — Personal/free-mail and
secondary/tertiary emails are stored but never used for outreach in the
MVP (personal ones flagged, no approval path). Generic role emails go to
quarantine (D-042 still applies).

**D-073** (2026-10-29, Q-IMPORT-21) — Engagement-history rules:
do-not-contact/unsubscribed → opt-out; bounced → email invalid; replied
→ excluded from new campaigns and flagged for the BD owner; contacted
within the cooling-off period (default 90 days) → not eligible until it
ends. App's own send records win; otherwise most recent date wins.
Supersedes D-047; refines D-046 for engagement dates.

**D-074** (2026-10-29, Q-IMPORT-11, Q-IMPORT-21) — Intent signals and
Apollo's Qualify Contact flag are stored but not used in the MVP; source
stage/status and lists are kept (lists as tags). Supersedes D-048.

**D-075** (2026-10-29, Q-IMPORT-22) — Source owners map to app users by
name; unmatched leads go to an "Unassigned" pool for a BD manager to
assign. Ownership is for assignment and notifications, not a lock
(D-001 still applies).

**D-076** (2026-10-29, Q-IMPORT-23) — Industry standardization against a
NAICS-sector list, using SIC/NAICS codes where present and text where
not, with an admin screen to map new industry names.

**D-077** (2026-10-29, Q-IMPORT-24) — No generated source+email IDs.
Every record gets an internal ID; people are matched by source ID, then
email, LinkedIn URL, then name plus company domain; companies by Apollo
Account Id, then domain (work email first, website fallback), then
normalized name; uncertain matches go to review. Consistent with D-041.

**D-078** (2026-10-29, Q-IMPORT-25) — A default country is set per import,
and state names/abbreviations are standardized; leads with no location
use the BD rep's time zone (D-014).

**D-079** (2026-10-31, Q-COMP-04) — MVP unsubscribe: no public web
unsubscribe page in the MVP (deferred to the public-hosting phase; the
office-network-only setup stays). Every email footer says "Reply with
'unsubscribe' to opt out", detected by reply classification, and every
email has an "Unsubscribe" button that opens a pre-filled email to the
sending rep's mailbox, processed the same way. Later: point the button
at a web unsubscribe page and add the mail-client unsubscribe link.

**D-080** (2026-10-31, Q-REPLY-05) — Exception to same-thread reply
detection (D-016), for unsubscribe only: a new email with the subject
"Unsubscribe" from an address the app has emailed opts out the sender's
address and the address named in the body, by fixed rule.

**D-081** (2026-10-31, Q-COMP-07, Q-COMP-05, Q-COMP-06) — Real-sending
gate: until the admin switches on real sending, emails go only to an
admin-maintained test-recipient list. The switch requires Microsoft 365
sending connected, a tested working unsubscribe option, saved footer
wording, and a saved postal address; switching it on is recorded.

**D-082** (2026-10-31, Q-SEND-06) — Default sequence for all campaigns:
first email, follow-up 1 on business day 3, follow-up 2 on business day
7; follow-ups count toward the 3-in-30-days contact limit; the 90-day
cooling-off applies to entering a new campaign; follow-ups stop on any
reply, bounce, opt-out, or Qualified/Handed Off status; due follow-ups
are sent before new first emails when a mailbox cap is reached.
Refined (2026-11-02) by D-093: out-of-office replies do not stop the
sequence.

**D-083** (2026-10-31, Q-RULES-04) — Sending and contact limits are
global admin-only settings (no per-campaign override in the MVP).
Defaults: 3 emails per person in 30 days with a 2-business-day minimum
gap; 90-day cooling-off; at most 2 people per company contacted per day;
30 emails per day and 8 per hour per mailbox, raised gradually by the
admin; sending window Mon–Fri 09:00–17:00 in the prospect's time zone.
Conflicting settings trigger a warning before saving; a campaign
completion estimate warns when a target end date can't be met; opt-outs
are always enforced. Refines D-020 (defaults now set).

**D-084** (2026-10-31, Q-CONTENT-07) — Hybrid email structure: default
structures for the first email and each follow-up, with sections marked
fixed (inserted by the app) or AI-written, editable by the admin. This
is how the MVP covers Apollo's "templates" (D-024).

**D-085** (2026-10-31, Q-CONTENT-08) — Segment guidance: an editable
global voice plus size profiles (SMB 1–200, mid-market 201–1,000,
enterprise above 1,000 employees) and industry profiles (D-037 list plus
General), combined per lead.

**D-086** (2026-10-31, Q-CONTENT-09) — AI guardrails: the AI uses only
the lead's data and approved knowledge-base content and never invents
claims; every draft passes the nine automatic checks in Q-CONTENT-09
before review (pass / warning / one automatic retry then "Needs
attention").

**D-087** (2026-10-31, Q-DATA-07) — CSV export in the MVP for lead search
results and campaign results; all roles, within what they can already
see; every export logged. Covers the "export" part of D-024.

**D-088** (2026-10-29, Q-CONTENT-10) — The knowledge base starts with
solution descriptions of the four offerings only; items carry an
approval status and only approved items reach the AI; case studies are
added once approved (Q-CONTENT-04).

**D-089** (2026-10-29, Q-LEADS-05) — The latest funding round type is
stored on the company and offered as the funding-stage filter requested
in D-025. Extends the unified model in D-063.

**D-090** (2026-11-02, Q-SEND-07) — All three emails of a lead's sequence
are drafted at campaign start and reviewed together; follow-ups no
longer needed are cancelled automatically.

**D-091** (2026-11-02, Q-ROLES-04) — Bulk approval is allowed only for
drafts that passed every check with no warnings, after the rep has seen
them in the list; drafts with warnings or "Needs attention" are approved
one at a time. Not auto-send (D-019 stays deferred).

**D-092** (2026-11-02, Q-IMPORT-26) — Uncertain matches are imported as
separate records flagged "Possible duplicate", excluded from campaigns
until a manager or admin merges them or marks them "not a duplicate".
Refines D-077.

**D-093** (2026-11-02, Q-REPLY-06) — Out-of-office replies are recorded
but do not stop the sequence; all other reply categories stop it.
Refines D-082.

**D-094** (2026-11-02, Q-REPLY-07) — Replies classified below 0.7
confidence (admin-adjustable) are marked "Unclear – please check"; the
sequence stops and the rep is notified. Replies that can't be classified
(AI unavailable) are handled the same way as "Unclassified".

**D-095** (2026-11-02, Q-NOTIFY-04) — Reply alerts go to the sending rep
and, if different, the lead's owner; managers see replies in their
overview without individual alerts.

**D-096** (2026-11-02, Q-SEND-08) — Permanent bounce → address invalid
at once and sequence stopped; temporary bounce → one retry the next
business day, then invalid if it bounces again.

**D-097** (2026-11-02, Q-SEND-09) — Failed sends are retried after 30
minutes, 4 hours and 20 hours, then marked "Failed" and the rep is
notified. Refines D-018.

**D-098** (2026-11-02, Q-LEADS-06) — Saved segments are private to their
owner by default, with an option to share with the team. Refines D-009.

**D-099** (2026-11-02, Q-COMP-08) — Admin-only "Erase person" action in
the MVP: removes the person's personal data everywhere in the app but
keeps the address on the opt-out list; each erasure is audit-logged.

**D-100** (2026-11-02, Q-COMP-09) — Full reply text is stored only for
replies to the app's own emails; other mailbox messages are never
stored; no automatic deletion in the MVP, retention period to be agreed
before go-live.

**D-101** (2026-11-02, Q-OWN-04) — Any BD user can set "Qualified" /
"Handed Off to Sales" on any lead; every change is logged. Consistent
with D-001 and D-022.

**D-102** (2026-11-02, Q-REPORT-03) — The MVP includes a simple activity
page (rep's own figures; team totals for managers): sent, replies by
category, drafts awaiting review, failed sends, missed same-day
follow-ups. Richer dashboards later. Adds to D-052; implements D-023 in
a minimal form.

**D-103** (2026-11-02, Q-SEND-10) — The MVP is complete when Microsoft 365
sending and reply checking work end to end with test recipients; real
sending to prospects follows once the go-live items are settled (D-062,
D-081, D-100). Clarifies D-052 and D-058.

**D-104** (2026-11-02, Q-ROLES-05) — Any BD user can upload imports with
an existing source profile and fix headers for that file; only admins
create or edit saved source profiles and industry/state mappings.

**D-105** (2026-11-02, Q-REPLY-08) — Reps reply to prospects in Outlook;
the app shows replies with a link to Outlook and the rep marks them
handled in the app. No manual reply sending from the app in the MVP.

**D-106** (2026-11-02, Q-LEADS-07) — Lead search shows all leads except
opted-out ones by default, with eligibility badges; "Eligible only" is
an optional filter. Refines D-011 together with D-067.

**D-107** (2026-11-02, Q-ROLES-06) — Any BD user can fix and release
quarantined rows; only the importer, a manager or an admin can discard
them.

**D-108** (2026-11-02, Q-IMPORT-27) — Duplicate merge: most recent source
pre-selected per field (D-046) and editable; email addresses, campaign
history and timelines from both records are kept on the merged record.

**D-109** (2026-11-02, Q-IMPORT-28) — Re-uploading a file with identical
content shows a warning (earlier date and user) with cancel or import
anyway.

**D-110** (2026-11-02, Q-IMPORT-29) — Imports accept CSV or XLSX, up to
50,000 rows or 20 MB, one sheet per import.

**D-111** (2026-11-02, Q-COMP-10) — Quarantined-row and change-summary
downloads are limited to the importer, managers and admins, and every
download is audit-logged.

**D-112** (2026-11-04, Q-CONTENT-11) — BD customises drafts by editing the
AI-written parts only; greeting, call to action, signature and footer
stay as set in the email structures (admin-editable). Every edit is
re-checked and a failed check blocks approval. Admins edit structures,
voice and segment guidance from the app defaults and can restore them.
Refines D-028 and D-084.

**D-113** (2026-11-04, Q-CONTENT-13) — All BD users can view the voice,
segment guidance, email structures and knowledge items read-only; only
admins edit them. The review screen shows each lead's applicable guidance.
Refines D-085 and D-112.

---

## Open Questions & Assumptions

- Note (2026-10-29): "founded year" is in the unified company model
  (D-063), but none of the analysed sources (Apollo dump, BD sample file)
  provides it; it stays empty until a source does.

- Q-DESIGN-05 — Answered 2026-10-28 (see D-055, D-056).
- Q-DESIGN-06 — Answered 2026-10-28 (user is the M365 admin; see D-057).
- Q-DESIGN-07 — Answered 2026-10-28 (free tier for test data only, paid
  tier before real data; see D-061).
- Q-DESIGN-08, Q-DESIGN-09, Q-DESIGN-10 — Withdrawn 2026-10-29 (not
  needed after D-062).
- Assumption (D-062): the free-tier Gemini key is used only on
  hand-selected test records. A wrong filter could send real prospect
  data to the free tier; accepted as an MVP risk, to be avoided by care
  during testing.
- ⚠ Go-live check: switch to the paid Gemini key and review the AI
  provider's data-use terms (D-062), and
  confirm Microsoft Graph access is limited to the BD mailbox group
  (D-057).

- Q-COMP-03 (Parked) — BD checking Apollo.io's terms as part of an
  in-progress renewal; will provide a knowledge-transfer (KT) on Apollo.io.
  Re-checked 2026-10-28: no update, remains Parked.
- Q-REPORT-02 (Parked) — BD confirming current Apollo.io subscription cost
  with Finance/Procurement.
  Re-checked 2026-10-28: no update, remains Parked.
- Q-CONTENT-04 (Parked) — BD/leadership confirming which case studies are
  approved for use in outreach (none approved yet; hard guardrail against
  fabricated case studies stays in force meanwhile).
- Q-CONTENT-06 (Parked) — BD to provide actual example outreach emails and
  brand tone guidelines (materials not yet delivered).
- ⚠ Q-SEND-01 flag: BD's requested 800–1,000 emails/day/mailbox needs
  technical validation in Phase 2 against real Microsoft 365 limits and
  deliverability best practice — see note under Q-SEND-01 and D-029.

- Q-COMP-05 (Open, added 2026-10-31) — final email footer wording.
  Required before any real (non-test) email is sent (D-081).
- Q-COMP-06 (Open, added 2026-10-31) — Alphaleo's postal address for the
  footer. Required before any real (non-test) email is sent (D-081).
- Q-CONTENT-14 (Open for the BD team, added 2026-11-04) — first-email
  length: keep 80–120 words or adjust (first test drafts were 59–74).
  Until BD answers, the structure stays at 80–120 and shorter drafts show
  a warning only.
- ⚠ D-029 vs D-082: the "full campaign in one week" target can't be met
  with the default sequence (last follow-up about 9 calendar days after
  the first email). Flagged for BD; no decision changed.
- Later-phase items (2026-10-31): web unsubscribe page once publicly
  hosted (D-079); the mail-client "unsubscribe" link at the top of
  emails, not settable with the current Microsoft Graph sending method.
- Assumption (D-083): mailbox limits start at 30/day and 8/hour and are
  raised gradually by the admin as sending reputation builds.
- ⚠ Go-live check (D-100, added 2026-11-02): agree a retention period
  for stored reply text and other personal data before go-live.
- Assumption (2026-11-02, M3): leads marked "Qualified" or "Handed Off to
  Sales" (D-022, D-101) are excluded from new campaigns, like replied
  leads, because they are already in a sales conversation. Their
  sequences already stop (D-082).
- Assumption (2026-11-02, M3): in lead search, a person counts as opted
  out if any of their addresses is opted out (D-066 is per address). The
  send-time check stays per address.

---

## Change Log

- 2026-10-21: Initial Round 1 requirements discovery drafted across 12
  themes (DATA, LEADS, OWNERSHIP, PERSONALIZATION, SENDING, REPLY, NOTIFY,
  ROLES, RULES, COMPLIANCE, REPORT, CHANNEL). 16 decisions logged
  (D-001–D-016) from BD discussion rounds.
- 2026-10-22: 4 more decisions logged (D-017–D-020): notification channel,
  failed-send retry policy, bulk/auto-send permission model, contact
  frequency limit default. Held an Email Content Strategy discussion
  (reply/spam drivers, structure, personalization mapping, segment angles,
  follow-up cadence, tone guardrails); added new CONTENT theme (section 13)
  with 6 questions assigned to the BD team covering Alphaleo's offerings,
  target segment, target industries, case studies/proof points,
  differentiator, and brand voice. Consolidated three previously separate
  files (`round-1-questions.md`, the earlier chronological `Q-A.md`, and
  `QA.md`) into this single tracked file per the new cross-project Q&A
  tracking convention; those files are now superseded.
- 2026-10-22: 3 more decisions logged (D-021–D-023): manager edit rights
  (view only), post-reply in-app qualified/hand-off status tag, and
  reporting scope (reps see own activity, managers see all). Q-SEND-01
  (per-mailbox daily send cap) moved to Parked, awaiting BD team input
  alongside the CONTENT-theme questions.
- 2026-10-23 – BD questionnaire generated (Round 1): BD-Questionnaire-2026-10-23-R1.docx.
  Sent IDs: Q-DATA-01, Q-DATA-02, Q-DATA-03, Q-DATA-04, Q-DATA-05, Q-DATA-06,
  Q-LEADS-01, Q-LEADS-02, Q-LEADS-03, Q-LEADS-04, Q-OWN-01, Q-OWN-02, Q-OWN-03,
  Q-PERS-01, Q-SEND-01, Q-SEND-02, Q-SEND-02b, Q-SEND-03, Q-SEND-04, Q-SEND-05,
  Q-REPLY-01, Q-REPLY-02, Q-REPLY-03, Q-REPLY-04, Q-NOTIFY-01, Q-NOTIFY-02,
  Q-NOTIFY-03, Q-ROLES-01, Q-ROLES-02, Q-ROLES-03, Q-RULES-01, Q-RULES-02,
  Q-RULES-03, Q-COMP-01, Q-COMP-02, Q-COMP-03, Q-REPORT-01, Q-REPORT-02,
  Q-CHAN-01, Q-CONTENT-01, Q-CONTENT-02, Q-CONTENT-03, Q-CONTENT-04,
  Q-CONTENT-05, Q-CONTENT-06.
- 2026-10-27: Imported BD team's completed answers from
  `BD-Ans-2026-10-23-R1.docx`. 23 previously-answered questions reconfirmed
  by BD (some with added nuance — see individual entries). 15 new
  decisions logged (D-024–D-038) for questions that moved from Open/Parked
  to Answered. 6 questions moved to Parked pending further BD/leadership
  input or materials: Q-DATA-01 (export field list — pending a referenced
  file not yet received), Q-COMP-02, Q-COMP-03, Q-REPORT-02, Q-CONTENT-04,
  Q-CONTENT-06. Q-RULES-03 flagged as needing a re-ask — BD's submitted
  answer was a mismatched duplicate of Q-RULES-02's answer. Q-SEND-01
  answered with a specific volume target (800–1,000 emails/day/mailbox)
  that is flagged for mandatory technical validation in Phase 2 due to
  deliverability risk. Status counts moved from 22 Open/22 Answered/1
  Parked to 1 Open/38 Answered/6 Parked (45 total).
- 2026-10-28: Q-RULES-03 resolved directly with the user (D-039) — no
  existing customer suppression list exists, will be built from scratch.
  User provided the real Apollo export field list (resolving Q-DATA-01).
  Added new "14. Data Import & Validation" (IMPORT) theme with 10 new
  questions (Q-IMPORT-01 through Q-IMPORT-10) covering field mapping,
  mandatory-field checks, failure handling, cross-source conflict
  resolution, and Apollo-specific metadata handling — all answered in the
  same session, logging 11 new decisions (D-040–D-050). Q-COMP-02 also
  resolved (D-051) — no unsubscribe footer/process exists yet, one needs
  to be created. Status counts moved from 1 Open/38 Answered/6 Parked (45
  total) to 0 Open/51 Answered/4 Parked (55 total, 10 new questions added).
- 2026-10-28: Q-COMP-03 and Q-REPORT-02 re-checked with the user — no
  update on Apollo.io terms or current cost figure; both kept Parked
  (follow-up notes added). Status counts unchanged (0 Open/51 Answered/
  4 Parked, 55 total).
- 2026-10-28: Sync check against Prompt-Log.md and session transcripts.
  Corrected header counts (the file held 56 questions — 52 Answered/4
  Parked — not 55). Recorded the paused app-design discussion: new theme
  "15. App Design & Platform (DESIGN)" with Q-DESIGN-01 to 04 (Answered)
  and Q-DESIGN-05 (Open), and decisions D-052 (MVP phased scope), D-053
  (structured lead store; RAG limited to the knowledge base) and D-054
  (MVP design inputs). Status counts now 1 Open/56 Answered/4 Parked
  (61 total).
- 2026-10-28: App-design thread resumed. Q-DESIGN-05 answered (Outlook
  accounts exist; Microsoft Graph setup needed; Gemini API for the MVP),
  logging D-055 (Graph with per-rep sign-in) and D-056 (Gemini as MVP AI
  provider behind a swappable layer). Added Q-DESIGN-06 (M365 admin) and
  Q-DESIGN-07 (Gemini paid vs free tier) as Open. Status counts now 2
  Open/57 Answered/4 Parked (63 total).
- 2026-10-28: Recorded the user's Microsoft 365 and AI-provider
  direction. Q-DESIGN-06 answered (user is the M365 admin) and
  Q-DESIGN-07 answered (free tier with masked test data, paid tier before
  real data). D-055 superseded by D-057 (application permissions limited
  to a BD mailbox group); D-056 refined by D-060 (provider-neutral AI
  layer). New decisions D-057 to D-061 (Graph access, mock sender,
  secrets handling, AI layer, AI data protection). Added Q-DESIGN-08 to
  10 as Open. Status counts now 3 Open/59 Answered/4 Parked (66 total).
- 2026-10-29: User simplified the AI testing approach. Q-DESIGN-07 answer
  superseded (earlier answer kept); D-061 superseded by D-062 (free-tier
  key on hand-selected test records only; no masking or safeguard in the
  MVP; paid key before real data). Q-DESIGN-08, 09, 10 withdrawn as no
  longer needed. Status counts now 0 Open/59 Answered/4 Parked/3
  Withdrawn (66 total).
- 2026-10-29: Added pointer notes to technical decisions D-054 to D-062
  and to theme 15, showing where each is now maintained in App-Design.md
  (TD-xxx), following the rule that Q-A.md holds business decisions only.
  The business part of D-062 stays here. No content removed; status
  counts unchanged.
- 2026-10-29: Analysed the BD team's non-Apollo sample file. Added
  Q-IMPORT-11 to Q-IMPORT-25 (all Answered) and decisions D-063 to D-078
  covering the lean unified model, opt-outs, quarantine, mandatory fields,
  missing data, email types, engagement rules, ownership, industry
  standardization, matching, and default country. Marked D-039, D-043,
  D-044, D-045, D-047 and D-048 as superseded; added related notes to
  D-001, D-004, D-042 and D-046. Status counts now 0 Open/74 Answered/
  4 Parked/3 Withdrawn (81 total).
- 2026-10-31: Recorded business decisions from the start of App-Design
  Section 2 (backend components). Added Q-DATA-07 (CSV export),
  Q-LEADS-05 (funding-stage filter), Q-SEND-06 (follow-up sequence),
  Q-REPLY-05 (unsubscribe emails outside the thread), Q-RULES-04
  (admin-only limits and defaults), Q-COMP-04 (MVP unsubscribe),
  Q-COMP-07 (real-sending gate), Q-CONTENT-07 to Q-CONTENT-10 (email
  structures, segment guidance, AI guardrails, knowledge-base scope), all
  Answered; and Q-COMP-05 (footer wording) and Q-COMP-06 (postal address)
  as Open. New decisions D-079 to D-089. Added "Related" notes to D-016,
  D-024 and D-029, and an update note to theme 15's context. Nothing
  superseded. Status counts now 2 Open/85 Answered/4 Parked/3 Withdrawn
  (94 total).
- 2026-11-02: Recorded business answers from App-Design Section 2 Parts
  1–3 (components, main flows, data model). Added Q-SEND-07, Q-SEND-08,
  Q-SEND-09, Q-ROLES-04, Q-IMPORT-26, Q-REPLY-06, Q-REPLY-07,
  Q-NOTIFY-04, Q-LEADS-06, Q-COMP-08, Q-COMP-09 and Q-OWN-04 (all
  Answered) and decisions D-090 to D-101 (follow-up drafting, bulk
  approval, possible duplicates, out-of-office replies, unclear replies,
  reply alert recipients, bounces, retry timing, saved-segment sharing,
  GDPR erasure, reply-text storage, Qualified/Handed Off status). Added
  refinement notes to Q-SEND-05, Q-SEND-06, D-018 and D-082 (nothing
  superseded) and a retention go-live check. Status counts now 2 Open/
  97 Answered/4 Parked/3 Withdrawn (106 total).
- 2026-11-02: Recorded Section 2 Part 4 (MVP vs later) answers: added
  Q-REPORT-03 (simple activity page in the MVP) and Q-SEND-10 (MVP done
  when Microsoft 365 sending and reply checking work with test
  recipients), both Answered, with decisions D-102 and D-103. The agreed
  build order is technical and goes to App-Design.md. Status counts now
  2 Open/99 Answered/4 Parked/3 Withdrawn (108 total).
- 2026-11-02: Recorded App-Design Section 3 Part 1 (screen map and core
  lead screens) answers: added Q-ROLES-05 (who can import), Q-REPLY-08
  (replies handled in Outlook) and Q-LEADS-07 (default lead search view),
  all Answered, with decisions D-104 to D-106. Device support is
  technical and goes to App-Design.md. Status counts now 2 Open/102
  Answered/4 Parked/3 Withdrawn (111 total).
- 2026-11-02: Recorded App-Design Section 3 Part 2 (import screens)
  answers, accepted as suggested defaults: added Q-ROLES-06, Q-IMPORT-27,
  Q-IMPORT-28, Q-IMPORT-29 and Q-COMP-10 (all Answered) with decisions
  D-107 to D-111. New working rule (also in project CLAUDE.md): only
  MVP-blocking questions are asked; non-blocking edge cases are recorded
  as "Parked – later phase" with a suggested default. Status counts now
  2 Open/107 Answered/4 Parked/3 Withdrawn (116 total).
- 2026-11-02: M2 (import & quarantine) built. Recorded three non-blocking
  import edge cases as "Parked – later phase" with suggested defaults,
  per the project's question rules: Q-IMPORT-30 (carry the company name
  down in hand-made files), Q-IMPORT-31 (case-only name changes count as
  updates) and Q-IMPORT-32 (the BD "Hospitality" sheet's industry is
  "hospital & health care"). No decisions changed. Status counts now
  2 Open/107 Answered/7 Parked/3 Withdrawn (119 total).
- 2026-11-02: M3 built. Recorded two working assumptions under Open
  Questions & Assumptions: Qualified / Handed Off leads are excluded from
  new campaigns, and a person is shown as opted out if any of their
  addresses is. No decisions changed; status counts unchanged.
- 2026-11-04: User emphasised that BD must be able to customise emails.
  Added Q-CONTENT-11 (Answered) and D-112: reps edit AI-written parts only,
  fixed parts stay intact, edits are re-checked before approval, and admins
  edit structures, voice and segment guidance with restore-defaults.
  Q-CONTENT-12 (per-segment length and call to action) recorded as "Parked –
  later phase" with its default. Status counts now 2 Open/108 Answered/
  8 Parked/3 Withdrawn (121 total).
- 2026-11-04: Added Q-CONTENT-13 (Answered) and D-113: reps can view all
  writing settings read-only, and the review screen shows each lead's
  guidance. Status counts now 2 Open/109 Answered/8 Parked/3 Withdrawn
  (122 total).
- 2026-11-04: Added Q-CONTENT-14 (Open, for the BD team): first-email
  length target, after the first test drafts came out at 59–74 words
  against the 80–120 in D-084. Status counts now 3 Open/109 Answered/
  8 Parked/3 Withdrawn (123 total).
