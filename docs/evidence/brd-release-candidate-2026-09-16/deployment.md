# R1 incremental release — deployment in progress

Candidate: `f63f1eaf7e023e7ea5c428995c44ca0a3ad202ff`, published on `demo/agentic`.
Previous served revision: `7532d4491a239d0e2285303cb12447ceac7419c2`.

- VM build checkout advanced by fetch and fast-forward; clean tree verified.
- Protected storage check passed; data volume had 259 GiB available.
- Paired backup completed at `/srv/agentium-data/brd-system-deployments/2026-09-16-f63f1eaf7e02`; `.ready` verified. PostgreSQL dump 452 MiB, MLflow dump 136 KiB, 264 objects (311 MiB), three evaluation report states retained, none missing.
- Migrations 106 and 107 applied successfully; database reports `107_brd_proposals`.
- Backend image built: `agentium-backend:f63f1eaf7e02`.
- All three immutable images built and switched successfully. Public build-info confirms the full candidate SHA; root HTTP 200, backend/frontend healthy, CPU and recipe workers running. Startup logs contain zero traceback/exception matches. Giskard SDK offline qualification passed in the worker build; real-provider campaign is not established by that check.
- Protected carakai checkout fast-forwarded through a Git bundle to the exact candidate; source marker updated after HEAD verification. Canaries completed: 10 passed, two intentional local-contract skips, in 2.0 minutes. Evidence: `canaries.log`; protected artifacts `/tmp/iteration-canaries-20260916T125457Z.yohlg3` on carakai.

Migration is additive. No database rollback or runtime downgrade is authorized by this record. Once new BRD-origin contracts are written, an older strict contract reader is not a compatible rollback; retain compatible readers or fix forward.

This is release evidence, not R1 acceptance. Full PIH/NorthForge journeys, repeated live tests, second-user consumption and formative user sessions remain open.

## First real PIH authoring exercise

The canonical API retained BRD `184ab6a2-1d41-482d-ae8b-236dbc476f96` and dispatched job `d252042e-f821-4994-90b7-32ddc64dba60` to the deployed worker. Generation completed in approximately 54 seconds, using the configured workspace resolver (effective OpenAI gpt-5, 9,916 reported tokens). Reviewed application of proposal `e6a2ab64-a8eb-4ecd-9319-60a66ee20dba` created draft System `85d7e34e-0f0a-4565-8a93-a8710342536b`; no application was published.

The server suite created batch `512bdb27-9cf9-4a62-991d-07ffe4556295` with three canonical Runs. The first two reached human review, retaining original fact quotes and explicitly missing fields. Human decisions remain pending; server verdicts correctly remain pending. The generated lexical exclusion of `recommend` conflicts with the template's legitimate `no recommendations` heading. This is a test-quality defect, not proof of a prohibited HR recommendation. Existing criteria and outputs are retained unchanged in `pih-live.json`; this batch is not accepted as a passing reference suite.
