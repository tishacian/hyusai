# Agentium reference — identity, lexicon, surfaces, Experience platform

> One document for what used to be three: the identity card, the surface map
> and the Experience platform architecture. The normative source stays
> [`mental-model.md`](./mental-model.md); this reference is its stable, short
> form, and the place to answer "what do we call this, and where does it live?".
> Runtime truth for the API surface is `GET /api/v1/catalog/endpoints`.

---

## 1. In one sentence

**Agentium** is a cockpit for running **intelligent systems** in an enterprise:
business objectives, capabilities and policies, measured executions,
governance and continuous improvement — not a chat nor an isolated agent
builder.

| Axis | What Agentium brings |
| --- | --- |
| **Alignment** | A **System** ties an objective to real capabilities (skills, RAG, policies). |
| **Observability** | Every answer goes through traceable **Runs** (cost, latency, context). |
| **Quality** | **Evaluations** score outputs; thresholds and presets make measurement systematic. |
| **Action** | **Decisions** (Hypervisor / Steering) materialise acceptance, rejection or recommendations; the loop reaches **replay**, **feedback** and **canonical answers**. |
| **Governance** | Audit, policies, human approval, connectors with a trail — control is explicit, never "prompt only". |

The canonical business chain:

```text
System → Run → Evaluation → Decision → Action
```

- **System** — a declaration of intent: objective, execution graph, context, policies.
- **Run** — one execution (chat, engine, canonical answer without an LLM, replay).
- **Evaluation** — composite score and dimensions (RAG component attribution when applicable).
- **Decision** — a human or machine proposal (review, proactive recommendation, policy patch).
- **Action** — replay with overrides, applied suggestion, accept/reject with feedback, promotion to a canonical answer.

Persistent entities (see `mental-model.md` §0.1): **Workspace**, **System**,
**Capability**, **Skill**, **Context**, **ControlPolicy** / **AdaptivePolicy**,
**Run**, **EvaluationScore**, **Decision**, **Impact**, plus **EvaluationFeedback**,
**CanonicalAnswer**, **EvaluationPreset** and the `parent_run_id` lineage.

## 2. Lexicon — one concept, one word

The enforceable vocabulary lives in
`frontend-ng/src/app/core/i18n.lexicon.ts`; `npm run check:i18n` fails on a
banned synonym in any UI string. The words that name **where a person is**:

| Word | Meaning | Routes | Who |
| --- | --- | --- | --- |
| **Work** | The space of business applications: a person uses what was published, with no engine jargon. | `/work`, `/work/:slug` | Business users |
| **Cockpit** | The authoring and operating space: build Systems, run and steer them, govern them. Five cognitive axes, progressive disclosure, dark chrome (`ck-*` components). | `/create`, `/systems`, `/runs`, `/hypervisor`, `/governance`, … | Authors, operators, governors |
| **Studio** | The human surface of a business application's agent, inside Work: the person watches the run, decides at its gates and talks to the agent. The NAWA *Agent Studio* on `/work/pr-to-po` is one. | `/work/:slug` | The application's users |

`Work ↔ Cockpit` is permission-gated navigation, not a visual mode toggle;
both share workspace identity, canonical ids, audit and deep links.

Retired words — never on screen, never in a class name: **Desk**, **Board**
(they named the Studio during the PR to PO build-up and made it read as three
surfaces), **workflow** / **pipeline** (say Flow), **job** (say Run),
**HITL** as a label (say Human approval). A client's own noun stays theirs:
NAWA WE's *IT Service Desk* is a department, allow-listed where it appears.

Objects a person manipulates, and their primary UI:

| Object | Meaning | Primary UI |
| --- | --- | --- |
| `Workspace` | Tenant boundary, membership, mode, data isolation | `/workspace`, workspace picker |
| `Capability` | Business capability blueprint | `/capabilities` |
| `System` | Configured executable agentic system | `/systems`, `/systems/:id` |
| `Skill` | One unit of work with a defined input and output; a published ML model is one (`ml_models.published_skill_id`) | `/skills`, Data & Models |
| `Dataset` / `Model` | The data plane: what a System's runs produced (`system_id`, from the run) and, once published, a Skill. One Build entry, **Data & Models**; `/data` and `/models` stay distinct routes | `/data`, `/models` |
| `Experience` | A business application: a no-code UI assembled from published Systems | `/create/apps` (author), `/work/:slug` (use) |
| `Binding` | A stable link from an app action to one published System version and its contract | Experience editor |
| `Run` | Execution evidence and runtime ledger | `/runs`, `/observability`, `/tasks` |
| `Knowledge` | Collections, context and vectorized evidence | `/knowledge`, `/steering/contexts` |
| `Review Queue` | Human validation before policy or knowledge changes | `/steering/review-queue`, `/hypervisor` |
| `Connector` | External intake or integration surface (SharePoint, SFTP, SAP HANA, MCP, RPA) | `/resources`, `/connectors/*` |
| `Governance` | Access, audit, presets and platform control | `/governance/*`, `/presets` |
| `Tier` | Named model quality level: `fast`, `balanced`, `strong`. Distinct from retrieval lanes (`fast` / `balanced` / `deep`). | `/resources` (Model routing) |
| `Model routing` | Policy that turns a tier into the provider and model for a turn. Order: explicit → System pin → workspace tier → workspace default → global default, then `allowed_models`. | `/resources`, chat trail |
| `Chat execution` | Which runtime answers `/chat`: classic, hybrid (percentage), or agentic by default. Managed setting; not a generic PATCH. | `/workspace` (general) |

An Experience is **authored**. A Workspace App package is **installed**. An
Integration is **connected**. Mixing the three words on screen is a bug.

## 3. Two product layers

- **Systems** — the intelligence layer: Flows, Runs, bindings, governance.
  The engine stays System-centric (`System → Capability → Skill → Knowledge → Flow`).
- **Experience** — the application layer on top: end users consume published
  Systems through business applications on `/work`; authors compose them in
  the Cockpit (`/create`).

Flags: `settings.features.experience_v1` enables the Work/runtime contract;
`settings.features.experience_studio_v1 = false` keeps Work active while
withholding authoring (absent, it inherits `experience_v1`). Implementation
baseline 2026-08-14, migrations `087`–`094`; "integrated" is not a production
acceptance claim — that takes a SHA-bound canary artifact from the deployed
build.

### 3.1 Three lifecycles that must not collapse

```
Experience:    ExperienceDraft → Release (immutable) → Deployment (Pilot | In service)
Flow:          Draft → Published pointer (flow_publication_v1) — the executable graph
Workspace App: Blueprint plan → apply / receipts → runtime authority (Lot 9)
```

- **Flow publish** makes a System executable. It does not put an application in users' hands.
- **Experience release** freezes identity, pages, the bindings the document references (published Flow versions + contract hashes), access, languages, theme and the certified renderer version. Rollback is atomic to a previous release.
- **Lot 9 install** puts a packaged Workspace App into a tenant. It neither authors an Experience nor publishes a Flow.

A published Flow may generate a **System Home** (usage page), publishable as-is,
customised or folded into a wider Experience. It is still not a Workspace App
package.

### 3.2 Binding

The primitive between an Experience action and a System: a stable key
(`procurement.pr_to_po.run`), locked onto **one published Flow version** and
its contract (schemas + hashes). Draft graphs are never binding targets;
updating a System inside an app is an explicit author action. On screen the
object is a **Binding** / **Liaison**; `SystemBinding` stays internal.

The live runtime never resolves a mutable binding: `/work` invokes the exact
binding snapshot in the selected immutable Release (exact `SystemVersion`,
ingress and contract hashes). Retargeting or deleting the authoring binding
cannot modify an already deployed application. A binding invoke tags
`input_ref._ingress.adapter.origin = "experience:{release_slug}"` and records
Experience, Release, Deployment, channel, binding, page and component
provenance; `GET /api/v1/runs?origin=experience:{slug}` filters on it.

### 3.3 No-code document contract

The Cockpit's Experience editor stores a constrained, accessible document, not
browser code: pages and stable component ids form the route/DOM outline
(absolute positioning rejected); certified components cover content,
forms/actions, results, tables, KPI, queues, feeds, maps and agendas;
`dataBinding: { source: "run-output", componentId, selector }` projects a
previous result; `queryBinding: { source: "system-binding", bindingKey, input,
selector }` executes only on an explicit user action through the
Release-scoped `/work` API (no free URLs, no auto-run); `afterSuccess` is a
closed catalogue; localized content uses `{ "$i18n": key, "fallback": text }`
and ready-check requires every declared language; file fields upload through
the governed ingestion endpoint and submit a completed `document_id`.

The renderer registry is append-only: releases from migrations `088`/`089`
keep `certified-components-0.1.0`, every new Release pins
`certified-components-0.2.0`, both stay routable, and an unknown pin fails
closed before any `live_href` redirect.

### 3.4 Studio — the agent's human surface

A Studio is a client of the server's `Run`, never a second runtime:

- it starts the run through the Experience binding (`POST /work/{slug}/bindings/{key}/runs`);
- it follows `checkpoints` and `skill_invocations`, shows every call the server made verbatim;
- it decides through the canonical human approval (`POST /runs/{id}/hitl`) — the gate card and the chat write dialogue share that one path;
- it never calls an MCP server or composes a write body in the browser; the guardrails it shows ride the run input and the server blocks before the network.

Reference implementation: `frontend-ng/src/app/features/experience/work/pr-to-po-studio.component.ts`,
behavioural contract `frontend-ng/e2e/tests/18-nawa-agent-studio-canary.spec.ts`.

### 3.5 Governance and audit

Experience lifecycle writes to the existing `AuditLog`: `experience.created`,
`experience.draft_saved`, `experience.released`, `experience.deployed`,
`experience.rolled_back`, `experience.deleted`, `experience.binding.invoked`,
`experience.binding.retargeted`. Read them with
`GET /api/v1/audit?event_type_prefix=experience.` or
`GET /api/v1/experiences/audit` (same store, same `audit_log.read` authority).
`/governance/workspace-apps` remains Lot 9 install governance.
`PUT /api/v1/workspaces/{slug}/apps` is legacy enablement for installed
packages: do not delete it, do not author Experiences through it.

`GET /api/v1/work` is the sole launcher catalogue, filtered server-side by
Release access, deployment audience and the member's role/groups (an entitled
Pilot precedes Live for that member). Viewer/business roles receive the public
projection; contributor/reviewer/admin/owner roles enter the Cockpit.

## 4. Where things live — client mappings

### Andritz

| Need | Object | UI route | API prefix | Status |
| --- | --- | --- | --- | --- |
| Sourced business research | `Workbench` | `/chat` | `/api/v1/chat` | `canonical` |
| Customer and PDR operations | `Workbench` | `/client360` | `/api/v1/client360` | `canonical` |
| Expert interview planning and capture | `Workbench` | `/systems/:id/capture`, `/knowledge/capture` | `/api/v1/knowledge-capture` | `canonical` |
| Secure external file intake | `Connector` | `/connectors/sftp`, `/deposit/:accessId` | `/api/v1/sftp`, `/api/v1/deposit-links` | `canonical` / `public-external` |
| Workspace access and reviewer roles | `Governance` | `/governance/access`, `/workspace/:slug/access` | `/api/v1/iam` | `canonical` |
| Files waiting for validation | `Review Queue` | `/connectors/sftp` staging queue | `/api/v1/sftp/deposits` | `canonical` |
| Knowledge base collections and ingestion | `Knowledge` | `/knowledge` | `/api/v1/documents` | `canonical` |
| Execution traceability | `Run` | `/runs/:id` | `/api/v1/runs` | `canonical` |
| Recreate the workspace pattern elsewhere | `Workspace` | `/governance/blueprints` | `/api/v1/blueprints` | `canonical` |

### NAWA — PR to PO

| Need | Object | UI route | API prefix | Status |
| --- | --- | --- | --- | --- |
| Run the procurement agent, decide at its gate, talk to it | `Experience` (Studio) | `/work/pr-to-po` | `/api/v1/work/pr-to-po` | `canonical` |
| SAP reads and writes | `Connector` (MCP) | `/connectors/mcp` | `/api/v1/mcp` | `canonical` — writes only through `connectors/mcp/write.py`, flag `sap_write_unsealed` |
| The agent's graph | `System` | `/systems/:id/flow` | `/api/v1/systems` | `canonical` |
| Pending human approvals | `Review Queue` | `/work/pr-to-po` gate | `/api/v1/work/pr-to-po/validations`, `/api/v1/runs/{id}/hitl` | `canonical` |

### SENTINEL-CI

| Need | Object | UI route | API prefix | Status |
| --- | --- | --- | --- | --- |
| Ministerial cockpit and daily briefing | `Workbench` | `/hypervisor/mission-room/cockpit`, `/hypervisor/mission-room/briefing` | `/api/v1/mission-room/cockpit`, `/api/v1/mission-room/briefing` | `canonical` |
| Open intelligence and RSS weak signals | `Run` | `/hypervisor/mission-room/presse`, `/hypervisor/mission-room/veille`, `/intelligence` | `/api/v1/mission-room/news`, `/api/v1/intelligence` | `canonical` |
| Strategic project pilotage | `System` / `Workbench` | `/hypervisor/mission-room/pilotage`, `/hypervisor/mission-room/projets`, `/systems` | `/api/v1/mission-room/projects`, `/api/v1/systems` | `canonical` |
| Territorial action map | `Workbench` | `/hypervisor/mission-room/strategie` | `/api/v1/mission-room/map` | `canonical` |
| Draft cabinet instructions | `Review Queue` | `/hypervisor/mission-room/decisions` | `/api/v1/mission-room/decisions`, `/api/v1/mission-room/actions/draft` | `canonical` |
| Recreate the demo workspace elsewhere | `Workspace` | `/governance/blueprints` | `/api/v1/blueprints` | `canonical` |

SENTINEL-CI is a workspace pattern, not a hardcoded fork: workspace
`mode=demo`, settings, seeded Capabilities/Skills, System
`flow_definition.variant` and the Mission Room API carry the demo. The
workspace is anchored on Côte d'Ivoire (perimeter: Côte d'Ivoire, West Africa,
the Sahel, the Gulf of Guinea); the News Lab prefers African public RSS feeds
and surfaces source health before demo fallback content. `workspace_app_shell
= "immersive"` hides the standard chrome only for `/hypervisor/mission-room/:view`;
auth, audit, IAM, chat overlay, workspace switch and blueprint export stay
platform-governed.

### Chat orchestration — default baseline vs industrial opt-in

The transverse workspace chat is a real, inspectable `System` in every
workspace (variant `chat_transverse_v1`, `ensure_workspace_chat_system_default`
in `backend/app/services/systems/bootstrap.py`).

| Layer | Who gets it | Answer policy | Source policy highlights |
| --- | --- | --- | --- |
| Universal default | every workspace (`family=generic`, the showcase) | `default_answer_policy()` — `precise_fact` / `summary` / `comparison` / `insufficient_context` | `require_citations`, `preserve_user_terms`, `preserve_reference_types=[document_name, part_number, identifier]` |
| Industrial opt-in | `family in {andritz, industrial}` | `industrial_answer_policy()` — adds `project_summary` / `transversal_inventory` / `equipment_detail` | adds `prefer_exact_references`, `reject_cross_project_sources`, `project` in `preserve_reference_types`, `require_project_code_match` |

Same retrieval funnel (hybrid dense+sparse, C-HAH, MMR, candidate headroom,
optional Deep Search), same flow nodes; only answer and source policies differ.
Andritz stays byte-identical (migration `046_andritz_voice_capture_overrides`);
the showcase demonstrates the baseline — `docs/showcase-workspace.md`,
`docs/showcase-notices-knowledge-guide.md`.

## 5. API stability and compatibility

| Status | Rule |
| --- | --- |
| `canonical` | Preferred contract for new frontend and external integration work. |
| `compatibility` | Still active; not for new surfaces. Must point to a canonical successor. |
| `deprecated` | Backward-compatible alias with deprecation headers and a sunset target. |
| `public-external` | Not behind the Agentium JWT; protected by its own scoped token or password flow. |
| `internal` | Operational/system endpoint; not a product surface. |

| Legacy surface | Successor | Notes |
| --- | --- | --- |
| `/api/v1/agents` | `/api/v1/systems` | Emits `X-Deprecated`, `Sunset`, `Link`. |
| `/api/v1/traces` | `/api/v1/runs` | Emits `X-Deprecated`, `Sunset`, `Link`. |
| `/api/v1/settings` | `/api/v1/presets` | Compatibility proxy over workspace-default presets. |
| `/api/v1/documents/list` | `/api/v1/documents/collections` + collection document routes | Retained for older document views. |
| `/api/v1/documents/collections/{collection_name}` delete by name | `/api/v1/documents/collections/{collection_id}` | Retained while the collection-ledger migration completes. |

## 6. Navigation contract and the alignment rule

The frontend source of truth is `frontend-ng/src/app/core/navigation.catalog.ts`:
each surface declares its lens (`Hypervisor`, `Build`, `Operate`, `Steer`,
`Govern`), its object (one of §2), its scope (`workspace`, `capability`,
`system`, `run`, `admin`, `public`), its primary API prefix, its stability and
audience. The backend source of truth is
`backend/app/services/surface_catalog.py`, exposed via `/api/v1/catalog/endpoints`.

**No new route ships unless it is represented in both** the backend surface
catalog and, when it has a UI, the frontend navigation catalog. Every shipped
surface maps back to an Agentium object; a client workspace may be the first
target, never the shape of the platform.

Workspace blueprints (`/governance/blueprints`, `/api/v1/blueprints/*`) export
structure and configuration only — Systems, Capabilities, Contexts, IAM
flags, presets, Knowledge collection metadata; never members, credentials,
Secure Deposit files, raw documents, vectors, runs or audit logs. See
`docs/workspace-blueprints.md`.

## 7. Quality gates

Playwright canaries for `/work`, the Cockpit's Experience editor and the NAWA
Studio are part of the iteration gate alongside System360 and protected-runner
canaries. `E2E_EXPERIENCE_CANARY=1` and `E2E_NAWA_STUDIO=1` are explicit
acceptance contracts: a missing enabled workspace, compatible published
ingress or visible deployed app fails the run rather than skipping it.

```bash
cd frontend-ng
E2E_EXPERIENCE_CANARY=1 E2E_NAWA_STUDIO=1 \
  E2E_USERNAME=... E2E_PASSWORD=... E2E_EXPECTED_SHA=<40-hex> \
  npx playwright test \
    e2e/tests/16-experience-work-canary.spec.ts \
    e2e/tests/17-experience-studio-canary.spec.ts \
    e2e/tests/18-nawa-agent-studio-canary.spec.ts \
    --project=chromium
```

`scripts/run-iteration-canaries.sh <sha>` enables these specs and writes their
JSON evidence; it accepts only a root-owned, clean checkout whose HEAD equals
the deployed SHA. Pilot/Live mutations stay a separate explicit canary mode.

## 8. Honest boundaries

- Advanced multi-tenant/RBAC: isolation tested; custom roles and marketplace out of short-term scope.
- Preview is effect-free; the Cockpit's role/group simulation is advisory and never borrows an identity or replaces the server-side access check.
- Custom domains and arbitrary components are not part of the certified no-code runtime; a custom component takes the WorkspaceAppPackage/Git/CI/SBOM path.
- `candidate_config_sha256` stays on the IAM decision plane. Runs `origin=` has no JSON index; very large workspaces may need one after measurement.
- Chat / Client360 / capture stay id-resolved during dual-run; Mission Room rails prefer bindings when `experience_v1` is on. NAWA Lot 9 packages stay on their binding until an explicit cutover.
- Offline what-if simulation on a replayed run (E6) is still open. For the state over time: [`vague-e-plan.md`](./vague-e-plan.md), [`production-demo-map.md`](./production-demo-map.md), [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md).
