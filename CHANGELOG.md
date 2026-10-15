# Changelog

## 2026-10-15 · Execution observability candidate (not deployed)

- Add a transactional activity journal, authenticated replayable SSE and
  System/workspace/platform views in Operations. Native completion, human
  acceptance and delivery receipts remain distinct. Migrations **133–134** are
  required even when admission flags are closed; downgrade refuses retained
  execution evidence.
- Add durable submission intents, shared resource admission, deadlines,
  cooperative cancellation and reconciliation, with a separate short control
  worker. Uncertain external effects are not automatically replayed; unknown
  resource usage stays unknown.
- Provide an optional SDK-only Temporal candidate for two explicit linear
  agent/data compositions, using native Skills, DataOps, service review and
  receipts. LangGraph comparisons remain isolated experiments. Existing graph
  runtimes are retained; model providers, release images and the VM still need
  qualification. No feature is enabled by default or deployed by this change.
- Keep image budgets and the historical DataOps/connectors plans unchanged.
  See the [implementation and evidence](docs/agentium-execution-observability-implementation.md),
  [delivery procedure](docs/agentium-execution-operations.md) and
  [deferred work handover](docs/agentium-execution-deferred-handover.md).

## 2026-10-15 · Connector catalogue usable in production, C0 still open

- Ship the connector catalogue so it can be tried: governed connections, personal
  OAuth and secret scopes, version-bound System delegations, a shared local compute
  registry, isolated connector workers, and the Connections UI. Enabling the
  framework forces the network guard to enforce. No profile is Vérifié or Certifié.
  The certification bench, administered exceptions, image qualification as a C0
  exit, and the HANA bench stay open.
- Write approval stays bound to immutable input/target contracts and a successful
  preview. Unknown outcomes require reconciliation or explicit human abandonment.
  Migrations 127–132. Fabric/Entra, cloud bulk staging and unsupported lakehouse
  features remain explicit limits. See
  [implementation status](docs/agentium-connectors-implementation.md).

## 2026-10-14 · DataOps production activation (`0e401afc`)

- The operator reports production running revision `0e401afc`, verified through
  `build-info`, with DataOps preparation, Delta writes, service contracts and
  streaming scoring enabled globally. Backend and DataOps worker loaded the
  settings. Health checks passed; RabbitMQ now applies `consumer_timeout=3600000`
  with its volume retained, eight workers reconnected and the scheduler running.
- A real preparation in `default` produced one row in one Delta part. Service
  contract lists are accessible but empty; calibration reaches “corpus not
  found”. Streaming scoring has not been exercised. Activation is distinct from
  qualification of throughput, service delivery or judge quality.
- **Image-only rollback to `ad10dbc2` is incompatible with existing Delta
  versions.** Disabling Delta writes does not convert existing data, and removing
  the two probe datasets does not establish compatibility for other writes.
- Four blocked runs were cancelled and orphan reply queues were removed by the
  operator. HANA Showcase demo activation remains pending; narration, HANA writes
  and insecure TLS remain disabled. The [production record](docs/ops/dataops-production-2026-10-14.md)
  records the settings, dataset IDs, checks, cleanup and rollback constraints
  from the operator's report. No new live checks are claimed by this documentation.

## 2026-10-14 · DataOps candidate (not deployed)

Historical record before the production activation above; its image measurements
refer to `6dcb0d48`, not to a new measurement of `0e401afc`.

- Raise the VM build's backend image budget from **1400 to 1480 MiB** and the
  worker budget from **1760 to 1850 MiB**, following the release owner's VM
  measurements and explicit decision. Candidate `6dcb0d48` measures **1412 MiB**
  for the backend and **1765 MiB** for the worker, compared with **1356/1709 MiB**
  for production `ad10dbc2`. The new limits leave **68/85 MiB**, about 5%, above
  the measured candidate sizes.
- The roughly **56 MiB** increase comes from the compressed dependencies
  `sqlglot`, `deltalake`, `arro3-core` and `deprecated`. Docker 29/containerd's
  `docker image inspect .Size` is the budget measurement; the earlier
  **3420/3567 MiB** backend comparison counted uncompressed layer payloads.
  The shared layer count remains nine according to the VM report.
- Keep the frontend, ml-ts and livekit-agent budgets at **40/1240/110 MiB**;
  their measured candidate sizes are **28/1229/99 MiB**. ml-ts retains **11 MiB**
  of headroom. No Dockerfile, dependency, build option or measurement method is
  changed by this budget adjustment.
- Production remains on `ad10dbc2`, reported healthy. Candidate images remain
  unused by running containers. HANA Showcase's explicit demo mode with strict
  TLS is prepared but **not activated**. This change performs no merge or
  deployment. The [measurement and decision record](docs/dataops-release-blockers-2026-10-14.md#mesure-candidate-sur-la-vm-et-plafonds-retenus)
  distinguishes the user-supplied VM result from local validation.
- The release owner subsequently reran the budget check on the VM against the
  existing **`6dcb0d48` images**, using the limits committed in **`cd015ed6`**:
  **exit code 0**. The image-budget blocker is closed for those images and limits.
  No rebuild, deployment or HANA activation occurred. This records the owner's
  report; no new raw SSH bundle accompanies it. A future image build remains
  subject to its own budget check.

## [unreleased] — 2026-04-16 · Audit waves A → F

Implementation of the 10-ticket audit plan that closes the gap between
the canonical mental model, the backend engine and the Agentium
cockpit.

### Wave A — Skills runtime + canonical routers

- Introduced `app.services.rag.rag_service` and rewired the RAG
  skill wrappers so HAH / CHAH / reasoning templates flow through a
  single entry point.
- Added `GET /skills/runtime-health` exposing the tri-state status
  (`bound | stub | unbound`) of every registered skill.
- Migrated the legacy custom chains (`src/customchain*.py`) into
  `backend/app/services/rag/chains/` and registered them as canonical
  skills (`chain_naive_v1`, `chain_hybrid_v1`, `chain_mixed_hah_v1`).
- Frontend: replaced every `/agents` / `/traces/traces` call by the
  canonical `/systems` / `/runs` endpoints.

### Wave B — Reasoning templates & retrieval modes

- Backend: `GET /reasoning/templates` returns the canonical reasoning
  templates from `app.services.system_prompts`.
- `ChatRequest` gained `rag_mode_override` and `prompt_type` for
  per-query overrides.
- UI: chat panel and System Builder both expose selectors for
  reasoning template + retrieval mode. Assistant messages render a
  badge showing the active mode.

### Wave C — Context & per-system defaults

- Migration `005_system_defaults` adds `default_prompt_type`,
  `default_model` and `retrieval_mode_default` to `systems`.
- Run engine propagates these defaults into the skill `ctx` so every
  wrapper can honor them.
- Completed `/contexts` CRUD (PATCH + DELETE) and wired the canonical
  client. System Builder lets the operator reuse an existing context.
- Added a Context tab on `/systems/:id` and a dedicated
  `/steering/contexts` page.
- Resources page now shows which systems pin each model.

### Wave D — Runs & orphaned components

- New canonical Runs browser: `/runs` + `/runs/:runId` drill-down.
- `/observability/traces` redirects to `/runs`; the old
  `TracesListComponent` was deleted.
- Governance shell with tabs for `/governance/audit` and
  `/governance/access`.
- Command palette + side rail updated with a dedicated "Runs" entry.

### Wave E — Steering adaptive & Hypervisor What-If

- Migration `006_adaptive_policy_scope` adds `scope` + `target_id` to
  `adaptive_policies`.
- New endpoints: `PATCH /control-plane/adaptive/{id}`,
  `DELETE /control-plane/adaptive/{id}`,
  `POST /control-plane/adaptive/{id}/toggle`. List accepts
  `scope` + `target_id` filters.
- Steering cockpit exposes enable/disable/delete + a "before / after"
  simulate readout, filtering policies by the active scope.
- Hypervisor gains a canonical 4-lever What-If panel
  (`resource / velocity / autonomy / risk_tolerance`) wired to
  `POST /hypervisor/what-if` and a paginated Decisions feed with a
  detail drawer. `GET /hypervisor/decisions` supports
  `status / scope / kind / limit / offset`; `GET
  /hypervisor/decisions/{id}` returns the full decision payload.

### Wave F — Documentation

- Rewrote `docs/mental-model.md` to match the shipped runtime
  (canonical entities, per-system defaults, routes).
- New `docs/skills-runtime.md` — slug → module mapping with runtime
  status and the ctx-propagation contract.
- Created this `CHANGELOG.md`.
