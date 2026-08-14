# Agentium Experience platform

Flag: `settings.features.experience_v1` (opt-in). Off → existing Studio navigation is unchanged.

Implementation baseline: 2026-08-14, migrations `087` through `092`. Lots 0–8 are integrated behind the flag; the certified component catalogue remains intentionally closed.

This document is the architecture for the **Experience** concept (on screen: **Application métier** / **Business application**). It does not replace Lot 9 Workspace Apps or Flow publication.

## Three objects that are not the same thing

| Object | Who it is for | What it is |
| --- | --- | --- |
| **Experience** (Application métier) | Authors in Studio; end users on `/work` | A no-code business UI assembled from **published** Systems. One product noun on screen; the internal type is `Experience`. |
| **WorkspaceAppPackage** | Operators / platform | A content-addressed, versioned package (`app_id` + SemVer + `manifest_digest`) **installed** into a workspace (Chat, Client360, Mission Room, …). Lifecycle is Lot 9: plan → apply → receipts. |
| **Integration** | Operators | A connector to an external system (SharePoint, SFTP, SAP HANA, RPA). Lives under Govern → Connectors. Not an application. |

An Experience is **authored**. A Workspace App is **installed**. An Integration is **connected**. Mixing the three words on screen is a bug.

The engine stays **System-centric** (`System → Capability → Skill → Knowledge → Flow`). End users stay **application-centric** (`/work/:appSlug`, no engine jargon).

## Three lifecycles that must not collapse

```
Experience:   ExperienceDraft → Release (immutable) → Deployment (Pilot | In service)
Flow:         Draft → Published pointer (flow_publication_v1) — executable graph
Workspace App: Blueprint plan → apply / receipts → runtime authority (Lot 9)
```

- **Flow publish** makes a System executable. It does **not** put an application in users’ hands.
- **Experience release** freezes identity, pages, only the bindings actually referenced by the document (published Flow versions + contract hashes), access, languages, theme, and the certified renderer version. Rollback is atomic to a previous release.
- **Lot 9 install** puts a packaged Workspace App into a tenant. It does **not** author an Experience and it does **not** publish a Flow.

A published Flow may generate a **System Home** (usage page). That page can be published as-is, customised, or folded into a wider Experience. It is still not a WorkspaceAppPackage.

## SystemBinding

The primitive between an Experience action and a System:

- Stable key (`expenses.submit`).
- Locked onto **one published Flow version** and its contract (schemas + hashes).
- Draft graphs are never offered as binding targets.
- Updating a System inside an app is an explicit author action, not a silent float.

On screen the object is a **Liaison** / **Binding**. `SystemBinding` stays internal.

The live runtime never resolves a mutable `SystemBinding`. `/work` invokes the exact binding snapshot in the selected immutable Release, including the exact `SystemVersion`, ingress and contract hashes. Retargeting or deleting the authoring binding cannot modify an already deployed application.

## No-code document contract

Studio is no-code by default and stores a constrained, accessible document rather than executable browser code:

- Pages and stable component ids form the route/DOM outline. Absolute positioning is rejected.
- Certified components cover content, forms/actions, results, tables, KPI, queues, feeds, maps and agendas.
- `dataBinding: { source: "run-output", componentId, selector }` projects a previous component result.
- `queryBinding: { source: "system-binding", bindingKey, input, selector }` executes only on an explicit user action through the Release-scoped `/work` API. Free URLs and auto-run queries are forbidden.
- `afterSuccess` is a closed catalogue: stay, focus the result, reset the form, or navigate to an existing page id.
- Localized content uses `{ "$i18n": key, "fallback": text }` plus document dictionaries. Ready-check requires every declared language.
- File fields upload through the governed document ingestion endpoint and submit only a completed `document_id`.

The Advanced surfaces expose hashes, schemas and the Flow/System contracts; they do not create a second document model or allow arbitrary JavaScript.

## Two spaces, one product

| Space | Route | Audience | Chrome |
| --- | --- | --- | --- |
| **Work** | `/work` | Business users | Light, no engine jargon |
| **Studio** | `/create`, `/systems`, … | Authors / operators | Cockpit (dark by default) |

Bridges: « Modifier dans le Studio » / « Voir l'application ». Flow Builder scratchpad (`/orchestration`) is a Studio facet, reachable via ⌘K when `experience_v1` is on — not a top-level Create item.

`GET /api/v1/work` is the sole launcher catalogue. It is filtered server-side by Release access, deployment audience and the current member's role/groups. An entitled Pilot takes precedence over Live for that member; clients never reproduce audience logic. Viewer/business roles only receive the public projection, while contributor/reviewer/admin/owner roles can enter Studio. Contributors author; reviewers/admins release and deploy.

## Recommended lot order

Ship in this order; later lots assume the primitives of earlier ones.

0. **Foundation** — flag, lexicon, Create nav, `/create` hub, this doc. No backend.
1. **SystemBinding** — persist the primitive; only published versions are selectable.
2. **ExperienceDraft + Studio editor** — pages tree, preview, action inspector (readable binding; JSON under Advanced).
3. **System Home** — auto page from a published Flow.
4. **`/work` shell** — business launcher; zero Studio chrome.
5. **Studio inventory** — drafts, releases, audiences (`/create/apps`).
6. **New-app wizard** — templates + binding step.
7. **Release + deployment** — ready-check, immutable release, Pilot / In service, atomic rollback.
8. **Certified renderer** — lock renderer version on the release; serve `/work`.

NAWA and other Lot 9 packages stay on their current binding until a later, explicit cutover. Do not reuse Lot 9 install APIs for Experience drafts.

## Governance and audit

Experience lifecycle writes to the existing audit store (`AuditLog`). Queryable types:

| Event | When |
| --- | --- |
| `experience.created` | Draft resource created |
| `experience.draft_saved` | Draft pages / binding keys changed |
| `experience.released` | Immutable release created |
| `experience.deployed` | Pilot or In-service pointer moved |
| `experience.rolled_back` | Channel pointer restored |
| `experience.deleted` | Draft deleted (blocked while live) |
| `experience.binding.invoked` | Binding started a published Run |
| `experience.binding.retargeted` | Binding snapshot refreshed to the current published contract |

Filter the existing list:

- `GET /api/v1/audit?event_type_prefix=experience.`
- `GET /api/v1/experiences/audit` — same store and the same `audit_log.read` authority (reviewer+). Not a second ledger.

`/governance/workspace-apps` remains Lot 9 install governance. Do not mix Experience events into that console.

## Hypervisor / runs origin

Binding invoke tags `input_ref._ingress.adapter.origin = "experience:{release_slug}"` and records Experience, Release, Deployment, channel, binding, page and component provenance.

`GET /api/v1/runs?origin=experience:{slug}` filters that JSON path (no extra index). Large workspaces scan the workspace run list.

## Legacy workspace apps

`PUT /api/v1/workspaces/{slug}/apps` is Lot 9 / legacy enablement for installed Workspace App packages. Experience draft → release → deploy is the source of truth for business applications. Do not delete the legacy endpoint; do not author Experiences through it.

## Quality gates

Playwright canaries for `/work` and Studio are part of the default iteration gate alongside System360 and protected-runner canaries. They skip, rather than fail, when the feature flag is off; `/work` also skips when its server-filtered catalogue is empty.

```bash
cd frontend-ng
E2E_EXPERIENCE_CANARY=1 \
  E2E_USERNAME=... E2E_PASSWORD=... \
  E2E_EXPECTED_SHA=<40-hex> \
  E2E_EXPERIENCE_EVIDENCE=/tmp/experience.json \
  npx playwright test \
    e2e/tests/16-experience-work-canary.spec.ts \
    e2e/tests/17-experience-studio-canary.spec.ts \
    --project=chromium
```

`scripts/run-iteration-canaries.sh <sha>` enables these specs and writes their JSON evidence by default. Traces stay off because the canaries use a live principal.

## Deliberate boundaries and follow-ups

- `candidate_config_sha256` remains on the IAM decision plane, not on Experience rows.
- Runs `origin=` has no JSON index; very large workspaces may need one after measurement.
- Preview is effect-free. A later governed “preview as role/group” projection may be added, but it must use server-computed effective access rather than impersonation in the client.
- Custom domains and arbitrary custom components are not part of the certified no-code runtime. A custom component still requires the WorkspaceAppPackage/Git/CI/SBOM path.
- Chat / Client360 / capture stay id-resolved during dual-run. Mission Room rails prefer bindings when `experience_v1` is on.
- First API Publish of an 089 seed-shaped contract auto-retargets seed bindings. Author bindings stay locked.
