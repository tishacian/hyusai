# Changelog

## 2026-10-14 · Connectors roadmap candidate (not deployed)

- Add governed multi-instance connections, personal OAuth and secret scopes,
  version-bound System delegations, a shared local compute registry, and isolated
  connector workers. Data, tool and lakehouse adapters expose explicit capabilities.
- Bind write approval to immutable input/target contracts and a successful preview.
  Unknown outcomes require reconciliation or explicit human abandonment; no blind replay.
  Add incremental checkpoints, immutable object/Delta exports and object-watch Flow triggers.
- Add the Connections UI, agent read/write-request Skills, evidence-bound badges,
  migrations 127–132 and an opt-in certification campaign for the VM operator.
- No profile is certified by these development tests. No deployment, budget increase,
  production exception or HANA qualification is included. Fabric/Entra, cloud bulk
  staging and unsupported lakehouse features remain explicit limits.
  BigQuery and object/HTTP/lakehouse observations lack the server version required
  by the current proof contract; an operator report cannot replace that missing identity.
  See [implementation status](docs/agentium-connectors-implementation.md) and
  [delegated certification](docs/agentium-connectors-certification-handoff.md).

## 2026-10-14 · DataOps candidate (not deployed)

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
