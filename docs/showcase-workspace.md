# Agentium Showcase Workspace

The showcase workspace turns the shipped Agentium features into a coherent
demo tenant. It is synthetic, idempotent, and safe to reset.

## Seed Command

Run from the backend directory:

```bash
python -m scripts.seed_showcase_workspace --reset
```

Useful options:

```bash
python -m scripts.seed_showcase_workspace \
  --workspace-slug agentium-showcase \
  --workspace-name "Agentium Showcase" \
  --owner-email thibaud.ishacian@datategy.net \
  --reset
```

`--skip-ingest` skips FAISS/Qdrant document ingestion and still seeds the
rest of the product story.

## Smoke Command

```bash
python -m scripts.smoke_showcase_workspace \
  --backend-url https://agentium.papai.ai \
  --username alice@acme.test \
  --password alice-demo
```

Expected VM result:

```text
PASS login
PASS workspaces
PASS systems
PASS runs
PASS recommendations
PASS component health
PASS review queue
PASS canonical answers
PASS audit
Results: 9 passed / 0 failed
```

## Seeded Workspace

- Slug: `agentium-showcase`
- Name: `Agentium Showcase`
- Mode: `portfolio`
- Owner membership: `thibaud.ishacian@datategy.net` when that user exists

The script writes six synthetic documents and attempts to ingest them into
the workspace `documents` collection:

- `contract-risk-policy.md`
- `vendor-onboarding-sop.md`
- `sla-enterprise-policy.md`
- `security-review-checklist.md`
- `tender-response-guidelines.md`
- `sharepoint-ingestion-runbook.md`

## Demo Personas

### Executive / Portfolio Owner

Start at `/hypervisor`.

What to show:

- Portfolio metrics are non-empty.
- Recommendations panel has proactive E5 decisions.
- Click **SCAN** to regenerate recommendations idempotently.
- Open the decision feed and show proposed/applied states.

### Builder / AI Architect

Open `/systems`.

Seeded systems:

- `Contract Risk Copilot`
- `Compliance Review Loop`
- `Tender Response Analyst`

What to show:

- Each system has a business objective and active status.
- Compliance uses a HITL flow.
- Tender response uses a debug-friendly decision flow.
- Systems have associated runs and versions.

### Business User / Operator

Open `/chat` or `/runs`.

What to show:

- Ask about the enterprise SLA or contract risk.
- Open seeded runs with skill invocations and outcomes.
- Show replay lineage and canonical-answer runs.

### Quality Owner / Optimizer

Open `/observability` and `/steering/review-queue`.

What to show:

- Component health has RAG components populated.
- Review queue contains proposed, applied, and feedback-backed items.
- Active suggestions can be applied to create replays.
- Canonical answers demonstrate deterministic remediation.

### Admin / Compliance

Open `/governance/audit`, `/presets/evaluation`, and `/connectors/sharepoint`.

What to show:

- Evaluation preset is enabled by default.
- Audit trail includes showcase seed, replay, canonical answer, proactive recommendation, and SharePoint sync events.
- SharePoint sync history is simulated with a completed job.

## Seeded Functional Data

The script creates:

- 3 showcase capabilities.
- 3 showcase systems.
- 10 runs, including replay and canonical-answer run types.
- 8 evaluation scores with question types and failed RAG components.
- Review decisions with active suggestions.
- Evaluation feedback rows.
- Canonical answers with `hit_count`.
- E5 proactive recommendations via the real recommendation service.
- SharePoint sync job history.
- Audit events via `emit_audit_event`.

## Reset Safety

`--reset` deletes only the target showcase workspace and rows scoped to it.
It does not touch other workspaces.

The script also uses unique showcase capability slugs:

- `showcase_contract_risk`
- `showcase_tender_response`
- `showcase_compliance_loop`

## VM Validation Snapshot

On the VM after `--reset`:

```text
Showcase workspace ready: slug=agentium-showcase systems=3 runs=10 evals=8
smoke_showcase_workspace.py: 9 passed / 0 failed
Playwright E2E: 7 passed
```
