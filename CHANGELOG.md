# Changelog

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
