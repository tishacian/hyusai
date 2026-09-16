# Observed HITL decision — deployed release

Deployed: `89f8e09aa82059b45bddf14e3a4f7bc774cf6294`, pushed on
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

All three immutable images were built on omnirag-demo and the storage gate
passed. The six application services switched to `89f8e09aa820`; backend and
frontend became healthy, public build-info matched the complete candidate SHA
with revision_verified=true, homepage returned 200, and startup exception count
was zero. The initial readiness probe returned 502 while backend health was
starting; the subsequent healthy probe passed. No infrastructure service changed.
Image IDs are retained in vm-switch.log. Carakai canaries: **10 passed, 2 intentional local-contract skips, 2.0 minutes**.
Artifacts on carakai: `/tmp/iteration-canaries-20260916T162826Z.DLuWBE`.
The tests assert the exact deployed SHA. The skipped local adoption/branding
fixtures are not claimed as live acceptance. Chrome inventory still showed
Agentium sign-in pages; no authenticated manual smoke was completed. Manual authenticated smoke and human trials
remain open. The independent NorthForge absence-planning failure is not fixed
by this release; the unsuccessful prompt-order experiment was reverted.
