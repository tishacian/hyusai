# Agentium simplification implementation progress

Plan source: `docs/agentium-simplification-audit-2026-09-11.md`

This ledger records the product-wide implementation queue. Each slice is reviewed, tested, and committed independently. The existing user-owned `frontend-ng/proxy.conf.json` change is excluded from every slice.

**Overall simplification status: reopened after the 2026-09-15 live-product audit.** The original 15 P0–P2 items remain delivered, but the live audit found a second class of truth and coherence defects that the earlier route-level release gates did not cover. Most importantly, a System could show workspace-wide request metrics as its own, label itself Ready from status alone, and default a field-service Q&A objective to the runnable but semantically wrong Answer Quality Audit capability. The product is not complete until the queue below is closed with real-browser evidence.

## 2026-09-15 corrective implementation queue

| Priority | Slice | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P0 | Canonical System Overview | Implemented, verification in progress | New `/systems/{id}/overview` read model scopes readiness, publication, Runs, latency, and quality to one System; missing evidence stays `not_measured`; frontend removes false Yield and status-only Ready claims. Backend contracts 11/11, focused frontend contracts 11/11, production Angular build pass. |
| P0 | Correct simple-Builder semantics | Implemented, verification in progress | Simple Build selects only the bound `intelligent_qa` contract, never the first runnable catalog row; switching to Flow persists `draft`; commercial tier labels and enterprise-tier copy removed. Existing Systems are not silently rewritten. |
| P0 | Prove create → publish → run → inspect | In progress | Recreate or explicitly rebind the pump demo System, run the real Operator Runner, verify Overview/Runs/Invocations/Payloads against the published version, and capture browser evidence. |
| P0 | Runtime failure recovery | Planned | Replace generic FAILED/unsupported outcomes with a task-level explanation, preserve input, and route the operator to the exact Builder/model/knowledge fix. |
| P1 | Remove dead default surfaces | Planned | Delete the legacy Overview dashboard code after one compatibility window; eliminate remaining global metric calls and canary-only System 360 chrome from the default product profile. |
| P1 | Core navigation and route inventory | Planned | Hide duplicate, demo, and incomplete routes from default navigation; keep only Ask, Knowledge, Build, Runs, Settings, and contextual advanced links. |
| P1 | Catalog and seed reduction | Planned | Keep commercial fields out of normal APIs/UI and move demo/client-specific Capabilities and Systems to opt-in fixture packs. |
| P2 | Responsive, accessibility, and EN/FR proof | Planned | Re-run the authenticated desktop/mobile/light/dark matrix for the corrected System flow, including keyboard and screen-reader names. |

Claude delegation note: two Opus-medium dispatches were attempted through the installed `claude-delegate` relay. The local authenticated Team session currently resolves `opus` to `claude-opus-5`, which the provider rejects before the first token with a model-not-found/access error. No Claude-authored code is claimed in this corrective queue; Codex continued the P0 slice rather than substituting another model silently.

| Order | Slice | Owner | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | P0.1 + P0.3: Ask default entry and four-item primary navigation | Claude, reviewed and landed by Codex | Complete | 17 focused tests; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 2 | P0.4: remove unsupported pricing, marketplace, and certification UI | Claude, reviewed and landed by Codex | Complete | 33 focused tests; commercial-UI source contract; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 3 | P0.5: fail closed for catalog-only, stub, and unbound runtimes | Codex | Complete | Apps API and UI expose wired entries only; publication, run ingress, and System Builder block non-bound Skills; 67 backend and 3 focused frontend tests pass |
| 4 | P0.2 + P1.1: first-run model setup and one model settings surface | Codex | Complete | Settings owns one guided provider/model form; the API validates credentials and live model availability before one atomic save; failed questions return and retry automatically; safe technical details stay collapsed; 68 backend and 57 focused frontend tests pass |
| 5 | P1.2 + P1.3: progressive Knowledge and Build flows | Codex | Complete | Knowledge now defaults to upload → processing/recovery → Ask, with collections/search/capture behind Advanced; Build defaults to desired result + knowledge, selects only a runnable capability automatically, reveals technical controls on demand, and fails closed when none is runnable; 38 focused tests and all frontend/compiler/compliance guards pass |
| 6 | P0.6 + P1.4 + P1.5: golden path, deployed Work consolidation, and legacy redirects/docs | Codex + delegated Claude Opus, reviewed by Codex | Complete | Work remains the deployed-experience launcher; Tasks resolve inside Runs; Apps and Missions are absent from user navigation; legacy settings/agents/traces/playground routes redirect canonically; the root README describes Agentium. The real EN/FR journey passes model setup → unique upload → cited answer → rendered PDF evidence → forced connection failure → cited retry, including repeated runs against a populated store. |
| 7 | P2: accessibility, performance, activation telemetry, and visual cleanup | Codex + delegated Claude Opus, reviewed by Codex | Complete | The authenticated real-browser matrix passes on Ask, Settings, Knowledge, Build, and Runs across EN/FR, light/dark, reduced motion, desktop, 456 px, and 320 px. Production performance, activation telemetry, and Cockpit visual/contrast contracts also pass. |

## P2.2 performance and perceived speed

- The optimized initial bundle is 854,312 bytes raw, down from 1.88 MB, and passes the unchanged 1 MB production error budget. The complete 7,481-key translation catalogue loads after the shell and Ask copy; chart registration loads only with a chart-bearing lazy surface.
- `npm run check:performance` builds production with esbuild statistics and fails closed if the initial graph exceeds 1,000,000 bytes, Chart.js or the complete catalogue becomes eager, or Ask, Settings, Knowledge, Build, or Runs stops being route-lazy or exceeds its explicit route-entry budget.
- Heavy Knowledge capture remains behind the explicit lazy `/knowledge/capture` route and each capture implementation remains deferred inside its router.
- The opt-in EN/FR golden path now records privacy-safe timings for sign-in to usable Ask, provider readiness, question to first cited answer, and citation to visible source preview. The artifact contains locale and millisecond measurements only.

Evidence: the optimized production build and deterministic bundle gate pass at 854,312 initial bytes. The live EN/FR journey passes the configured readiness, first cited answer, and source-preview budgets and retains privacy-safe timing artifacts.

## P2.4 core visual cleanup

- `/settings` is now a focused model-setup surface. The broader model, connector, and App portfolio remains on Resources instead of competing with first-run setup.
- Shared object headers are flat, opaque, and token-driven rather than gradient glass cards. Generic section-header icons no longer sit in decorative tiles.
- Knowledge uses smaller upload/dialog icons, a flat advanced-capture surface, a solid primary action, and an opaque dialog scrim.
- Build removes selected-card glow and decorative violet, reduces accordion icon tiles, and presents the simple-mode explanation as inline guidance rather than another nested card.
- Ask uses solid Cockpit surfaces for history and controls, and its context selector fits a 320 px screen. Runs actions wrap and its filters flex instead of overflowing narrow layouts.

Evidence: source-level visual regression contract plus the complete 1,545-test frontend unit suite, i18n, navigation, UI-chrome, and compliance gates. The production performance gate passes at 854,312 initial bytes, and the authenticated browser matrix passes all five core surfaces.

## P2.3 activation telemetry

The eight funnel milestones are emitted through the existing workspace-scoped `POST /audit` mechanism by one Angular service, `frontend-ng/src/app/core/product-telemetry.service.ts`. No feature component builds an audit payload of its own.

| Milestone | Audit `event_type` | Authoritative success point |
| --- | --- | --- |
| Signed in | `product.activation.signed_in` | Sign-in, inside the `loadWorkspaces()` success callback |
| Model ready | `product.activation.model_ready` | Validated `PUT /models/setup` response, and a current-workspace `GET /models/readiness` answering `ready` |
| Knowledge added | `product.activation.knowledge_added` | `upload-batch` response with `successful > 0`, in Knowledge and in chat drop-and-ask |
| First question sent | `product.activation.first_question_sent` | Chat, once the `/chat/stream` request is open |
| First answer completed | `product.activation.first_answer_completed` | Chat `done` chunk with no classified failure and non-empty text |
| Source opened | `product.activation.source_opened` | Chat, once a citation resolved to a document and its preview opened |
| Failure recovered | `product.activation.failure_recovered` | A retried chat turn, upload batch or model save that then succeeded |
| System published | `product.activation.system_published` | System Builder, when the API returned a live System |

Contract:

- **Privacy.** Details carry only `schema_version`, `milestone`, a masked route template, a navigation-catalog surface id, the UI locale, and optionally a closed-enum `recovery_kind` and a coarse `elapsed_bucket`. No prompt or answer text, filename, source title or content, credential, provider endpoint, e-mail address, raw error, identifier or arbitrary user string is ever emitted. Deduplication keys are local and never transmitted.
- **Deduplication.** "First" milestones are recorded at most once per authenticated browser session and workspace, persisted in `sessionStorage`, so a page reload cannot re-emit them. The ledger is cleared when the authenticated principal is left (sign-out or user switch) via `AuthStore.registerContextReset`; the service is started from an `APP_INITIALIZER` so that hook is always registered first. Repeatable milestones are guarded by a local occurrence key.
- **Best effort.** Emission never blocks, awaits or alters the user action; storage and transport failures are swallowed.
- **No inference.** Nothing is derived from a route visit or an optimistic click.

Evidence: 92 focused frontend tests (`product-telemetry`, `chat-panel`, `chat-workspace`, `knowledge-progressive`, `knowledge-capture`, `model-setup`, `system-builder`); Angular compiler, i18n, nav-link, UI-chrome and compliance gates pass.

## Release rules

- Preserve canonical deep links for one compatibility release.
- Keep English and French dictionaries structurally equivalent.
- Do not expose raw provider exceptions or secrets.
- Do not make catalog presence imply runtime readiness.
- Run focused tests plus navigation, i18n, UI-chrome, and Angular compiler gates where relevant.
- Do not include unrelated user changes in commits.

## Final release evidence — 2026-09-14

- `npm run check:core-release`: **pass** — 2/2 EN/FR golden journeys and 5/5 core accessibility surfaces.
- Repeated standalone golden-path execution: **pass twice consecutively** (4/4 locale runs) on an already populated workspace before the consolidated release run.
- `npm run test:unit`: **1,545/1,545 pass**.
- `npm run check:performance`: **pass**, initial bundle 854,312 bytes.
- `npm run check:i18n` and `npm run check:ui-chrome`: **pass**.
- Clean SQLite Alembic bootstrap/round-trip plus SharePoint migration contracts: **44/44 pass**.
- Grounding, citation, conversation-memory, upload, and answer-policy suites: **92/92 pass** in the focused release run; the exact-reference subset was re-run after the latency hardening and passed **63/63**.
- The broad TypeScript check still reports pre-existing typing debt across legacy test files outside this release slice; no changed P0–P2 production file appears in the filtered error output, and Angular's production compiler/build passes.
- The user-owned `frontend-ng/proxy.conf.json` change remains deliberately excluded from Agentium work.
