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
| 5 | `LOT5-WORKSPACE-BLUEPRINT-V2` — Workspace Blueprint v2 migrates portable experience safely | `full_stack` | ❌ 1/2 required | ✅ 1/1 required | ✅ 2/2 required | ✅ 3/3 required | `node`, `pytest` | 🟡 Partial |
| 5 | `LOT5-SURFACE-CATALOG-COVERAGE` — API catalog coverage uses the production router as oracle | `api` | ✅ 1/1 required | ✅ 1/1 required | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |
| 5 | `LOT5-CANONICAL-CONTRACTS` — Canonical workspace contracts replace implicit tenant branching progressively | `full_stack` | ✅ 7/7 required | ✅ 2/2 required | ❌ 2/3 required | ✅ 8/8 required | `node`, `pytest` | 🟡 Partial |
| 5 | `LOT5-COMPLIANCE-GOVERNANCE` — Product claims are computed and external evidence cannot self-promote | `governance` | ✅ 4/4 required | — | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |
| 6 | `LOT6-NAV-ONE-SCALE-PER-AXIS` — Cockpit navigation uses one scale per axis | `frontend` | ✅ 3/3 required | — | ✅ 2/2 required | ✅ 2/2 required | `node`, `playwright` | 🟠 Static verified |
| 6 | `LOT6-SYSTEM360-PERSPECTIVES` — One marked System exposes four distinct, evidence-backed perspectives | `full_stack` | ✅ 5/5 required | ✅ 1/1 required | ✅ 1/1 required | ✅ 1/1 required | `playwright` | 🟠 Static verified |
| 6 | `LOT6-P4-DURABLE-SUBFLOWS` — Durable Celery subflows preserve delegated Run identity | `backend` | ✅ 6/6 required | — | — | ✅ 4/4 required | `pytest` | 🟠 Static verified |
| 7 | `LOT7-OBJECT-GRAPH-PROJECTIONS` — Capability, Run and SkillInvocation expose governed object perspectives | `full_stack` | ❌ 7/8 required | ✅ 2/2 required | ✅ 1/1 required | ✅ 7/7 required | `playwright`, `pytest` | 🟡 Partial |
| 7 | `LOT7-AUTHORIZATION-ROLLOUT` — Action-level authorization advances through compat, shadow and enforce | `api` | ✅ 4/4 required | ✅ 2/2 required | — | ✅ 6/6 required | `pytest` | 🟠 Static verified |
| 7 | `LOT7-MEMBRANE-MEASUREMENTS` — Membrane budgets distinguish measured zero from unavailable telemetry | `backend` | ✅ 2/2 required | — | — | ✅ 2/2 required | `pytest` | 🟠 Static verified |
| 7 | `LOT7-ANDRITZ-MEMBRANE-SHADOW` — Andritz Membrane v2 shadow preparation is append-only and reversible | `backend` | ✅ 1/1 required | — | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |
| 8 | `LOT8-AUTHORITATIVE-VALUE-LOOP` — System value scenarios follow one governed evidence lifecycle | `full_stack` | ✅ 14/14 required | ✅ 4/4 required | ✅ 2/2 required | ✅ 19/19 required | `node`, `playwright`, `pytest` | 🟠 Static verified |
| 9 | `LOT9-WORKSPACE-APP-LIFECYCLE` — Workspace Apps use content-addressed lifecycle and runtime authority | `full_stack` | ✅ 11/11 required | ✅ 2/2 required | ✅ 4/4 required | ✅ 19/19 required | `node`, `playwright`, `pytest` | 🟠 Static verified |
| 9 | `LOT9-IMMUTABLE-SUPPLY-CHAIN` — Release contract binds source, images and semantic evidence by digest | `governance` | ✅ 2/2 required | — | — | ✅ 1/1 required | `pytest` | 🟠 Static verified |

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

Blueprint v2 exports portable experience and app-access intent, preserves homonymous System and Context objects through opaque workspace-scoped stable keys, restores bidirectional bindings and preset scopes, produces a dry-run plan token, and keeps unambiguous v1 imports compatible. Mental model: §0.2, §30, §33.

- **implementation / FAIL** — [Blueprint v2 service and compatibility boundary](../backend/app/services/workspace_blueprints.py); 1 literal(s) missing
- **implementation / PASS** — [Workspace-scoped Blueprint object identity migration](../backend/alembic/versions/071_blueprint_object_keys.py)
- **api / PASS** — [Blueprint validate/apply API](../backend/app/api/v1/endpoints/blueprints.py)
- **frontend / PASS** — [Immutable frontend dry-run binding](../frontend-ng/src/app/features/governance/workspace-blueprint-plan.ts)
- **frontend / PASS** — [Blueprint governance workbench](../frontend-ng/src/app/features/governance/workspace-blueprints.component.ts)
- **tests / PASS** — [Backend Blueprint v2 safety contract](../backend/app/tests/services/test_workspace_blueprints.py)
- **tests / PASS** — [Blueprint object-key migration contract](../backend/app/tests/services/test_migration_071_blueprint_object_keys.py)
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
- **frontend / FAIL** — [Canonical frontend workspace and application projection](../frontend-ng/src/app/core/workspace.service.ts); 1 literal(s) missing
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

### `LOT6-NAV-ONE-SCALE-PER-AXIS` — Cockpit navigation uses one scale per axis

Zone is the rail, object is the breadcrumb, facet is ?facet=. The zone summary never lists the four object types. Work is an RBAC link. cockpit\_nav\_v5 and the routed axes graduate to code defaults. Mental model: §5bis.

- **implementation / PASS** — [Lot 6 one-scale-per-axis contract](../docs/agentium-navigation-lot-6-one-scale-per-axis.md)
- **implementation / PASS** — [URL grammar v5](../docs/agentium-reference.md)
- **implementation / PASS** — [Facet catalogue and zone sections](../frontend-ng/src/app/core/navigation.catalog.ts)
- **frontend / PASS** — [Zone summary and System facet branch](../frontend-ng/src/app/features/layout/mini-rail.component.ts)
- **frontend / PASS** — [Builder mode home](../frontend-ng/src/app/core/navigation-resolver.service.ts)
- **tests / PASS** — [I1 sommaire and OBJECT\_FACETS](../frontend-ng/src/app/core/navigation.catalog.spec.ts)
- **tests / PASS** — [Navigation v5 canary](../frontend-ng/e2e/tests/19-navigation-v5-canary.spec.ts)

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
- **implementation / PASS** — [Transactional dispatch outbox and bounded reconciler](../backend/app/services/run_engine/dispatch_outbox.py)
- **implementation / PASS** — [Delegated HITL deadline watchdog](../backend/app/services/run_engine/hitl_watchdog.py)
- **implementation / PASS** — [Additive durable dispatch schema](../backend/alembic/versions/064_run_dispatch_outbox.py)
- **implementation / PASS** — [Bounded post-P4 maintenance worker](../backend/app/workers/p4_maintenance.py)
- **implementation / PASS** — [Protected PostgreSQL and RabbitMQ gate](../.gitlab-ci.yml)
- **tests / PASS** — [Real broker redelivery and fan-out integration](../backend/app/tests/integration/test_subflow_celery_rabbitmq.py)
- **tests / PASS** — [Outbox delivery and reconciliation contracts](../backend/app/tests/services/test_dispatch_outbox.py)
- **tests / PASS** — [Delegated HITL watchdog contracts](../backend/app/tests/services/test_hitl_watchdog.py)
- **tests / PASS** — [Bounded maintenance loop contracts](../backend/app/tests/services/test_p4_maintenance.py)

### `LOT7-OBJECT-GRAPH-PROJECTIONS` — Capability, Run and SkillInvocation expose governed object perspectives

Ordered Workspace gates expose four honest lenses for Capability, Run and SkillInvocation while preserving identity and historical execution evidence; final activations are bound to an exact server audit and current OIDC anchors, while every executable System reference crosses one tenant-aware catalog boundary. Mental model: §43.1, §43.5.

- **implementation / PASS** — [Attested runtime projection gate](../backend/app/services/projection_gate.py)
- **implementation / PASS** — [Object perspective read models](../backend/app/services/object_perspective.py)
- **implementation / PASS** — [Tenant-aware executable System catalog bindings](../backend/app/services/system_catalog_bindings.py)
- **implementation / PASS** — [Ordered marker-discovered projection rollout](../backend/scripts/rollout_lot7_projections.py)
- **implementation / FAIL** — [Additive immutable execution schema](../backend/alembic/versions/065_system_version_config.py); 1 literal(s) missing
- **implementation / PASS** — [Immutable invocation execution evidence migration](../backend/alembic/versions/066_skill_invocation_snapshot.py)
- **implementation / PASS** — [SystemVersion uniqueness migration](../backend/alembic/versions/067_system_version_uniqueness.py)
- **implementation / PASS** — [Five-profile user-validation gate](../scripts/agentium_trusted_compliance.py)
- **api / PASS** — [Capability perspective route](../backend/app/api/v1/endpoints/capabilities.py)
- **api / PASS** — [Run and SkillInvocation perspective routes](../backend/app/api/v1/endpoints/runs.py)
- **frontend / PASS** — [Epoch-scoped latest-wins projection cache](../frontend-ng/src/app/core/object-perspective.store.ts)
- **tests / PASS** — [Marker-discovered sequential object canary](../frontend-ng/e2e/tests/12-lot7-object-graph-canary.spec.ts)
- **tests / PASS** — [Object projection integrity tests](../backend/app/tests/services/test_object_perspective.py)
- **tests / PASS** — [Exact projection receipt and current trust-anchor gates](../backend/app/tests/services/test_lot7_projection_rollout.py)
- **tests / PASS** — [System catalog tenant-isolation and runtime boundary tests](../backend/app/tests/services/test_system_catalog_bindings.py)
- **tests / PASS** — [Additive migration contracts](../backend/app/tests/services/test_migration_067_system_version_uniqueness.py)
- **tests / PASS** — [PostgreSQL SystemVersion concurrency gate](../backend/app/tests/integration/test_system_version_postgresql.py)
- **tests / PASS** — [User-validation promotion thresholds](../backend/app/tests/infra/test_lot6_proof_contract.py)

### `LOT7-AUTHORIZATION-ROLLOUT` — Action-level authorization advances through compat, shadow and enforce

A single decision plane compares legacy and candidate permissions, binds shadow evidence to immutable JUnit artifacts and accepts enforce only after reloading the exact content-addressed promotion receipt, source ledger, review and current OIDC anchors. Mental model: §43.2.

- **implementation / PASS** — [Granular authorization decision plane](../backend/app/services/iam/decision_plane.py)
- **implementation / PASS** — [Server-owned authorization promotion receipt](../backend/scripts/rollout_authorization_v2.py)
- **implementation / PASS** — [JUnit execution invariant](../backend/app/services/iam/evidence_contracts.py)
- **implementation / PASS** — [SHA-bound Client360 authority preflight](../backend/scripts/preflight_client360_authority.py)
- **api / PASS** — [Persisted ActionManifest resource authority](../backend/app/api/v1/endpoints/actions.py)
- **api / PASS** — [Client360 action authorization boundary](../backend/app/api/v1/endpoints/client360.py)
- **tests / PASS** — [Authorization boundary and attestation tests](../backend/app/tests/api/test_authorization_v2_boundaries.py)
- **tests / PASS** — [Promotion evidence tests](../backend/app/tests/services/test_authorization_v2_rollout.py)
- **tests / PASS** — [Decision-plane canonical receipt enforcement](../backend/app/tests/services/test_iam_decision_plane.py)
- **tests / PASS** — [Client360 route authorization inventory](../backend/app/tests/api/test_client360_authorization_inventory.py)
- **tests / PASS** — [Managed Run structural approval floor](../backend/app/tests/api/test_runs_hitl_auth.py)
- **tests / PASS** — [Client360 authority preflight tests](../backend/app/tests/scripts/test_preflight_client360_authority.py)

### `LOT7-MEMBRANE-MEASUREMENTS` — Membrane budgets distinguish measured zero from unavailable telemetry

Cost, token and latency valves carry explicit coverage, include delegated child ledgers and fail closed under authoritative enforcement when a configured measure is unavailable. Mental model: §43.3.

- **implementation / PASS** — [Coverage-aware Membrane valves](../backend/app/services/membrane/enforcement.py)
- **implementation / PASS** — [Provider-reported Contract Risk token ledger](../backend/app/services/evaluation/judge.py)
- **tests / PASS** — [Runtime measurement coverage tests](../backend/app/tests/services/test_run_engine_membrane_v2.py)
- **tests / PASS** — [Contract Risk four-Skill token telemetry](../backend/app/tests/services/test_provider_token_telemetry.py)

### `LOT7-ANDRITZ-MEMBRANE-SHADOW` — Andritz Membrane v2 shadow preparation is append-only and reversible

A family-discovered dry-run workflow prepares append-only shadow policy generations, binds configuration snapshots and restores the source policy through a drift-checked rollback; runtime business non-regression remains a separate rollout gate. Mental model: §43.4.

- **implementation / PASS** — [Andritz shadow preparation and rollback](../backend/scripts/prepare_andritz_membrane_shadow.py)
- **tests / PASS** — [Append-only Andritz shadow lifecycle](../backend/app/tests/services/test_andritz_membrane_shadow_rollout.py)

### `LOT8-AUTHORITATIVE-VALUE-LOOP` — System value scenarios follow one governed evidence lifecycle

Outcome, decision, simulation, immutable approval snapshot, bounded actuation and independently sourced post-action measurement remain distinct and System-scoped; runtime\_auto and operator measurements require exact tenant-scoped server audits, policy transitions bind their action receipts, Decision lineage is compositional, and each promoted System owns an exact activation receipt while one workspace-wide canary marker/window prepares the next proof. Mental model: §44.

- **implementation / PASS** — [Transactional value-loop state machine](../backend/app/services/value_loop.py)
- **implementation / PASS** — [Audit-bound operator and runtime Run outcome provenance](../backend/app/services/run_outcome_provenance.py)
- **implementation / PASS** — [Attested per-System rollout and workspace-wide proof gate](../backend/scripts/rollout_value_loop.py)
- **implementation / PASS** — [Persisted value-loop facts and exact runtime receipts](../backend/app/services/value_loop_gate.py)
- **implementation / PASS** — [Redacted observation evidence collector](../backend/scripts/collect_value_loop_evidence.py)
- **implementation / PASS** — [Server-composed Steer actuator authority](../backend/app/services/system_perspective.py)
- **implementation / PASS** — [Additive value-loop persistence schema](../backend/alembic/versions/068_value_loop_core.py)
- **implementation / PASS** — [Forecast-bound measurement evaluation schema](../backend/alembic/versions/072_value_measurement_evaluation.py)
- **implementation / PASS** — [Fail-closed tenant and value-lineage integrity migration](../backend/alembic/versions/074_relational_integrity.py)
- **implementation / PASS** — [Immutable simulation approval pin](../backend/alembic/versions/075_simulation_approval_pin.py)
- **implementation / PASS** — [Decision to ValueScenario compositional lineage](../backend/alembic/versions/076_decision_scenario_lineage.py)
- **implementation / PASS** — [Canonical executed ControlPolicy identity](../backend/app/services/control_policy_snapshot.py)
- **implementation / PASS** — [Append-only Showcase configuration reconciliation](../backend/scripts/seed_showcase_workspace.py)
- **implementation / PASS** — [Server-owned Showcase seed boundary](../backend/app/services/seed_catalog_safety.py)
- **api / PASS** — [System-scoped value-loop commands](../backend/app/api/v1/endpoints/value_loop.py)
- **api / PASS** — [Atomic Run outcome override boundary](../backend/app/api/v1/endpoints/runs.py)
- **api / PASS** — [Portfolio value-loop aggregation](../backend/app/api/v1/endpoints/hypervisor.py)
- **api / PASS** — [Server-managed Showcase seed marker](../backend/app/api/v1/endpoints/auth.py)
- **frontend / PASS** — [Steer value-loop evidence UI](../frontend-ng/src/app/features/systems/system-value-loop.component.ts)
- **frontend / PASS** — [Portfolio Capability count avoids Run substitution](../frontend-ng/src/app/features/hypervisor/hypervisor-impact.ts)
- **tests / PASS** — [Value-loop transaction and evidence semantics](../backend/app/tests/services/test_value_loop.py)
- **tests / PASS** — [Current-authority API boundary](../backend/app/tests/api/test_value_loop_api.py)
- **tests / PASS** — [Operator outcome receipt attack tests](../backend/app/tests/services/test_run_outcome_provenance.py)
- **tests / PASS** — [Operator outcome API receipt and rollback](../backend/app/tests/api/test_object_perspective_api.py)
- **tests / PASS** — [Value-loop migration contracts](../backend/app/tests/services/test_migration_072_value_measurement_evaluation.py)
- **tests / PASS** — [Relational preflight and real Alembic round-trip](../backend/app/tests/services/test_migration_074_relational_integrity.py)
- **tests / PASS** — [Simulation approval pin migration](../backend/app/tests/services/test_migration_075_simulation_approval_pin.py)
- **tests / PASS** — [Decision scenario lineage migration and attacks](../backend/app/tests/services/test_migration_076_decision_scenario_lineage.py)
- **tests / PASS** — [ORM Decision scenario compositional lineage](../backend/app/tests/models/test_decision_scenario_lineage.py)
- **tests / PASS** — [ORM-aligned tenant and value lineage constraints](../backend/app/tests/models/test_agentium_relational_integrity.py)
- **tests / PASS** — [Protected/local evidence collection and activation](../backend/app/tests/services/test_value_loop_rollout.py)
- **tests / PASS** — [Append-only and idempotent Showcase seed reconciliation](../backend/app/tests/services/test_showcase_translation_suite_seed.py)
- **tests / PASS** — [Showcase seed ownership and destructive-CLI guards](../backend/app/tests/services/test_seed_catalog_safety.py)
- **tests / PASS** — [Showcase marker cannot be forged through generic workspace settings](../backend/app/tests/api/test_workspace_app_runtime_api.py)
- **tests / PASS** — [Server-authoritative Steer actuator projection](../backend/app/tests/services/test_system_perspective.py)
- **tests / PASS** — [PostgreSQL value-loop lock ordering](../backend/app/tests/integration/test_value_loop_postgresql.py)
- **tests / PASS** — [Steer six-step and fail-closed UI contract](../frontend-ng/src/app/features/systems/system-value-loop.component.spec.ts)
- **tests / PASS** — [Steer and Hypervisor authority presentation](../frontend-ng/src/app/features/hypervisor/hypervisor-impact.spec.ts)
- **tests / PASS** — [Marker-discovered value-loop canary](../frontend-ng/e2e/tests/13-lot8-value-loop-canary.spec.ts)

### `LOT9-WORKSPACE-APP-LIFECYCLE` — Workspace Apps use content-addressed lifecycle and runtime authority

Exact manifests govern compatibility, installation transitions, hierarchical API authority, routes, branding, action packs and entitlements; shell-aware canaries are re-derived server-side and every probation or activation requires its exact audit receipt plus current OIDC anchors. Mental model: §45.

- **implementation / PASS** — [Content-addressed Workspace App lifecycle](../backend/app/services/workspace_app_lifecycle.py)
- **implementation / PASS** — [Shared slash-boundary API authority contract](../backend/app/services/workspace_app_boundaries.py)
- **implementation / PASS** — [Fail-closed installed-app runtime](../backend/app/services/workspace_app_runtime.py)
- **implementation / PASS** — [Staged Workspace App authority rollout](../backend/scripts/rollout_workspace_app_platform.py)
- **implementation / PASS** — [Protected preflight and post-activation evidence collector](../backend/scripts/collect_workspace_app_evidence.py)
- **implementation / PASS** — [Immutable built-in manifest registry](../backend/app/services/workspace_app_manifests.py)
- **implementation / PASS** — [Manifest-defined entitlement schema boundary](../backend/alembic/versions/070_workspace_app_entitlement_registry.py)
- **implementation / PASS** — [Ordered lifecycle migration and backfill executors](../backend/app/services/workspace_app_lifecycle.py)
- **implementation / PASS** — [Tenant-scoped lifecycle step receipts](../backend/alembic/versions/073_workspace_app_steps.py)
- **implementation / PASS** — [Workspace App installation and receipt lineage integrity](../backend/alembic/versions/074_relational_integrity.py)
- **implementation / PASS** — [Manifest-owned API prefixes and generic Mission Room provider](../backend/app/services/workspace_app_runtime.py)
- **api / PASS** — [Workspace App governance API](../backend/app/api/v1/endpoints/workspace_app_governance.py)
- **api / PASS** — [Server-owned Workspace App canary marker](../backend/app/api/v1/endpoints/auth.py)
- **frontend / PASS** — [Shell-aware canary entry resolver](../frontend-ng/e2e/fixtures/workspace-app-canary.ts)
- **frontend / PASS** — [Content-addressed lifecycle console](../frontend-ng/src/app/features/governance/workspace-app-lifecycle.component.ts)
- **frontend / PASS** — [Authoritative frontend fail-closed and repair contract](../frontend-ng/src/app/core/workspace-experience.ts)
- **frontend / PASS** — [Isolated Workspace App unavailable shell](../frontend-ng/src/app/features/workspace-app-runtime/workspace-app-unavailable.component.ts)
- **tests / PASS** — [Lifecycle transition and rollback contracts](../backend/app/tests/services/test_workspace_app_lifecycle.py)
- **tests / PASS** — [Manifest isolation and publication lock](../backend/app/tests/services/test_workspace_app_manifests.py)
- **tests / PASS** — [Installed runtime authority](../backend/app/tests/services/test_workspace_app_runtime.py)
- **tests / PASS** — [Staged bootstrap, probation, finalize and OIDC gates](../backend/app/tests/services/test_workspace_app_platform_rollout.py)
- **tests / PASS** — [Server-owned marker API boundary](../backend/app/tests/api/test_workspace_app_runtime_api.py)
- **tests / PASS** — [Workspace App evidence phase and probation bindings](../backend/app/tests/services/test_workspace_app_evidence_collector.py)
- **tests / PASS** — [API-prefix conflicts at governance plan and apply boundaries](../backend/app/tests/api/test_workspace_app_governance_api.py)
- **tests / PASS** — [Entitlement registry migration](../backend/app/tests/services/test_migration_070_workspace_app_entitlement_registry.py)
- **tests / PASS** — [Lifecycle step receipt migration](../backend/app/tests/services/test_migration_073_workspace_app_steps.py)
- **tests / PASS** — [Relational Workspace App lineage constraints](../backend/app/tests/models/test_agentium_relational_integrity.py)
- **tests / PASS** — [Generic Mission Room provider isolation](../backend/app/tests/api/test_mission_room_extension_gate.py)
- **tests / PASS** — [Platform-authoritative entitlement boundary](../backend/app/tests/api/test_app_entitlements_api.py)
- **tests / PASS** — [Authenticated preflight lifecycle canary](../frontend-ng/e2e/tests/14-lot9-workspace-app-lifecycle-canary.spec.ts)
- **tests / PASS** — [Authenticated probation runtime canary](../frontend-ng/e2e/tests/15-lot9-workspace-app-probation-canary.spec.ts)
- **tests / PASS** — [Specialized Mission Room direct workspace switch](../frontend-ng/src/app/features/mission-room/mission-room.component.spec.ts)
- **tests / PASS** — [Generic Mission Room direct workspace switch](../frontend-ng/src/app/features/mission-room/generic-mission-room.component.spec.ts)
- **tests / PASS** — [Shell-aware canary fail-closed unit contract](../frontend-ng/src/app/core/workspace-app-canary.spec.ts)
- **tests / PASS** — [Frontend unavailable and admin repair isolation](../frontend-ng/src/app/core/workspace-experience.spec.ts)
- **tests / PASS** — [Resolver owns terminal unavailable redirects](../frontend-ng/src/app/core/navigation-resolver.service.spec.ts)

### `LOT9-IMMUTABLE-SUPPLY-CHAIN` — Release contract binds source, images and semantic evidence by digest

Release schema v2 binds the exact repository revision, populated SBOM, SLSA build invocation and every backend, frontend and worker digest to image signatures, DSSE attestations, the tested set, a mandatory deployment receipt and served build-info; offline validation remains non-cryptographic and an explicit live runner performs nine pinned Cosign checks. Mental model: §45.

- **implementation / PASS** — [Digest-bound release verifier](../scripts/agentium_release_contract.py)
- **implementation / PASS** — [Registry digest deployment overlay](../docker/compose.agentium.registry.yml)
- **tests / PASS** — [Semantic supply-chain failure contracts](../backend/app/tests/infra/test_lot9_release_contract.py)

## Residual workspace-slug branch debt

Inventory schema v1 declares **2 occurrence(s)** across **2 expression(s)**. Any new, removed, duplicated or edited branch fails `--check` until this versioned debt list is reviewed explicitly.

Runtime scan roots: `backend/app`, `frontend-ng/src/app`. Excluded paths: `backend/app/tests`, `backend/app/cli`. Excluded suffixes: `*.spec.ts`.

Alembic migrations and repository utilities under `backend/scripts` are outside these runtime scan roots; migration 058's one-shot legacy inference is covered by its own implementation and test proofs. Runtime seed/bootstrap code under `backend/app` remains scanned.

| Path | Expression | Occurrences | Category | Reason |
|---|---|---:|---|---|
| [`backend/app/services/mission_room.py`](../backend/app/services/mission_room.py) | `Workspace.slug == OCTOCITY_WORKSPACE_SLUG` | 1 | `provisioning_identity` | The explicit, idempotent Octocity provisioning command locates the workspace identity it owns; runtime presentation and authorization use the Mission Room profile instead. |
| [`backend/app/services/mission_room.py`](../backend/app/services/mission_room.py) | `Workspace.slug == SENTINEL_WORKSPACE_SLUG` | 1 | `provisioning_identity` | The explicit, idempotent Sentinel provisioning command locates the workspace identity it owns; runtime behavior is family/profile/action-pack driven. |

## Static and authenticated evidence levels

Repository proofs, runner results, environment evidence, behavioral evidence and user validation are deliberately independent. JSON passed to this static generator remains untrusted; only the authenticated CI collector can derive a higher formal state:

- `python3 scripts/agentium_compliance.py --check` verifies the committed manifest and generated documentation.
- `--runner-attestation <json> --sha <40-hex-sha>` records claimed runner evidence for an exact commit; it never sets `runner_verified` or `shipped`.
- `--deployment-attestation <json> --sha <40-hex-sha>` records a claimed environment; it never sets `deployed`.
- The requested SHA must equal Git `HEAD`, `CI_COMMIT_SHA` when present, and a completely clean checkout; evidence for another or dirty ref is rejected.
- `--report-json <path|->` emits the combined machine-readable view. Neither external evidence type mutates this matrix.
- `scripts/agentium_trusted_compliance.py` verifies the protected GitLab OIDC identity and derives `runner_verified → deployed_verified → behavior_verified → user_validated` from separate SHA- and job-bound artifacts.
- `--user-attestation` is accepted only after behavioral proof and must cover five required profiles, at least four successes for each of four questions, mean confidence of at least 4/5 and zero critical identity or lens confusion.

Formal promotion is intentionally disabled in this static generator. The trusted collector writes a separate immutable CI artifact and never edits this matrix or the mental model. A decorative mechanism therefore cannot self-declare `Shipped` or `Deployed` through a hand-written JSON file, branch name, manifest field, or documentation badge.
