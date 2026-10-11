# Generated BRD review contract — candidate release

Candidate: `f6b73cff68da87be6f93e4598326105ea57f1d96`, pushed to
`demo/agentic`. Previous live/rollback: `89f8e09aa82059b45bddf14e3a4f7bc774cf6294`.
No migrations, permission changes or NAWA theme changes.

Local gates: 14 BRD generation service tests and 9 BRD import/API tests pass.
Frontend: 1,467 passed, production build passed (existing warnings),
i18n 7,981 keys, navigation and chrome guards passed.
The chunked script initially counted zero because Node selected a different
reporter; rerunning with NODE_OPTIONS=--test-reporter=tap produced the retained
1,467-test count. Assertions and selected test suite were unchanged.

All three images were built on omnirag-demo from the pushed clean commit,
with the optional Giskard worker SDK preserved (2.19.2, offline checks passed).
Storage gate passed and all six application services switched to the candidate.
Backend became healthy at 49 seconds; revision_verified is true for the exact
SHA, homepage 200, startup exception count zero. The first readiness request
at 11 seconds returned 502 while backend was starting. No migration.

The first carakai invocation ended before tests because sudo's PATH omitted
its installed Node runtime. Retried with /opt/agentium-protected-runner/node-current/bin
in PATH; canaries are running. No successful canary outcome claimed yet.

New production generation job: `1e0d6cd5-312c-4ed8-a67d-86be9aa8f9ab`,
reusing retained document `ffc6102b-e1c6-4c67-8ce2-38885bdba6f5`.
The previous proposal remains unchanged and unapplied.

## Completed deployment and reviewed draft

Canaries: 10 passed, 2 intentional local-fixture skips, 2.0 minutes. Artifacts:
`/tmp/iteration-canaries-20260916T165941Z.Gvr3ui` on carakai.
Generation completed on its first provider attempt. Proposal
`86658a91-fc74-4226-8429-a3ec3fe1854e` includes six cases, including separate
approval and rejection assertions on the actual HITL decision_status. Both
review cases now ask concrete business questions. The Flow retains two
read-only tools, native planner, synthesis and explicit review.

Reviewed and applied via the canonical API to new draft System
`ea63cf3a-3c42-47ba-a923-abcd0cb811ba`. No Flow was assembled manually, no
existing System changed, no application published. Six requirements remain
explicitly uncovered because their mappings have no cases; they are not
claimed validated. Golden Runs and human acceptance remain to execute.

## First canonical Golden batch (in progress)

Batch `8498846c-832c-4d8f-8ad1-c31b754a2757`, six Runs, suite
`984d3c08-0340-4ffd-b90d-ef0ab6802116`, draft revision 2. Each Run retains
the proposal digest and suite assertions. First two Runs reached HITL:
- `9ba95dea-544f-4d41-b6b6-965eb2006412`: notices tool, 700 bar continuous
  and 735 bar relief clearly distinguished, source document/chunk cited.
- `c9389385-5a63-45fb-a7cd-d226489af2fb`: history tool, NF-04 30 planned
  and 55 actual minutes, history source cited.

Their test verdicts remain pending; no reviewer decision was submitted.
The other four cases are not yet qualified. The API schedules this batch
through sequential FastAPI BackgroundTasks calling schedule_run; this is
not evidence of durable worker dispatch or restart recovery.

## Qualification finding: canonical approval status

During runtime review, the approval oracle introduced by f6b73cff was found
incorrect: DAG resume copies Decision.status, which is `accepted` (or later
`applied`), whereas `approved` is a boolean output. The generated suite's
`decision_status == approved` assertion cannot pass a normal approval.
No live decision was submitted to make it pass; the retained suite and Runs
remain unchanged. The generation guard and prompt are corrected locally to
require `accepted` and `rejected`, with an explicit regression rejecting the
old `approved` value. Generation plus canonical HITL authorization tests:
38 passed. This correction is not deployed yet.

The absence case reached the actual hitl_review_1 node, reporting equipment
and cause as not supplied, with the history document cited. This confirms
this execution, not five-repeat reliability.
