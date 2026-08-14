# Agentium Experience platform

Flag: `settings.features.experience_v1` (opt-in). Off → existing Studio navigation is unchanged.

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
- **Experience release** freezes pages, bindings (published Flow versions + contract hashes), access, languages, theme, and the certified renderer version. Rollback is atomic to a previous release.
- **Lot 9 install** puts a packaged Workspace App into a tenant. It does **not** author an Experience and it does **not** publish a Flow.

A published Flow may generate a **System Home** (usage page). That page can be published as-is, customised, or folded into a wider Experience. It is still not a WorkspaceAppPackage.

## SystemBinding

The primitive between an Experience action and a System:

- Stable key (`expenses.submit`).
- Locked onto **one published Flow version** and its contract (schemas + hashes).
- Draft graphs are never offered as binding targets.
- Updating a System inside an app is an explicit author action, not a silent float.

On screen the object is a **Liaison** / **Binding**. `SystemBinding` stays internal.

## Two spaces, one product

| Space | Route | Audience | Chrome |
| --- | --- | --- | --- |
| **Work** | `/work` | Business users | Light, no engine jargon |
| **Studio** | `/create`, `/systems`, … | Authors / operators | Cockpit (dark by default) |

Bridges: « Modifier dans le Studio » / « Voir l'application ». Flow Builder scratchpad (`/orchestration`) is a Studio facet, reachable via ⌘K when `experience_v1` is on — not a top-level Create item.

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

Binding invoke tags `input_ref._ingress.adapter.origin = "experience:{binding_key}"`.

`GET /api/v1/runs?origin=experience:{key}` filters that JSON path (no extra index). Large workspaces scan the workspace run list.

## Legacy workspace apps

`PUT /api/v1/workspaces/{slug}/apps` is Lot 9 / legacy enablement for installed Workspace App packages. Experience draft → release → deploy is the source of truth for business applications. Do not delete the legacy endpoint; do not author Experiences through it.

## Quality gates (opt-in)

Playwright canaries for `/work` and Studio. They are **not** part of the default iteration deploy path (`scripts/run-iteration-canaries.sh` still runs only `11-system360-canary` and `12-protected-runner-canaries`).

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

Skip (do not fail) when `settings.features.experience_v1` is off, or when `/work` has no Pilot/In-service app visible to the principal. Traces stay off. Optional: `E2E_EXPERIENCE_CANARY=1 scripts/run-iteration-canaries.sh <sha>` after the default 11+12 specs.

## Leftovers

- `on_unavailable` is stored on `SystemBinding` and is not executed at invoke time.
- `candidate_config_sha256` lives on the IAM decision plane, not on Experience rows.
- No “Réparer les liaisons” UI on `/create/apps` (Lot 5 owns that page). Drift list + retarget are API-only: `GET /api/v1/system-bindings/drift`, `POST /api/v1/system-bindings/{key}/retarget`.
- Runs `origin=` has no JSON index.
- Chat / Client360 / capture stay id-resolved. Mission Room rails prefer bindings when `experience_v1` is on.
- First API Publish of an 089 seed-shaped contract auto-retargets seed bindings. Author bindings stay locked.
