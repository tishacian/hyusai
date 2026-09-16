# Release 4771d53a — Capture publication continuity

Deployed from `demo/agentic`: `4771d53ae2a057b3e6b0590a7b3b4ce8d9068166`.
Images built on `omnirag-demo`, immutable tag `4771d53ae2a0`.
Rollback tag: `bb467f534d40`. No migration, flag switch or NAWA theme change.

- [Local checks and component captures](../capture-publication-2026-09-17/README.md):
  162 backend tests, 1,493 frontend tests, 8,048 i18n keys, navigation, chrome,
  production build and AOT compilation passed.
- [Three image identities](images.log); worker retains optional Giskard and
  passed `pip check` and its fixture-based SDK qualification. This is not a new
  live Giskard campaign.
- [Storage checks](storage.log), [idle jobs before switch](pre-switch-final.log),
  [healthy services](health.log), [backend SHA](backend-build-info.json) and
  [frontend SHA](frontend-build-info.json) verified. Homepage HTTP 200; zero
  startup exception/traceback matches. The first backend request during startup
  returned 502; the process completed startup without a restart and subsequent
  checks passed.
- [Carakai canaries](canaries.log): 10 passed, 2 intentional local-contract
  skips. Protected runner artifacts:
  `/tmp/iteration-canaries-20260916T231458Z.8L39zo`.

## Real Capture test: correction retained, publication withheld

An isolated text Capture was created through the live APIs in Showcase. Its
original 8 bar statement and amendment to 6 bar are both persisted. The generated
report contains 6 bar and excludes the superseded value. It remains
`pending_review`: no review, publication, or fresh-conversation request was sent.

[Retained result](capture-draft.json): session
`c84ec7f5-3480-43dd-8205-a59d88c459a0`, proposal
`98fd6641-6239-48bc-b405-fb80ba7ab2dc`.

**The content acceptance failed.** The generated report included an unrelated
Knowledge collection inventory. Inspection found that a session without an
explicit context inherited the workspace's most recently updated Context, and
FINAL reformulation admitted `collection_inventory` diagnostics as documentary
context. Neither the report nor its review status was edited to hide this result.

Corrections to source selection and FINAL evidence filtering are developed and
qualified separately; they are not part of this deployed SHA. R2, R0 manual
acceptance and the human baseline remain open. No retained R1 Run was replayed,
replaced or approved by this test.
