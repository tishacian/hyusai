# BRD → System roadmap — implementation evidence

Base: `origin/demo/agentic` at `9494149ad1ade0dc9da713588590d1ec01a9d2da`.
Implementation branch: `codex/brd-system-roadmap`.
Scope: [accepted roadmap](../agentium-delivery-roadmap.md).

## Implemented in this change

- Studio: selected page and warning pill use the primary foreground on their
  existing semantic backgrounds. Layout, branding and native NAWA styles are unchanged.
- BRD import: reads at most 5 MiB plus one byte; rejects DOCX archives above
  50 MiB expanded or 1,000 parts before Word parsing. Returns the exact upload's
  SHA-256 and size. Reports duplicated references, missing descriptions,
  generated references, and truncated rows/text instead of silently implying a
  complete extraction. The existing import route and authoring permission remain.
- NorthForge Operational Analysis: calculates and checks the largest overrun,
  `NF-04`, `25` minutes, alongside the existing 120/155/+35/three-late reference.
  The output schema and English/French reference copy include it. Existing
  published versions are not rewritten by this source change.

## Initial local verification — 2026-09-16

| Check | Result |
|---|---|
| BRD parser, import API, Operational Analysis | 17 passed; 1 skipped (template DOCX absent in worktree) |
| Frontend unit suite | 1,459 passed, 0 failed, 0 skipped; all 157 files |
| `check:i18n` | Passed, 7,946 keys |
| `check:nav-links --fail-closed` | Passed |
| `check:ui-chrome` | Passed |
| Production frontend build | Passed; existing budget/CommonJS warnings |
| Studio foreground/background rendering | Local Chromium component fixture inspected in light and dark; not a live Studio canary |

The first monolithic unit invocation exhausted local temporary disk space.
The full suite was rerun in groups of eight files using the existing
`FLOW_UNIT_FILTER`; all groups passed. No test or assertion was removed.
Polars 1.31.0 was installed into a temporary test dependency directory, not a
production environment.

## Release and remaining work (initial tranche; see qualification below)

The initial tranche had not yet been deployed; live qualification is recorded below.

At the initial read-only baseline, Showcase had no Operational Analysis System.
The scoped installation and subsequent qualification below supersede that
inventory. The adoption baseline and independent CI attestation remain open.

R1 is not implemented: returning a document fingerprint does not persist the
file, create a System, or provide requirement-to-Run traceability. Server-owned
proposals, reviewed/idempotent application, the two reference flows, tests,
publication and the authoring UI remain to build.

R2, R3, R5 and R6 remain open. R4 has only the additional numerical reference
above; its application lifecycle, HITL, comparative execution and external-effect
guarantees are not qualified by this change. Existing observability work retains
its separate qualification status.

No default adoption flag switch, customer activation, native NAWA change,
database migration, or replacement of a published System is included.

## R0 live qualification — 16 September 2026

The targeted installer published **Operational Analysis** in the structural
`agentium-showcase` workspace only. Reapplying it preserves the same System,
Experience and published Flow version; it does not reseed the workspace.

- System: `15b05919-c93b-4648-8581-8a41cbe2fae6`.
- Experience: `f286295a-ebef-44d2-a4a3-d0dbf04c866f`.
- Flow version: `e997f4e4-3b51-4eef-9481-389f3a9afae4`.
- Work entry: `/work/operational-analysis`.
- Binding: `showcase.operational.analyze`; published manual ingress `src`.

`480864e5c789fe5079cdfd5de3631f89188e53f8` and then
`e09bde5c3072f406f8f47a8f41be93f2b6bc8323` were built on omnirag-demo from
pushed demo/agentic commits. Public build-info confirmed each exact revision.
No database migration was executed (existing head: `105_evaluation_corrections`).

Five sequential executions passed on each SHA, using the same published Flow:
exact 4 orders, 120 planned minutes, 155 actual minutes, +35 net minutes,
3 late orders, NF-04 +25 minutes; two successful Python recipe invocations,
one LLM invocation, numerical check true, human validation false, and no
duplicate Run on replay of the same idempotency key. The model used the existing
OpenAI deployment default. These checks do not evaluate the prose semantically.
Evidence: [480864e5](../evidence/roadmap-r0-2026-09-16/sequential-480864e5.json),
[e09bde5c](../evidence/roadmap-r0-2026-09-16/sequential-e09bde5c.json).

Manual Chrome check on e09bde5c: Work displayed 4 / 35 / 3 and the generated
explanation. “Inspect this result” opened exactly
`852223ad-f518-4972-ba4e-36791588641e`; the timeline exposed the two Python
operations and the effective OpenAI model. Application labels were English;
the model's response was French, following the configured answer behaviour.
Language of generated answers is therefore not qualified as following the UI.

### Blocking findings retained, not converted into successful tests

1. **Worker starvation under concurrency.** Two parent Runs occupied both CPU
   worker slots while awaiting recipes submitted to that same queue. A recipe
   hit its waiting deadline. The two remaining synthetic recipe tasks were
   cancelled explicitly via their canonical API to free the worker. No customer
   task was cancelled. [Persisted failed evidence](../evidence/roadmap-r0-2026-09-16/concurrent-run-failure.json).
   A dedicated executor queue/consumer or durable nonblocking orchestration
   must be designed and qualified with its deployment/storage/rollback gates;
   increasing concurrency alone does not remove the deadlock.
2. **Completion is not validation.** The failed check's Run still settled as
   `completed` with output `_status: failed`. Its absent numerical check was
   correctly rejected by the qualification script. Run summaries also show
   `approved` and `100%` from the legacy outcome while no human decision occurred.
   The DAG intentionally passes failed task data to downstream decision nodes
   (`run_engine/dag.py`, `_task`). The fix must preserve explicit recovery
   branches while preventing an unhandled failed required check from being
   presented as a validated result. It must not blindly fail every recovered Run.
3. **Automatic evaluation skipped.** This fixed-input Flow retains no query
   extractable by the current auto-evaluator. The investigation view honestly
   shows skipped/unavailable and no examined claims. Numerical checking is
   real; Giskard/native semantic evaluation is not established by this exercise.

The initial canaries returned 8 passed, 2 failed, 2 intentional local-fixture
skips. They exposed a wrong Work workspace selection, publication focus return,
then missing Work main landmark and adoption titlebar overflow on mobile.
The first two corrections shipped in e09bde5c; the latter two are in cf90acb0.
No canary assertion was weakened.

Local validation for the expanded tranche: 66 backend tests passed and one
DOCX-template test skipped; all 1,460 frontend tests exercised in batches
(1,459 initially passed, the wording failure corrected and its 16-test group
rerun successfully). Follow-ups: 64 Studio tests, then 17 titlebar/Work tests
passed. Production builds passed. i18n passes with 7,947 keys; navigation and
UI chrome guards pass. Independent GitLab CI attestation remains unavailable.

**R0 remains open.** Successful sequential arithmetic does not close concurrent
execution, honest outcome rendering, semantic evaluation or user-adoption
acceptance. Human trials and the unprepared case are NOT RUN. R1–R6 are not
implemented by this release.


### Final frontend qualification follow-up

Runtime cf90acb0 passed the main-landmark and mobile-width checks. Its five
sequential executions passed in 27–32 seconds:
[exact Run evidence](../evidence/roadmap-r0-2026-09-16/sequential-cf90acb0.json).
The API and frontend build-info both matched; root returned HTTP 200 and the
backend/frontend were healthy with no startup exception detected.

Its unchanged full canary suite was still 8 passed / 2 failed / 2 skipped:
Work expected the old “My applications” heading; Studio expected initial focus
on Close although the composer intentionally focused its textbox. Test-only
commit d38a67f0 updates the heading and verifies composer focus, a Tab remaining
inside the dialog, Escape, inert removal and return focus. A separate reviewed
worktree ran these tests against cf90acb0; it did not substitute a source marker
or claim a full signed iteration pass.

That focused run exposed two genuine next failures: Work live badge contrast
in all six light-theme cases, and publication success focus attempted before
render. Commit 196164eb fixes the badge foreground and uses afterNextRender for
new publication/deployment feedback targets. It also persists the visual matrix
PNGs to the test output directory. 76 targeted tests, all three frontend guards
and the production build passed before integration on demo/agentic.


### Delivered runtime and final verdict

**Live: 196164eb5b8098dca49cf54a7c06c4df05cc8b79.** Five sequential
Runs passed in 23–31 seconds, with the same Flow version and no duplicate on
idempotent replay. [Evidence and actual screenshots](../evidence/roadmap-r0-2026-09-16/README.md).

The full source-matched iteration returned **9 passed, 1 failed, 2 intentional
skips**. The sole remaining failure was Studio cleanup: the test incorrectly
expected deletion after immutable release creation. The API correctly returned
409 EXPERIENCE_RELEASED. Test-only commit **bd160451** checks that exact refusal
and explicitly retains the synthetic released Experience and binding.
The focused Studio rerun passed against the unchanged live 196164eb runtime.
Do not describe this as one all-green source-matched full-suite run: it is nine
passing canaries plus the separately reviewed and passing Studio follow-up.

Work and Studio each passed their 12-state FR/EN, light/dark, desktop/456/320px
accessibility matrix. Captures are retained. Manual language switching on the
live app confirmed translated controls and numerical reference copy, then EN
was restored. The authored application name/description remain English metadata;
the LLM response language is still not tied to the UI preference.

No new application build is needed for the test-only retention correction or
this evidence update; neither changes deployed application bytes. The runtime
SHA remains 196164eb. Existing concurrency, semantic-evaluation and user-study
limitations above remain open; this is a deployment, not R0 acceptance closure.

### R0 follow-up — concurrency and truthful completion (development)

The recipe dispatcher now uses a dedicated `recipes` queue, consumed by
`agentium-worker-recipes` using the same immutable worker image and protected
mounts. Its beat is disabled. The VM launcher starts it alongside the existing
workers; the storage guard validates its mounts, while accepting the previous
container generation during the pre-switch check. Standalone Celery deployments
must start an independent recipes consumer before upgrading producers.

Completed invocations no longer manufacture 100% confidence or an `approved`
decision. Only finite, explicit confidence values in [0, 1] are retained.
Declared per-execution ROI projections retain their existing calculation,
independently of approval. Historical outcomes are not rewritten. An unhandled failure envelope at the
terminal output now fails the Run. Recovered outputs remain completed, keeping
failed attempts in their invocation history. This terminal-envelope check is not
a proof that every business requirement was validated.

Validation: 36 recipe/outcome tests initially passed; after the decision and
terminal-error changes, 128 engine, membrane, provenance and runtime-environment
tests passed. Docker Compose was resolved on carakai without starting services:
separate queues, identical image and mounts, no second beat. All 54 storage
guard tests passed, including the new consumer mount check. Concurrent live
Runs, restart/redelivery and rollback qualification remain NOT RUN for this
change. No production deployment or R0 acceptance closure is claimed.

Final follow-up: 86 engine/membrane/outcome/provenance tests passed after
separating declared ROI projection from approval. The 54 storage tests and
43 runtime-environment tests passed; no frontend files changed in this slice.

### Deployment of the runtime follow-up

**7532d449 is live on demo/agentic.** Both concurrent pairs passed, including a
graceful recipe-worker restart; five sequential Runs and idempotent replays
passed. Iteration canaries: 10 passed, two intentional local-contract skips.
New Runs show no inferred approval or confidence. [Release evidence](../evidence/runtime-7532d449-2026-09-16/README.md).
Abrupt worker loss, real-provider Giskard and human adoption acceptance remain
outside this completed deployment qualification.

### R0 acceptance clarification — 16 September 2026

The owner confirmed that the repository uses Bitbucket and has no active remote
CI pipeline. Earlier references above to missing GitLab attestation are therefore
superseded, not outstanding release blockers. The release contract is the local
gates → immutable VM build → runtime checks → carakai canaries documented in
[the release process](../agentium-release-process.md). Their recorded results
for 7532d449 are available in the runtime evidence.

The [R0 acceptance sheet](agentium-r0-acceptance.md) separates the qualified
technical release from the outstanding human adoption baseline. Giskard provider
qualification and the unprepared observability case retain their own acceptance
scope; this clarification does not mark them passed. R0 is not declared formally
closed and R1's complete BRD-to-System generation is not yet delivered.
