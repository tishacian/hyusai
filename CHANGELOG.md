# Changelog

## Unreleased · UI/UX plan integration

- Published Flows open in read mode. Choose Modify to edit a draft; opening a
  published version no longer saves or aligns a draft automatically. Studio
  compares concurrent edits before replacement, and rollback names the release,
  channel and audience before confirmation.
- Decisions, member role changes and external writes distinguish refusal,
  failure and an unknown result. A lost response requires verification; it does
  not announce success or allow a duplicate creation. Application publication
  and activation show their confirmed receipt and actual audience.
- Creation can start from an empty workspace. Access failures explain the
  missing right or prerequisite, and the application wizard can resume after
  creating its linked System.
- Data provenance returns to the exact dataset version. Context freshness uses
  source dates, quality measures show their sample size, and the serving KPI
  excludes selected models that cannot be called.
- Impact uses integer counts and exposes assumptions. Missions are explicitly
  LLM writing tasks: saving does not launch them, attempts retain earlier output,
  and an interrupted attempt resumes from its persisted checkpoint. Secret
  changes show observed consumers before confirmation; restoration and account
  deletion report incomplete outcomes.
- Connector checks explain their scope; SharePoint and guest deposits retain
  per-file outcomes. Chat reports partial uploads, capture is reviewed before
  publication, and specialized applications distinguish their published release
  from the service revision.
- Delivery requires migrations 142–144 and the mission worker/beat configuration.
  These changes are not deployed. Validation results and outstanding
  browser, provider and human checks are recorded in
  `docs/ops/uiux-plan-2026-10-21/README.md`.

## 2026-10-20 · Measured finish on shared components

- Work buttons and links share the `.ck-btn` box: anchors such as « Services
  and deliveries » and the creator link are 32 px high and centred, the title
  bar glyph sits on its label, and Lucide icons follow their `size` again.
  Connections and the eight connector pages sit in the standard page frame,
  wizard groups are 20 px apart, the applications table keeps its actions on
  one line, Flow outline fields use the shared field and help links are 32 px
  targets. Visual change only, no behaviour or data change.
- `check:ui-chrome` now also counts type under 12 px (`--ck-text-meta`); the
  per-file budget is frozen at today's level and may only go down.

## 2026-10-17 · Operations tiles read the exhaustive Run series

- When activity series are open, the Operations tiles (runs, completed,
  running, failed, p95 latency) come from the same exhaustive, permission-
  filtered Run series as the chart below them, with the same period and anchor,
  instead of the 200-run sample. "Running" keeps the overview's native set
  (pending, running, human or debug wait, waiting sub-flows); the p95 is the
  exact nearest rank over measured finished runs, and a missing duration stays
  "—". Each tile opens Activities on the matching filter. Evaluation breaches
  keep their own source. With series closed, the sampled tiles are unchanged.
- The tiles never re-read the series on the overview's 5–15 s poll; they follow
  the period, anchor and System only.
- `check:ui-chrome` passes again. The global `.ck-input` from the connector
  catalogue painted its focus as a box-shadow halo, the seventh in
  `styles.scss` for a budget of six; focus now uses the global
  `:focus-visible` outline. The auth shell budgets are ratcheted down
  (violet 6 → 3, pill 6 → 5) as the guard asked.

## 2026-10-17 · Activity series read path lighter, migration 138

- The invocation consistency guard of the SQL series path scanned the whole
  workspace history with a nested loop whenever nothing differed (0.9–1.4 s per
  read). It now counts only the rows the request can select; a row outside the
  window reaches neither reader.
- Migration 138 adds typed `finished_at` and `duration_ms` copies of the
  activity snapshot, derived with the native reader's parsers and kept in step
  by the projection and an ORM hook, plus a `(workspace_id, finished_at)` index.
  Existing rows are back-filled in batches of 1,000. The snapshot stays the
  source; the native reader stays the test oracle.
- The aggregate joins only the native tables the requested kind can involve,
  skips the invocation join for activity counts when no invocation is orphaned,
  reads the cost evidence once per row, materializes once, and runs with
  `SET LOCAL work_mem` from `ACTIVITY_SERIES_WORK_MEM_MB` (16 by default, 4–256)
  instead of spilling to temporary files.
- Interleaved local benches (100,000 activities, PostgreSQL 16 defaults, a loaded
  workstation) cut the p95 by 3–6×. They are not a VM qualification: the 2 s
  target stays a release check. See the
  [evidence](docs/evidence/activity-series-typed-2026-10-17/report.md) and the
  [opening procedure](docs/agentium-execution-operations.md#ouverture-des-séries-et-de-la-vue-du-flow).
- Correction: production `8679a4f2` already contains R1, so Operations shows
  the monitor again. `4a404d61` was the revision that showed the activity view
  in that tab.

## 2026-10-15 · Connector catalogue made visible, with brand logos

- The Connectors page now shows the whole catalogue as one grid: 25 data
  sources, the generic MCP server, OpenAPI import, three official publisher MCP
  servers (GitHub, Notion, Atlassian) and the historical applications and
  channels, grouped by family, with search, family filters and capability chips.
  Historical cards that duplicate a profile (PostgreSQL, SAP HANA, MCP, S3,
  Elasticsearch, REST API) fold into the profile card and keep their own page.
- A new read-only `GET /api/v1/connector-catalog` serves profiles and official
  servers to workspace members even while the connector framework is off. It
  exposes no parameter, package, endpoint URL or secret. With the framework
  off, cards say so and only historical pages stay usable; with it on, Connect
  opens Connections with the profile preselected, and an official MCP server
  prefilled for an administrator to review.
- Brand logos come from Simple Icons 16.35.0 (CC0-1.0) as single monochrome
  paths, generated by `frontend-ng/scripts/gen-brand-registry.mjs` and bound as
  attributes. Delta Lake and Apache Iceberg have no logo there and keep a
  neutral glyph. Model providers and the Resources connector cards use the
  same logos. “Unverified” now reads “Not certified”; levels still come only
  from the server.
- `ck-input` gets a global, theme-aware style. It was only defined inside a few
  components, so in the dark theme every Connections field (and the catalogue
  search) rendered as a white box with near-white text.

## 2026-10-15 · Execution observability production activation (`4a404d61`)

- The operator reports production on `4a404d61`, with `build-info`, health,
  backup and migration checks completed, and the control worker and scheduler
  running. Journal, supervision, admission, deadlines, cancellation and
  reconciliation are open to all workspaces. The activity API is accessible
  and empty before new work; this does not establish a complete execution or
  delivery cycle. These are operator observations, not new VM checks here.
- `demo/agentic` and `develop` at `4a404d61`, and `main` at `05809a8d`.
  Temporal is off; the framework comparison and connector catalogue
  certification remain open. DataOps and connector activation states are unchanged.
- `up` selects the execution overlay from the frozen flags or from retained
  control containers, rejects divergent backend and control flags, and checks
  both control processes before reopening maintenance. Control capacity stays
  available while accepted work drains.
  See the [production record](docs/ops/execution-observability-production-2026-10-15.md).

## 2026-10-15 · Execution observability candidate (not deployed)

Historical qualification record before the operator-reported activation above.
Its local results are not new measurements of production `4a404d61`.

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
