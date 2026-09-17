# 37056391 — missing-source diagnosis and real source qualification

Deployed pushed `demo/agentic` SHA
`37056391d6cc315c72495f973fb6fe0e2072ed68`, tag `37056391d6cc`.
17 September 2026 Europe/Paris (16 September UTC).

## Release

- [Local implementation gates and component captures](https://bitbucket.org/datategy-root/omnirag/src/b6601f5e34fc87fdcdf66d3c4b204afae7cc7bc3/docs/evidence/ingestion-diagnostics-2026-09-16/README.md):
  75 backend tests, 1,487 frontend tests, 8,048 FR/EN keys, navigation/chrome checks
  and production build passed before integration.
- Three [immutable images](images.log) built on omnirag-demo;
  [build completion](image-build.log), [worker dependency/offline SDK checks](worker-gates.log).
  The offline Giskard check does not prove a provider-backed campaign.
- [Storage checks](storage.log) before and after the switch. No migration.
  Preflight: zero active/queued recipes, WorkerJobs or WorkspaceJobs; both Celery
  consumers reported no active tasks. Infrastructure and retained historical Runs
  were unchanged. No image cleanup ran concurrently with this build.
- [Backend](backend-build-info.json) and [frontend](frontend-build-info.json)
  serve the exact SHA. [Healthy application services](health.log), homepage 200,
  zero backend startup exception matches [before intentional failure QA](health-before-qa.log).
  Initial 502 probes resolved during startup, without restarting again.
- [Carakai canaries](canaries.log): **10 passed, 2 intentional local-contract skips**,
  2.1 minutes; `/tmp/iteration-canaries-20260916T221358Z.YD4yNR`.
  The Studio canary releases its own synthetic application. No BRD-generated
  application publication or human approval is claimed.
- Rollback image tag: **`c399f2bec1ca`**, preserving subsequent writes.
  Full VM logs: `/srv/agentium-data/roadmap-deployments/2026-09-17-37056391d6cc/`.

## Recovery: verified on a real worker

Collection `qa-ingest-retry-37056391`, ID `5279884b-e2de-4a60-8701-8764e9e69ca8`.
Retained job `10e5e7b0-2da6-4d2c-bcbb-90c03375b0d0`:

1. A deliberately absent synthetic original fails at `copy_originals` with
   persisted `original_source_missing` and its exact filename.
2. The same original is restored; the existing explicit retry endpoint dispatches
   a new real Celery attempt on the same job.
3. The job completes and indexes one chunk. Search returns `R2-DIAG-3705`.
4. The current failure diagnosis clears; its original error and structured cause
   remain in the single previous-attempt record.
5. Replaying the same request returns the same task and one history entry.

[Complete API evidence](ingestion-recovery.json),
[preparation/restoration helper](prepare-recovery.py),
[API qualification helper](qualify-recovery.py).
This is technical QA, not a human review or a voice publication.

## PDF / Excel: partial qualification, Excel defect found

One upload into `qa-document-locators-37056391` produces real job
`5fe4e00b-79d7-467a-82ba-ec42da735513`; it completes without inline fallback.
The PDF is the repository's explicitly synthetic invoice fixture. The workbook
is the pre-existing technical row-830 locator fixture, not another NorthForge
business dataset. No customer collection was changed.

[Retained responses](document-locators.json), [original checks](source-checks.json),
[qualification helper](qualify-document-locators.py), [initial failure](document-locators.log).

- Native PDF: rank-1 result includes INV-8834 and 9,860.00 QAR with page 1;
  rich preview resolves the PDF and downloaded original matches uploaded SHA-256.
  **This is not OCR.**
- Excel: rank-1 result correctly contains `N830=NF-04 | O830=55`; its actual
  citation is `A830:O831`. The original checksum matches; a missing worksheet
  correctly returns 404.
- **Failed:** the deployed preview displays only A:L, all blank for that range,
  and reports `selection_truncated=true`. The check fails before asserting the
  values. The successful narrow N:O local fixture had not covered the row chunk's
  wider citation. We did not substitute the rank-2 cell citation to pass the test.
- A bounded shared-preview correction is under qualification for the next
  candidate. This report retains the failed deployed response unchanged. Recheck
  the same original, retrieval hit and job after that release; do not upload again.

## Still open

Current authenticated manual R0 smoke, screenshots/video, 0/5 business and 0/5
developer baseline sessions, and the release owner's closure decision remain open.
The inspected user browser is at sign-in. OCR, the Excel correction's live recheck,
Capture voice/text reuse, interruption and the full R1/R2 criteria are not complete.
No NAWA theme or adoption-default change. **R0 and R1 are not closed.**
