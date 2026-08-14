# Agentium Experience — backlog (Lots 0–8)

Version: 2026-08-14. Flag: `settings.features.experience_v1`.

Architecture: [`agentium-experience-platform.md`](./agentium-experience-platform.md). Mockups: [`docs/design/experience/`](./design/experience/README.md).

Stories are compact on purpose. Lots 0–8 are now implemented behind the flag. This document is the acceptance ledger; future extensions must not weaken the immutable Release, server-side audience or certified-renderer contracts.

## Lot 0 — Foundation — delivered

Original Lot 0 boundary: nav, lexicon, hub and docs only. Backend, `/work` and the Studio editor arrived in the following delivered lots.

| ID | Story |
| --- | --- |
| US-0.1 | Build menu becomes **Créer** (Applications métier, Systems, Knowledge) + **Bibliothèque avancée**. Scratchpad via ⌘K only. Flag off → menu unchanged. |
| US-0.2 | Lexicon + `experience` i18n domain: Application métier, Liaison, Release, Pilote, En service + `concept.*`. |
| US-0.3 | Hub `/create` (intent cards, composer stub, Reprendre empty, articulation strip). `/create/apps` inventory stub. Flag off → redirect `/systems`. |
| US-0.4 | Architecture + this backlog. |

## Lot 1 — SystemBinding — delivered

| ID | Story |
| --- | --- |
| US-1.1 | Persist `SystemBinding` (stable key, published Flow version, schema hashes). Drafts are not selectable. |
| US-1.2 | Readable inspector: Appelle / Entrées / Confirmation / Après succès / Si indisponible. JSON + hashes under Advanced. |
| US-1.3 | Explicit “update System in this app”; no silent float to a newer published version. |

## Lot 2 — ExperienceDraft + Studio editor — delivered

| ID | Story |
| --- | --- |
| US-2.1 | `ExperienceDraft` resource, distinct from Flow draft and from Lot 9 install. |
| US-2.2 | Studio editor chrome: page tree, canvas preview, action inspector bound to SystemBinding. |
| US-2.3 | “Voir l'application” preview does not require a release. |

## Lot 3 — System Home — delivered

| ID | Story |
| --- | --- |
| US-3.1 | Publishing a Flow generates a usage page (System Home) from the published contract. |
| US-3.2 | Author can publish the home as-is, customise it, or insert it into a wider Experience. |

## Lot 4 — `/work` launcher — delivered

| ID | Story |
| --- | --- |
| US-4.1 | `/work` lists In-service (and entitled Pilot) Experiences. No Studio jargon. |
| US-4.2 | `/work/:appSlug` runs the certified renderer for that deployment. Light chrome. |
| US-4.3 | “Modifier dans le Studio” is the only path back to authoring. |

## Lot 5 — Studio inventory — delivered

| ID | Story |
| --- | --- |
| US-5.1 | `/create/apps` lists drafts, generated homes, releases, audiences. |
| US-5.2 | Lifecycle strip: Brouillon → Vérifications → Release → Pilote → En service. |

## Lot 6 — New application wizard — delivered

| ID | Story |
| --- | --- |
| US-6.1 | Step 1: pick a template (or start from a System Home). |
| US-6.2 | Step 2: bind actions to published Systems (Lot 1 picker). |

## Lot 7 — Release and deployment — delivered

| ID | Story |
| --- | --- |
| US-7.1 | Ready-check then immutable Release (pages + bindings + access + i18n + theme + renderer version). |
| US-7.2 | Deploy Pilot (limited audience) then In service. |
| US-7.3 | Atomic rollback to a previous Release. |

## Lot 8 — Certified renderer — delivered

| ID | Story |
| --- | --- |
| US-8.1 | Renderer version is a release pin, not “whatever the SPA currently ships”. |
| US-8.2 | `/work` serves only that pin. Uncertified components cannot be added to a release. |
| US-8.3 | Playwright canaries (`E2E_EXPERIENCE_CANARY=1`): `/work` launcher and `/create` Studio. Included in the default iteration gate; skip when the flag is off or `/work` has no deployed app. |

## Deliberate boundaries

- Lot 9 Workspace App install. NAWA dual-run (binding + inventory pointer to `/nawa`) is Lot 7; rewriting WE pages as certified components is still later.
- Changing Flow publication (`flow_publication_v1`).
- Arbitrary JavaScript, free-form URLs and unreviewed custom components in the no-code document.
- Custom domain provisioning and client-side role impersonation.

## Lot 7 leftovers (NAWA + reconciliation cutover)

- **PO↔Invoice** is seeded in-repo by `089_publish_nawa_recon` as a published 5-node contract (`spreadsheet_table_extract_v1` + `invoice_document_extract_v1` + `line_items_reconcile_v1`). 088/089 bind `rapprochement.po.factures` and deploy Experience `rapprochement-po-factures` in **pilot**. Demo tenants that already have the published System are left as-is.
- `089` publishes 065's Password Reset when it still has a draft/`flow_definition` and no published pointer, then retries `nawa.password_reset`.
- NAWA custom UI (`/nawa`) stays the full helpdesk. Experience `nawa` remains the inventory pointer (`theme.live_href = /nawa`). Certified password-reset form is Experience `nawa-reset` on `/work/nawa-reset`.

## Lot 8 leftovers (Andritz / Sentinel / Octocity / Mission Control dual-run)

Migrations `090_xp_dual_run` + `091_xp_sentinel_certified`. Live UIs stay on their existing routes (`theme.live_href`).

- **Andritz chat / Client360 / capture** stay resolved by id. Bindings are seeded for Studio only.
- **FSE** (`andritz.fse`) prefers the binding when the flag is on.
- **Mission Room rails** (cockpit, carte, agenda, presse/sécurité/réputation, arbitrages) prefer `sentinel.*` / `octocity.*` / `mission.*` bindings when the flag is on. Flag off keeps the variant match.
- **Certified widgets** `map_panel`, `agenda_panel`, `intelligence_feed`, `decision_queue` are in the catalog. SENTINEL / Octocity / Mission Control seed pages use them. AYA stays a callout to the immersive shell.
- **089 seed drift**: the first API Publish of a seed-shaped contract (`execution_contract` without `contract_sha256`) auto-retargets seed-created bindings (`created_by` starts with `system:`). Author-created bindings do not float.
- Bindings are skipped when the System has no `published_flow_version_id`.
- **Activate**: `alembic upgrade` through `092`, then `settings.features.experience_v1 = true`.
