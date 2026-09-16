# Observed HITL decision — release candidate

Candidate: `89f8e09aa82059b45bddf14e3a4f7bc774cf6294`, pushed on
`demo/agentic`. Previous live/rollback: `7951e698cb04c6c4791e7e7d7fd620e253402616`.
No migration or theme change.

Work, Flow and NAWA submit the decision ID the user saw. The API refuses a
mismatch before resolving a decision; the shared frontend refuses to submit
without a decision reference. The Flow terminal records success only after
server acknowledgment. Existing external clients may omit the additive field;
the stale-decision protection is not asserted for those clients.

Local gates:
- 24 HITL API tests passed, including accept/reject mismatch and matching ID.
- 1,467 frontend tests passed, including refusal without a false approval log.
- Production frontend build passed (existing budget/CommonJS warnings).
- i18n: 7,981 keys; navigation and UI chrome guards passed.

VM build is in progress. Switch, immutable image IDs, health, public SHA and
carakai results remain to record. Manual authenticated smoke and human trials
remain open. The independent NorthForge absence-planning failure is not fixed
by this release; the unsuccessful prompt-order experiment was reverted.
