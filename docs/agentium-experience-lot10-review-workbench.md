# Agentium Experience Lot 10: Review workbench

**Status:** specification and first implementation, 23 October 2026. The
backend is off behind `review_sets_enabled`. Two certified components are
added to the current catalog, the same way `map_panel` and `decision_queue`
were: `review_workbench` (sets, packages, filtered records, decision screen)
and `review_matrix` (sets on two label axes with deadline, close and export).
A Release that does not place them renders exactly as before.

## Why

Business apps can launch a System, show its result and approve or refuse a
gate. They cannot yet host the work a person does **on each record** a System
produced: read the record with its context, correct it, classify what was
wrong, and do that for thousands of records shared between several people.
Segment-level translation review is the first case; claim checking, label
review and document extraction checks have the same shape.

Today `TableBlock` and `QueueBlock` are read-only, the HITL resolve payload is
`accept | reject + note` for a whole run, and `llm_label_review` only edits
dataset labels. This lot adds the missing generic capabilities instead of a
bespoke Studio.

## Concepts

| Concept | Meaning |
| --- | --- |
| Review set | A batch of records produced by one Run or one runner job, for one workspace, opened for human review. It has a `namespace` (e.g. `translation.segment`), a `group` (e.g. a lot and a language), a deadline and a policy. |
| Review item | One record of the set: an immutable `subject` (what was produced: source, candidate, context, references, machine findings) plus a stable `item_ref`, a `tier` and a `weight` (e.g. word count). |
| Review decision | What a person did on an item: `approve`, `correct` or `reject`, the corrected value when there is one, annotations from the set's taxonomy, a comment and the time spent. Decisions are append-only; the latest one per item counts. |
| Claim | A short lease a reviewer takes on an item while editing it. Others see it as taken; it expires by itself. |
| Taxonomy | The set's closed list of annotation categories, each with allowed severities and the rules that make a comment mandatory. |
| Queue policy | How items are ordered (by tier), packed into work packages under a weight budget, and unlocked (a tier opens when earlier tiers reach a threshold). |

## Capabilities

### C1 Ordered work queue with unlock rules
Items are served by tier, then by `item_ref`. The policy packs consecutive
items of a tier into work packages whose weight stays under a budget
(`package_weight`). A tier can declare `unlock_after: {tiers, threshold}`; its
packages stay locked until the listed tiers are decided at that ratio.
Acceptance: a locked package cannot be claimed through the API, not only hidden.

### C2 Interactive table
Sort, filter by status, tier, annotation category and severity, free-text
search on the subject, server-side pagination, row selection and a bulk
action (`approve` only). Acceptance: filters are applied by the server; a bulk
approve skips claimed items and reports them.

### C3 Record workbench
One item with its context (`subject.context.before/after`, expandable when the
producer publishes more), its references with their similarity scores, the
machine findings, and an editor. The editor keeps inline markup the subject
declares protected (`subject.protected_spans`); a correction that drops or
reorders a protected span is refused with the span named. Right-to-left
scripts render with `dir="rtl"` from `subject.direction`.

### C4 Per-record decision (HITL with an edited value)
`approve` keeps the candidate. `correct` stores the corrected value. `reject`
marks the item unusable without a value. The decision is inferred only when
the client asks for it explicitly (`decision: "auto"`): unchanged means approve.

### C5 Annotation taxonomy
Configured per set, never free text: categories with their severities, an
optional weight per severity, and `comment_required_for` (for example any
`major` severity). The server enforces the rules; the client mirrors them.

### C6 Claims with expiry and optimistic writes
`claim` returns a lease (default 15 minutes, renewed by activity). A decision
must carry the item's `revision`; a stale revision is refused, so a double
submit or a concurrent edit never overwrites silently.

### C7 Time spent
The client reports `duration_ms` with each decision (pauses excluded); the
server keeps it and sums it per package, per reviewer and per set.

### C8 Export
CSV of a set or a filtered view: item ref, tier, subject fields chosen by the
set, decision, corrected value, annotations, comment, reviewer, duration,
decided at. Exports are audited.

### C9 Progress matrix with actions
Sets grouped on two axes (e.g. lot × language) with status, progress, weighted
score and deadline. Actions on a cell are catalogued app actions (extend the
deadline, close the set, remind reviewers) that start a Run or call a review
set operation, each audited.

## Flow integration

- A skill `review_set_open_v1` opens a set from a run output or a runner job
  artifact (CSV or JSON lines) with the namespace, group, taxonomy and policy
  given in the node config.
- When every item is decided, or when an administrator closes the set, the
  platform emits `review_set.completed`. A `source.review_set_completed`
  trigger starts the next System (reinjection, knowledge write-back,
  delivery). Side effects downstream stay behind an `hitl` node, as for every
  event trigger.
- A skill `review_set_read_v1` returns the decisions of a set, for write-back
  into a knowledge collection or a reinjection job.

## Access

Reviewing requires workspace membership and the app entitlement. A set can
restrict its reviewers to members whose attribute matches the set's group
(for example `review_languages` contains the set language). Platform and
workspace administrators can close sets and run exports. No shared accounts.

## Data model (backend)

- `review_sets`: id, workspace_id, namespace, group_key, group_labels, title,
  source (run_id or job_id), taxonomy, policy, deadline_at, status
  (`open | closed`), created_by, created_at, closed_at.
- `review_items`: id, set_id, item_ref, tier, weight, subject (JSON),
  revision, claimed_by, claim_expires_at, latest decision fields
  (status, decided_by, decided_at) for fast filtering.
- `review_decisions`: append-only; id, item_id, revision, decision, value,
  annotations, comment, duration_ms, decided_by, decided_at.

## Out of scope

- Free-form custom components and arbitrary JavaScript (unchanged boundary).
- Editing the subject itself: reviewers decide on the candidate, the producer
  owns the record.
- Real-time co-editing of one item.
