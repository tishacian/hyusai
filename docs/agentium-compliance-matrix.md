# Agentium compliance matrix

<!-- GENERATED FILE: run `python3 scripts/agentium_compliance.py`; DO NOT EDIT. -->

Source contract: [`config/agentium/product-compliance.v1.json`](../config/agentium/product-compliance.v1.json). The repository state below is computed from inspectable files and literals; it is never authored in the manifest.

`🟠 Static verified` means every repository proof family required by the claim kind passes, including a declared test contract. It does not attest that those tests ran. Local JSON evidence is recorded but cannot promote a claim to a formal delivery state.

| Lot | Claim | Kind | Implementation | API | Frontend | Tests | Required runners | Computed repository state |
|---:|---|---|---|---|---|---|---|---|
| 0 | `LOT0-BASELINE-CONTRACT` — Workspace experience baseline is explicit and regression-tested | `governance` | ✅ 1/1 required | — | — | ✅ 2/2 required | `playwright`, `pytest` | 🟠 Static verified |
| 1 | `LOT1-STABILITY-CONTRACT` — Workspace navigation remains stable across retries, rails and switches | `frontend` | ✅ 5/5 required | — | ✅ 2/2 required | ✅ 4/4 required | `node` | 🟠 Static verified |
| 2 | `LOT2-WORKSPACE-EXPERIENCE-RESOLVER` — Workspace experience resolver is flagged, shadowed and fail-closed | `frontend` | ✅ 2/2 required | — | ✅ 1/1 required | ✅ 2/2 required | `node` | 🟠 Static verified |
| 3 | `LOT3-COCKPIT-AXES` — Cockpit lenses preserve object identity and hierarchy | `frontend` | ✅ 2/2 required | — | ✅ 1/1 required | ✅ 1/1 required | `node` | 🟠 Static verified |
| 4 | `LOT4-SHOWCASE-CANARY-DISCOVERY` — Showcase canary discovers the live graph instead of a fixed slug | `governance` | ✅ 1/1 required | — | — | ✅ 1/1 required | `playwright` | 🟠 Static verified |
| 4 | `LOT4-BUSINESS-SHELL-MISSION-EXTENSION` — Andritz shell and Mission Room are resolver-owned extensions | `full_stack` | ✅ 2/2 required | ✅ 1/1 required | ✅ 1/1 required | ✅ 3/3 required | `node`, `pytest` | 🟠 Static verified |
| 4 | `LOT4-SENTINEL-OCTOCITY-ISOLATION` — Sentinel and Octocity keep isolated branding and action packs | `full_stack` | ✅ 1/1 required | ✅ 1/1 required | ✅ 1/1 required | ✅ 2/2 required | `node`, `pytest` | 🟠 Static verified |
| 4 | `LOT4-ANDRITZ-APP-ENTITLEMENTS` — Andritz app entitlements are explicit and fully backfilled | `full_stack` | ✅ 2/2 required | ✅ 1/1 required | ✅ 1/1 required | ✅ 3/3 required | `pytest` | 🟠 Static verified |
| 5 | `LOT5-WORKSPACE-BLUEPRINT-V2` — Workspace Blueprint v2 migrates portable experience safely | `full_stack` | ✅ 1/1 required | ✅ 1/1 required | ✅ 2/2 required | ✅ 2/2 required | `node`, `pytest` | 🟠 Static verified |
| 5 | `LOT5-SURFACE-CATALOG-COVERAGE` — API catalog coverage uses the production router as oracle | `api` | ✅ 1/1 required | ✅ 1/1 required | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |
| 5 | `LOT5-CANONICAL-CONTRACTS` — Canonical workspace contracts replace implicit tenant branching progressively | `full_stack` | ✅ 7/7 required | ✅ 2/2 required | ✅ 3/3 required | ✅ 8/8 required | `node`, `pytest` | 🟠 Static verified |
| 5 | `LOT5-COMPLIANCE-GOVERNANCE` — Product claims are computed and external evidence cannot self-promote | `governance` | ✅ 4/4 required | — | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |
| 6 | `LOT6-SYSTEM360-PERSPECTIVES` — One marked System exposes four distinct, evidence-backed perspectives | `full_stack` | ✅ 5/5 required | ✅ 1/1 required | ✅ 1/1 required | ✅ 1/1 required | `playwright` | 🟠 Static verified |
| 6 | `LOT6-P4-DURABLE-SUBFLOWS` — Durable Celery subflows preserve delegated Run identity | `backend` | ✅ 2/2 required | — | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |

## Evidence detail

### `LOT0-BASELINE-CONTRACT` — Workspace experience baseline is explicit and regression-tested

The pre-migration Andritz, Showcase, Sentinel and Octocity contracts are recorded without embedding credentials, and have live/backend contract tests. Mental model: §0, §34.

- **implementation / PASS** — [Lot 0 navigation baseline](../docs/agentium-navigation-lot-0-baseline.md)
- **tests / PASS** — [Andritz surface access contract](../backend/app/tests/api/test_andritz_surface_access_contract.py)
- **tests / PASS** — [Live workspace experience contract](../frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts)

### `LOT1-STABILITY-CONTRACT` — Workspace navigation remains stable across retries, rails and switches

The workspace header survives retry, one resolver owns redirects, the expanded rail overlays a fixed slot, Client360 stays in Operate, and workspace context changes are atomic. Mental model: §5bis, §34, §38.

- **implementation / PASS** — [Workspace-scoped authentication retry](../frontend-ng/src/app/core/auth.interceptor.ts)
- **implementation / PASS** — [Single navigation redirect owner](../frontend-ng/src/app/core/navigation-resolver.service.ts)
- **implementation / PASS** — [Constant rail layout slot with overlay expansion](../frontend-ng/src/app/features/layout/side-rail.component.ts)
- **implementation / PASS** — [Client360 Operate classification](../frontend-ng/src/app/core/navigation.catalog.ts)
- **implementation / PASS** — [Atomic workspace context epoch](../frontend-ng/src/app/core/workspace.service.ts)
- **frontend / PASS** — [Workspace request-scope public contract](../frontend-ng/src/app/core/workspace.service.ts)
- **frontend / PASS** — [Five-verb rail implementation](../frontend-ng/src/app/features/layout/side-rail.component.ts)
- **tests / PASS** — [Retry header tests](../frontend-ng/src/app/core/auth.interceptor.spec.ts)
- **tests / PASS** — [Resolver ownership tests](../frontend-ng/src/app/core/navigation-resolver.service.spec.ts)
- **tests / PASS** — [Client360 lens test](../frontend-ng/src/app/core/navigation.catalog.spec.ts)
- **tests / PASS** — [Atomic workspace switch tests](../frontend-ng/src/app/core/workspace.service.spec.ts)

### `LOT2-WORKSPACE-EXPERIENCE-RESOLVER` — Workspace experience resolver is flagged, shadowed and fail-closed

A pure V2 resolver is gated behind one flag, compared with an independent legacy oracle, and observed through privacy-safe rollout evidence. Mental model: §5bis, §34, §38.

- **implementation / PASS** — [Pure workspace experience model](../frontend-ng/src/app/core/workspace-experience.ts)
- **implementation / PASS** — [Passive shadow runtime](../frontend-ng/src/app/core/workspace-experience-shadow.service.ts)
- **frontend / PASS** — [Feature-flag integration boundary](../frontend-ng/src/app/core/navigation-profile.service.ts)
- **tests / PASS** — [Resolver parity and evidence gates](../frontend-ng/src/app/core/workspace-experience.spec.ts)
- **tests / PASS** — [Shadow fail-closed tests](../frontend-ng/src/app/core/workspace-experience-shadow.service.spec.ts)

### `LOT3-COCKPIT-AXES` — Cockpit lenses preserve object identity and hierarchy

Hypervisor, Build, Operate, Steer and Govern are projections over stable Capability, System, Run and Skill identities rather than separate object trees. Mental model: §5bis, §35, §39.

- **implementation / PASS** — [Canonical cockpit verb and hierarchy catalog](../frontend-ng/src/app/core/navigation.catalog.ts)
- **implementation / PASS** — [Stable object canvas](../frontend-ng/src/app/features/capabilities/capability-view.component.ts)
- **frontend / PASS** — [Object-aware URL projection](../frontend-ng/src/app/core/navigation.catalog.ts)
- **tests / PASS** — [Cockpit identity contract](../frontend-ng/src/app/core/navigation.catalog.spec.ts)

### `LOT4-SHOWCASE-CANARY-DISCOVERY` — Showcase canary discovers the live graph instead of a fixed slug

The Playwright canary selects an actual System linked to a Capability and Run, avoiding the retired showcase\_contract\_risk identifier. Mental model: §5bis, §38.

- **implementation / PASS** — [Auto-discovering Showcase graph canary](../frontend-ng/e2e/tests/10-cockpit-axes-canary.spec.ts)
- **tests / PASS** — [Showcase identity/history scenario](../frontend-ng/e2e/tests/10-cockpit-axes-canary.spec.ts)

### `LOT4-BUSINESS-SHELL-MISSION-EXTENSION` — Andritz shell and Mission Room are resolver-owned extensions

The flagged Andritz business shell keeps its three canonical surfaces while Mission Room is described and gated as an extension without moving its business components. Mental model: §0.4, §5bis, §34.

- **implementation / PASS** — [Three-surface business resolver contract](../frontend-ng/src/app/core/workspace-experience.ts)
- **implementation / PASS** — [Dependency-free Mission Room extension descriptor](../frontend-ng/src/app/features/mission-room/mission-room.extension.ts)
- **api / PASS** — [Mission Room API extension gate](../backend/app/api/v1/endpoints/mission_room.py)
- **frontend / PASS** — [Business and immersive shell composition](../frontend-ng/src/app/features/layout/shell.component.ts)
- **tests / PASS** — [Business resolver URL contract](../frontend-ng/src/app/core/workspace-experience.spec.ts)
- **tests / PASS** — [Mission Room extension contract](../frontend-ng/src/app/features/mission-room/mission-room.extension.spec.ts)
- **tests / PASS** — [Backend extension discovery gate](../backend/app/tests/api/test_mission_room_extension_gate.py)

### `LOT4-SENTINEL-OCTOCITY-ISOLATION` — Sentinel and Octocity keep isolated branding and action packs

Each Mission Room profile resolves its own assistant, brand and action packs, with explicit cross-vocabulary rejection on backend and frontend. Mental model: §0.4, §30, §38.

- **implementation / PASS** — [Workspace-derived Mission Room presentation](../frontend-ng/src/app/features/mission-room/mission-room.extension.ts)
- **api / PASS** — [Workspace-scoped Mission Room endpoints](../backend/app/api/v1/endpoints/mission_room.py)
- **frontend / PASS** — [Mission Room presentation isolation](../frontend-ng/src/app/features/mission-room/mission-room.presentation.ts)
- **tests / PASS** — [Frontend profile and action-pack isolation](../frontend-ng/src/app/features/mission-room/mission-room.extension.spec.ts)
- **tests / PASS** — [Backend profile vocabulary isolation](../backend/app/tests/api/test_mission_room_extension_gate.py)

### `LOT4-ANDRITZ-APP-ENTITLEMENTS` — Andritz app entitlements are explicit and fully backfilled

The three business apps are granted per member, exposed by auth/IAM, enforced by the resolver, and enabled only after an explicit validated Andritz migration backfill. Mental model: §0.2, §33, §34.

- **implementation / PASS** — [Canonical app-entitlement service](../backend/app/services/iam/app_entitlements.py)
- **implementation / PASS** — [Validated Andritz entitlement backfill](../backend/alembic/versions/057_workspace_app_entitlements.py)
- **api / PASS** — [Auth membership entitlement API](../backend/app/api/v1/endpoints/auth.py)
- **frontend / PASS** — [Frontend membership and resolver entitlement projection](../frontend-ng/src/app/core/workspace.service.ts)
- **tests / PASS** — [Entitlement API contract](../backend/app/tests/api/test_app_entitlements_api.py)
- **tests / PASS** — [Backfill and fail-closed migration tests](../backend/app/tests/services/test_migration_057_workspace_app_entitlements.py)
- **tests / PASS** — [Client360 settings keep endpoint-level admin authorization](../backend/app/tests/api/test_client360_mail_settings_api.py)

### `LOT5-WORKSPACE-BLUEPRINT-V2` — Workspace Blueprint v2 migrates portable experience safely

Blueprint v2 exports portable experience and app-access intent, validates actions and isolation, produces a dry-run plan token, and keeps v1 imports compatible. Mental model: §0.2, §30, §33.

- **implementation / PASS** — [Blueprint v2 service and compatibility boundary](../backend/app/services/workspace_blueprints.py)
- **api / PASS** — [Blueprint validate/apply API](../backend/app/api/v1/endpoints/blueprints.py)
- **frontend / PASS** — [Immutable frontend dry-run binding](../frontend-ng/src/app/features/governance/workspace-blueprint-plan.ts)
- **frontend / PASS** — [Blueprint governance workbench](../frontend-ng/src/app/features/governance/workspace-blueprints.component.ts)
- **tests / PASS** — [Backend Blueprint v2 safety contract](../backend/app/tests/services/test_workspace_blueprints.py)
- **tests / PASS** — [Frontend stale-plan protection](../frontend-ng/src/app/features/governance/workspace-blueprint-plan.spec.ts)

### `LOT5-SURFACE-CATALOG-COVERAGE` — API catalog coverage uses the production router as oracle

Every real API prefix, including operational and admin surfaces, must resolve to catalog metadata; a curated mini-router cannot hide gaps. Mental model: §0.2, §15, §33.

- **implementation / PASS** — [Surface metadata for previously uncovered prefixes](../backend/app/services/surface_catalog.py)
- **api / PASS** — [Real API router](../backend/app/api/v1/router.py)
- **tests / PASS** — [Production router coverage test](../backend/app/tests/api/test_surface_catalog.py)

### `LOT5-CANONICAL-CONTRACTS` — Canonical workspace contracts replace implicit tenant branching progressively

Workspace, System, application and action-pack vocabularies are canonical at database and API boundaries; runtime family and pack resolution is configuration-driven, while remaining slug-specific compatibility debt is explicitly inventoried and drift-gated. Mental model: §0.2, §20, §30, §33.

- **implementation / PASS** — [Shared canonical backend vocabularies](../backend/app/schemas/canonical.py)
- **implementation / PASS** — [Canonical action-pack contract and derived registry](../backend/app/services/actions/registry.py)
- **implementation / PASS** — [Fail-safe stamped workspace family resolver](../backend/app/services/workspace_features.py)
- **implementation / PASS** — [Reversible one-shot canonical backfill](../backend/alembic/versions/058_canonical_workspace_system_contracts.py)
- **implementation / PASS** — [Versioned residual slug-debt gate](../scripts/agentium_compliance.py)
- **implementation / PASS** — [Lot 5 canonical cleanup and rollout contract](../docs/agentium-navigation-lot-5-cleanup-governance.md)
- **implementation / PASS** — [Database-aware immutable image rollback](../scripts/deploy-vm.sh)
- **api / PASS** — [Workspace mutation schema canonicalization](../backend/app/api/v1/endpoints/auth.py)
- **api / PASS** — [System mutation schema canonicalization](../backend/app/api/v1/endpoints/systems.py)
- **frontend / PASS** — [Canonical frontend System contract projection](../frontend-ng/src/app/core/canonical-api.service.ts)
- **frontend / PASS** — [Canonical frontend workspace and application projection](../frontend-ng/src/app/core/workspace.service.ts)
- **frontend / PASS** — [Configuration-driven Mission Room extension](../frontend-ng/src/app/features/mission-room/mission-room.extension.ts)
- **tests / PASS** — [Canonical enum and database constraint contract](../backend/app/tests/services/test_canonical_contract_enums.py)
- **tests / PASS** — [Canonical action-pack API boundaries](../backend/app/tests/services/test_action_pack_contracts.py)
- **tests / PASS** — [No implicit tenant action packs](../backend/app/tests/services/test_actions_registry.py)
- **tests / PASS** — [Workspace family fail-safe contract](../backend/app/tests/services/test_workspace_features.py)
- **tests / PASS** — [Canonical migration round-trip and audit contract](../backend/app/tests/services/test_migration_058_canonical_workspace_system_contracts.py)
- **tests / PASS** — [Mission Room profile isolation remains configuration-driven](../frontend-ng/src/app/features/mission-room/mission-room.extension.spec.ts)
- **tests / PASS** — [Slug debt inventory drift tests](../backend/app/tests/infra/test_agentium_compliance_contract.py)
- **tests / PASS** — [Database revision rollback guard test](../backend/app/tests/infra/test_agentium_compliance_contract.py)

### `LOT5-COMPLIANCE-GOVERNANCE` — Product claims are computed and external evidence cannot self-promote

One machine-readable manifest derives repository states, rejects manual formal badges, binds external evidence to a clean exact SHA, and intentionally disables formal promotion until an authenticated CI collector exists. Mental model: §0, §33.

- **implementation / PASS** — [Compliance generator and checker](../scripts/agentium_compliance.py)
- **implementation / PASS** — [State-free product compliance manifest](../config/agentium/product-compliance.v1.json)
- **implementation / PASS** — [Repository CI compliance gate](../.gitlab-ci.yml)
- **implementation / PASS** — [Pinned-checkout deployment static gate](../scripts/deploy-vm.sh)
- **tests / PASS** — [Static compliance governance tests](../backend/app/tests/infra/test_agentium_compliance_contract.py)

### `LOT6-SYSTEM360-PERSPECTIVES` — One marked System exposes four distinct, evidence-backed perspectives

A marker-discovered System keeps one canonical identity while Build, Operate, Steer and Govern expose separate persisted projections, and a protected SHA-bound browser gate records the runtime proof. Mental model: §5bis, §33.

- **implementation / PASS** — [System perspective read model](../backend/app/services/system_perspective.py)
- **implementation / PASS** — [Protected runtime evidence pipeline](../.gitlab-ci.yml)
- **implementation / PASS** — [Ordered structural rollout state machine](../backend/scripts/rollout_system360_canary.py)
- **implementation / PASS** — [Quiesced VM deployment wrapper](../scripts/deploy-lot6-system360.sh)
- **implementation / PASS** — [Authenticated evidence state derivation](../scripts/agentium_trusted_compliance.py)
- **api / PASS** — [Marker-gated System perspective endpoint](../backend/app/api/v1/endpoints/systems.py)
- **frontend / PASS** — [Typed four-lens System projection](../frontend-ng/src/app/features/systems/system-perspective.component.ts)
- **tests / PASS** — [Authenticated marker-discovered System canary](../frontend-ng/e2e/tests/11-system360-canary.spec.ts)

### `LOT6-P4-DURABLE-SUBFLOWS` — Durable Celery subflows preserve delegated Run identity

A double-gated Celery execution path persists immutable child identities, resumes the parent idempotently and applies deterministic all, any and race joins under real broker redelivery. Mental model: §33.

- **implementation / PASS** — [Persisted subflow coordination](../backend/app/services/run_engine/subflow_orchestration.py)
- **implementation / PASS** — [Protected PostgreSQL and RabbitMQ gate](../.gitlab-ci.yml)
- **tests / PASS** — [Real broker redelivery and fan-out integration](../backend/app/tests/integration/test_subflow_celery_rabbitmq.py)

## Residual workspace-slug branch debt

Inventory schema v1 declares **2 occurrence(s)** across **2 expression(s)**. Any new, removed, duplicated or edited branch fails `--check` until this versioned debt list is reviewed explicitly.

Runtime scan roots: `backend/app`, `frontend-ng/src/app`. Excluded paths: `backend/app/tests`, `backend/app/cli`. Excluded suffixes: `*.spec.ts`.

Alembic migrations and repository utilities under `backend/scripts` are outside these runtime scan roots; migration 058's one-shot legacy inference is covered by its own implementation and test proofs. Runtime seed/bootstrap code under `backend/app` remains scanned.

| Path | Expression | Occurrences | Category | Reason |
|---|---|---:|---|---|
| [`backend/app/services/mission_room.py`](../backend/app/services/mission_room.py) | `Workspace.slug == OCTOCITY_WORKSPACE_SLUG` | 1 | `provisioning_identity` | The explicit, idempotent Octocity provisioning command locates the workspace identity it owns; runtime presentation and authorization use the Mission Room profile instead. |
| [`backend/app/services/mission_room.py`](../backend/app/services/mission_room.py) | `Workspace.slug == SENTINEL_WORKSPACE_SLUG` | 1 | `provisioning_identity` | The explicit, idempotent Sentinel provisioning command locates the workspace identity it owns; runtime behavior is family/profile/action-pack driven. |

## Runner and deployment attestations

Repository proofs, runner results, and deployment evidence are deliberately independent. External JSON is treated as untrusted evidence until an authenticated CI collector derives it:

- `python3 scripts/agentium_compliance.py --check` verifies the committed manifest and generated documentation.
- `--runner-attestation <json> --sha <40-hex-sha>` records claimed runner evidence for an exact commit; it never sets `runner_verified` or `shipped`.
- `--deployment-attestation <json> --sha <40-hex-sha>` records a claimed environment; it never sets `deployed`.
- The requested SHA must equal Git `HEAD`, `CI_COMMIT_SHA` when present, and a completely clean checkout; evidence for another or dirty ref is rejected.
- `--report-json <path|->` emits the combined machine-readable view. Neither external evidence type mutates this matrix.

Formal promotion is intentionally disabled until a trusted CI collector derives proof coverage from immutable job identities and artifacts. A decorative mechanism therefore cannot self-declare `Shipped` or `Deployed` through a hand-written JSON file, branch name, manifest field, or documentation badge.
