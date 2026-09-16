# Release c399f2be — recover failed source indexing

16 September 2026. Deployed from pushed `demo/agentic`:
`c399f2bec1ca9c984afa00ca7a3400d01a86d4cf`.

## Delivered / livré

Knowledge and the SFTP monitor display persisted indexing status, previous
failures and an explicit retry for authorized administrators. Retrying preserves
the existing job and deposit binding. Stale, superseded, foreign and governed
campaign requests are refused. Inventory failures remain errors, not empty data.
Labels and dates follow FR/EN; shared Cockpit tokens preserve NAWA branding.

Une indexation échouée peut être reprise sans perdre son erreur initiale ni
créer un autre job. Les collections conservent leurs contrôles d’accès et les
campagnes leur parcours de reprise propre.

## Qualification and deployment

- [Local implementation gates and component captures](../ingestion-recovery-2026-09-16/README.md):
  107 backend tests; 1,484 frontend tests in the full run and the final 7-test
  component rerun, covering 1,486 unique tests; i18n 8,045 keys, navigation,
  shared chrome and production build passed. Existing build warnings remain.
  Two additional dependency-constraint tests passed for this candidate.
- [Three immutable images](images.log), built on omnirag-demo with exact revision
  labels. Worker [Giskard 2.19.2 offline qualification](giskard-offline.json) and
  dependency checks pass. Judge calls were mocked; no live Giskard campaign is
  claimed by this release.
- [Actual image dependency comparison](dependency-comparison.json): backend
  retains all 211 packages and versions. Worker retains 250 unchanged versions;
  three old orphan packages (`httpx2`, `httpcore2`, `truststore`) are absent.
  [Previous worker metadata](previous-worker-orphan-packages.log) shows no
  dependent package for `httpx2`; application code has no imports of this group.
  Constraints select versions rather than installing unused packages.
- No migration. Storage checks [before](storage-before.log) and
  [after](storage-after.log) passed. The [switch](deploy.log) recreated six
  application services; infrastructure and retained data were untouched.
  No recipe, ingestion job or workspace job was queued/running at preflight;
  both Celery consumers reported no active tasks. Four historical Runs still
  marked running date from April–July; their records were not rewritten.
- Exact public [backend](public-build-info.json) and
  [frontend](frontend-build-info.json) SHA verified; [homepage 200](home-http.log),
  [healthy services and zero backend startup exception matches](runtime-health.log).
  Three early HTTP probes returned 502 during startup, then succeeded without
  restarting the candidate.
- [Carakai canaries](canaries.log): **10 passed, 2 intentional local-contract
  skips**, 2.1 minutes. Includes Work, Studio, branding isolation, LiveKit config,
  Hypervisor and exact-Run observability links. Runner artifacts:
  `/tmp/iteration-canaries-20260916T214834Z.jYmVjX`.

Build and capacity-maintenance logs remain on the VM at
`/srv/agentium-data/roadmap-deployments/2026-09-16-c399f2bec1ca/`.
The earlier c651 build failed during overlapping dangling-image cleanup and
never switched production. Cleanup finished before this build; tagged rollback
images and all volumes were retained. The three retained previous images were
started successfully before proceeding. Python versions are constrained from
the qualified runtime; base images and OS packages are not frozen by this change.

## Real failure → retry → indexed source → retrieval

The [preparation helper](prepare_ingestion.py) creates one dedicated synthetic
Showcase collection, `qa-ingest-retry-c399f2be`, and dispatches the canonical
worker with an intentionally missing original. No existing client corpus is
changed. The original is then explicitly restored, and the
[protected-runner client](qualify_ingestion.py) calls the public retry API.

The [complete retained evidence](ingestion-recovery.json) proves:

1. Job `62601299-b603-4c6f-ba34-bfc07667cff6` failed at `copy_originals` on
   task `8f4c5cc9-b091-483f-b2a0-c92b3ad751e9`.
2. The explicit API retry kept that job ID and used task
   `29ea594a-9a9c-4565-bdb8-24e26d08929d`, through the real broker/worker.
3. The retry completed in **22.8 seconds**, retaining exactly one prior attempt
   and its original error. The collection became ready with one source/chunk.
4. Scoped search returned the exact synthetic `R2-C399` passage with document
   identity `025a646d-eb42-5fc3-abf4-e5043f1d3fb0` and content SHA-256.
5. Replaying the same retry request returned the same job, task and history;
   it created no second attempt.

This is one technical source-recovery exercise. The source was restored between
attempts; it is not a deterministic replay of identical failed input, a broker
redelivery exercise, or a worker-kill recovery test. The source deliberately
contains no client knowledge. The retained error is currently a raw storage key;
its cause still needs a clearer operator-facing explanation in a later slice.

## Remaining acceptance

The authenticated human browser remains signed out. No current manual
Work/PIH/Quality smoke, live ingestion-screen capture or video is claimed.
Existing component captures use local fixtures. R0 baseline remains
**0/5 business and 0/5 developer sessions**; R0 is not closed.

R1 human review, publication and second-user consumption remain open. Live
OCR/Excel retrieval and the Capture voice → correction → publication → new
conversation path, including five repetitions, remain R2 acceptance work.
The retrieval plan in the saved response is not proof of every enabled stage
having executed. No human decision, BRD-generated application publication or default flag
change was made. The Studio canary created its own technical application release.

Rollback: immutable tag **`6f8f81696db0`** through the documented deployment
script; preserve database writes. Native NAWA theme and adoption defaults are
unchanged.
