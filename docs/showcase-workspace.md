# Agentium Showcase Workspace

The showcase workspace turns the shipped Agentium features into a coherent
demo tenant. It is synthetic, idempotent, and reconciled append-only.

## Seed Command

Run from the backend directory:

```bash
python -m scripts.seed_showcase_workspace \
  --owner-email "${AGENTIUM_EMAIL:?AGENTIUM_EMAIL is required}"
```

`AGENTIUM_EMAIL` must identify the existing operator account that should own
the workspace. The command fails closed when no owner is supplied.

Useful options:

```bash
python -m scripts.seed_showcase_workspace \
  --workspace-slug agentium-showcase \
  --workspace-name "Agentium Showcase" \
  --owner-email "${AGENTIUM_EMAIL:?AGENTIUM_EMAIL is required}"
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
PASS translation observability
PASS document search
PASS notices knowledge guide
PASS notices document search
Results: 13 passed / 0 failed
```

The last two lines cover the universal-search showcase: the published
`NorthForge Notices - Knowledge Guide` is present for the
`agentium-showcase-notices` collection, and a document search over that
collection returns grounded results.

## Seeded Workspace

- Slug: `agentium-showcase`
- Name: `Agentium Showcase`
- Mode: `portfolio`
- Owner membership: the existing account passed explicitly with
  `--owner-email`

The script writes ten synthetic documents and attempts to ingest them into
the workspace `documents` collection:

- `contract-risk-policy.md`
- `vendor-onboarding-sop.md`
- `sla-enterprise-policy.md`
- `security-review-checklist.md`
- `tender-response-guidelines.md`
- `sharepoint-ingestion-runbook.md`
- `translation-suite-sovereign-runbook.md`
- `translation-suite-dita-guardrails.md`
- `translation-suite-j2450-qa.md`
- `translation-suite-model-routing.md`

### Universal-search corpus (`agentium-showcase-notices`)

The seed also creates a separate, fully synthetic **NorthForge** notices
collection that demonstrates the *universal* chat orchestration baseline (the
same funnel and generic answer policy every workspace now inherits by default —
no "project" concept, no industrial opt-in layer). NorthForge is an invented
OEM; every identifier is fictional and there are no project codes.

- Collection / knowledge scope: `agentium-showcase-notices`
- Assistant profile: `showcase_advisor`
- Knowledge Guide: `NorthForge Notices - Knowledge Guide`
  (`docs/showcase-notices-knowledge-guide.md`), published as an interpretation
  context for the collection.
- Identifiers (catalog references, never projects): `PMP-700`, `BRG-22`,
  `SNS-09`, `VORTEX-5`, `FLT-3`, `GSK-8`, `LUB-40`.
- Document families: operating manuals, maintenance/service procedures, a spare
  parts catalog, a commissioning checklist, a safety / declaration of
  conformity, and a troubleshooting FAQ.
- Knowledge Capture wiring: an `expert_knowledge_capture` System + capture
  Context bound to the notices collection, with `expert_review_required: true`
  and the `agentium-showcase-expert-fiche` destination collection.

A synthetic retrieval golden batch
(`backend/app/resources/retrieval_golden/showcase_notices.json`) exercises the
neutral `precise_fact` / `summary` / `comparison` answer profiles plus a
diversity case over this collection. It is loaded explicitly (the default
golden batch stays Andritz) and validated offline by
`backend/app/tests/services/test_showcase_notices_golden_batch.py`.

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
- `Translation Suite`

What to show:

- Each system has a business objective and active status.
- Compliance uses a HITL flow.
- Tender response uses a debug-friendly decision flow.
- Translation Suite uses a DITA/F1/F2/J2450/CDT delivery DAG.
- Systems have associated runs and versions.

### Business User / Operator

Open `/chat` or `/runs`.

What to show:

- Ask about the enterprise SLA or contract risk.
- Open seeded runs with skill invocations and outcomes.
- Show replay lineage and canonical-answer runs.
- Open Translation Suite runs to inspect tool-call input, output, trace, agent identity and replay overrides.

### Quality Owner / Optimizer

Open `/observability` and `/steering/review-queue`.

What to show:

- Component health has RAG components populated.
- Review queue contains proposed, applied, and feedback-backed items.
- Active suggestions can be applied to create replays.
- Canonical answers demonstrate deterministic remediation.
- Translation Suite jobs appear in workspace observability with batch, guardrail, replay and delivery stages.

### Admin / Compliance

Open `/governance/audit`, `/presets/evaluation`, and `/connectors/sharepoint`.

What to show:

- Evaluation preset is enabled by default.
- Audit trail includes showcase seed, replay, canonical answer, proactive recommendation, Translation Suite, and SharePoint sync events.
- SharePoint sync history is simulated with a completed job.

### Universal Search / Knowledge Consumer

Open `/chat` with the `showcase_advisor` profile on the
`agentium-showcase-notices` scope.

What to show:

- The chat System is the **universal default** template (`chat_transverse_v1`):
  the same hybrid dense+sparse + C-HAH + MMR funnel, candidate headroom and
  optional Deep Search that Andritz proved — now the baseline for every
  workspace, with NO project concept.
- The generic answer policy resolves `precise_fact`, `summary`, `comparison`
  and `insufficient_context` profiles (no `project_summary` /
  `transversal_inventory` / `equipment_detail`).
- Ask a precise-fact question (e.g. "At what pressure does the PMP-700 relief
  valve open?") and show the answer cites the product/part identifier, the
  document name and the section.
- Ask a broad question (e.g. just "sensor") and show the guide-driven
  clarification (proximity / pressure / temperature `SNS-09`).
- Ask a comparison (e.g. operating manual vs safety declaration pressure
  limits) and show evidence drawn from two distinct notices.
- Contrast with Andritz: the same orchestration, but Andritz opts into the
  `industrial` family layer (project codes, cross-project rejection,
  `require_project_code_match`) which the showcase deliberately omits.

### Knowledge Capture / Expert

Open `/knowledge` (Knowledge Capture) on the showcase workspace.

What to show:

- A capture plan/System (`expert_knowledge_capture`) bound to the
  `agentium-showcase-notices` collection as documentary context.
- Run a short capture session; the elicited knowledge becomes a *proposal*.
- Because `expert_review_required: true`, the proposal goes through HITL review
  before it is published to the `agentium-showcase-expert-fiche` collection.
- Show that the published fiche then becomes retrievable interpretation context
  for the Universal Search persona above — closing the capture → curate →
  consume loop without any client data.

## Seeded Functional Data

The script creates:

- 5 showcase capabilities.
- 5 showcase systems.
- 14 runs, including replay, canonical-answer and Translation Suite run types.
- 12 evaluation scores with question types, failed RAG components and translation quality gates.
- Review decisions with active suggestions.
- Evaluation feedback rows.
- Canonical answers with `hit_count`.
- E5 proactive recommendations via the real recommendation service.
- Translation Suite workspace jobs, skill invocations, replay lineage and ACCEPT_4D delivery evidence.
- SharePoint sync job history.
- The synthetic `agentium-showcase-notices` collection (NorthForge notices), its published Knowledge Guide, a `showcase_advisor` profile + knowledge scope, and the Knowledge Capture System/Context with the `agentium-showcase-expert-fiche` destination.
- Audit events via `emit_audit_event`.

## Repeat-run safety

The seed exposes no reset option. Repeated runs reconcile current configuration
through append-only `SystemVersion` transitions and preserve Runs, Decisions,
audits and prior versions. Rebuilding a workspace destructively is deliberately
outside this operational command.

The script also uses unique showcase capability slugs:

- `video_contract_risk`
- `showcase_tender_response`
- `showcase_compliance_loop`
- `showcase_translation_suite`
- `showcase_hana_maintenance`

## VM Validation Snapshot

On the VM after an idempotent reconciliation:

```text
Showcase workspace ready: slug=agentium-showcase systems=5 runs=14 evals=12
smoke_showcase_workspace.py: 13 passed / 0 failed
Playwright E2E: 7 passed
```

This append-only guarantee applies to the authoritative Agentium workspace seed
above. The separately operated video fixture refresh and external SAP HANA demo
dataset are disposable demo-data tools; they cannot produce or promote Lot 8
runtime evidence.
