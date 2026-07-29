# Showcase Remaining Gaps

This document tracks the real remaining gaps after the Agentium showcase
workspace polish.

## Resolved In Polish

- Governance Audit now parses the backend `{ logs, total }` envelope and
  renders structured `details`.
- Run detail receives `input_ref` and `output_ref` from `GET /runs/:id`.
- Canonical answers have a simple manager at `/governance/canonical-answers`.
- Canonical answers can be deleted through
  `DELETE /evaluation/canonical-answers/{id}`.
- Showcase smoke covers document search.
- `/presets` links clearly to `/presets/evaluation`.
- SharePoint UI detects the seeded `showcase-guest-link` job and can
  prefill the demo key.

## Remaining Gaps

### SharePoint Is Still A Simulated Sync

The showcase seeds a completed `SharePointSyncJob` and audit event, but it
does not seed an encrypted session in the SharePoint session store and does
not run a real SharePoint sync.

Impact: the UI demonstrates sync history and ingest counts, but not a real
connector round trip.

Next step: implement E4.2/E4.3 or add an explicit backend demo mode for
SharePoint jobs.

### Showcase Seed Is Append-Only

`python -m scripts.seed_showcase_workspace --owner-email "${AGENTIUM_EMAIL:?AGENTIUM_EMAIL is required}"`
is the supported path. Repeated execution is idempotent for story facts and
creates a new `SystemVersion` only when effective configuration changes. The
command exposes no reset option and never deletes Runs, Decisions, audits or
historical versions.

### Showcase Capability Slugs Are Global

`Capability.slug` is globally unique in the database. The showcase uses
reserved slugs:

- `video_contract_risk`
- `showcase_tender_response`
- `showcase_compliance_loop`
- `showcase_translation_suite`
- `showcase_hana_maintenance`

Impact: one showcase workspace per environment is safe. Multiple parallel
showcase tenants would collide.

The append-only guarantee in this document concerns
`seed_showcase_workspace.py`. The bounded video fixture refresh and the
external SAP HANA demo-dataset loader remain disposable-data utilities and are
not admissible as Lot 8 evidence.

Next step: either keep one global showcase or migrate capabilities to a
workspace-scoped uniqueness model.

### RAG Grounding Depends On Ingestion Availability

On the VM, the six synthetic documents are ingested into FAISS successfully.
If `--skip-ingest` is used, the Knowledge and document-search parts of the
showcase become weaker, while the rest of the seeded story remains usable.

Impact: run the idempotent seed without `--skip-ingest` for full demos.

Next step: keep document-search in `smoke_showcase_workspace.py` as the
guardrail.

### Canonical Answer Manager Is Minimal

The current page lists and deletes canonical answers. It does not yet
support editing, source drill-down, or promoting feedback directly from the
manager.

Impact: enough for demo and governance visibility, but not a full admin
workflow.

Next step: add edit/update and source links if canonical answers become a
frequent operator workflow.
