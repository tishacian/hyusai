# Release fd9238fa — Capture source selection

Deployed from `demo/agentic`: `fd9238fa6e4aab29f0414cc0f1d2eca835d0b604`.
Three images built on `omnirag-demo`, immutable tag `fd9238fa6e4a`.
Rollback: `4771d53ae2a0`. No migration, activation change or NAWA theme change.

[Local gates](local-checks.log): 165 backend tests, 1,493 frontend tests,
8,048 translation keys, navigation/chrome checks and production build pass.
[Image identities](images.log), [idle consumers](pre-switch-final.log),
[storage/startup](storage-worker-startup.log), [service health](health.log),
[backend identity](backend-build-info.json), [frontend identity](frontend-build-info.json)
and [homepage 200](home-http.log) are retained. The first check at 17 seconds
returned 502 while the backend was starting; at 55 seconds it was healthy with
the expected public SHA. No restart was issued.

[Carakai](canaries.log): **10 passed, 2 intentional local-contract skips**;
artifacts `/tmp/iteration-canaries-20260916T233432Z.iAprM2`.
[Worker SDK check](worker-sdk.json) uses Giskard 2.19.2 with fixture models;
it is not a live provider campaign.

## Real text Capture: correction and publication pass

The same text input as the retained [4771d53a failure](../release-4771d53a-2026-09-17/capture-draft.json)
was entered in a new Showcase session. No historical report was rewritten.
[Draft evidence](capture-draft.json): session `fc22df85-3c24-48cf-831e-7193d4ad754b`,
proposal `c72a0f11-8770-430d-8346-a7c0b083b36d`.

- No unrelated Context is inherited. The original 8 bar statement and its
  amendment remain recorded; the generated report says 6 bar.
- The report preserves the synthetic nature and prohibition on real intervention.
  No Knowledge inventory appears as documentary content.
- Three suggested follow-up questions remain open. This proves factual correction,
  not the usefulness of every generated question.
- An explicitly labelled **automated technical review** accepted this synthetic
  fixture. It is not human acceptance. Publication used the separate collection
  `qa-capture-fd92`; unresolved questions were explicitly excluded from the indexed
  artifact and retained in the proposal.
- [Publication evidence](capture-publication.json): document
  `8b2756be-df4c-5984-96d0-e171baddd5f6`, one indexed chunk. Reloaded proposal returns
  `published`; authenticated rich preview and direct search expose the corrected
  passage in that collection.

## Fresh conversation: failed, retained for the next correction

[Actual result](capture-conversation-failure.json), Run
`77e592fb-6ad8-46c2-9778-2dd1eaac2e02`, answers that the information is unavailable.
The Context selected `qa-capture-fd92` with `context_mode=replace`, but retrieval
searched Showcase notices and expert fiches instead. Workspace chat defaults
supply a Knowledge Scope; the retrieval profile ignored replacement whenever
that scope was present. A subsequent code correction must be deployed and checked
against the same published document. No answer or Run is overwritten.

R2 is **not complete**: the fresh conversation failed; UI handoff, voice correction,
interruption/reconnection, five repetitions and user trials remain unqualified.
Absence before Capture was not queried in this trial. R0 manual acceptance and
human baseline remain open. Retained R1 Runs and decisions were not modified.
