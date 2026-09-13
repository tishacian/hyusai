# Agentium simplification implementation progress

Plan source: `docs/agentium-simplification-audit-2026-09-11.md`

This ledger records the product-wide implementation queue. Each slice is reviewed, tested, and committed independently. The existing user-owned `frontend-ng/proxy.conf.json` change is excluded from every slice.

| Order | Slice | Owner | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | P0.1 + P0.3: Ask default entry and four-item primary navigation | Claude, reviewed and landed by Codex | Complete | 17 focused tests; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 2 | P0.4: remove unsupported pricing, marketplace, and certification UI | Claude, reviewed and landed by Codex | Complete | 33 focused tests; commercial-UI source contract; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 3 | P0.5: fail closed for catalog-only, stub, and unbound runtimes | Codex | Complete | Apps API and UI expose wired entries only; publication, run ingress, and System Builder block non-bound Skills; 67 backend and 3 focused frontend tests pass |
| 4 | P0.2 + P1.1: first-run model setup and one model settings surface | Codex | Complete | Settings owns one guided provider/model form; the API validates credentials and live model availability before one atomic save; failed questions return and retry automatically; safe technical details stay collapsed; 68 backend and 57 focused frontend tests pass |
| 5 | P1.2 + P1.3: progressive Knowledge and Build flows | Codex | Complete | Knowledge now defaults to upload → processing/recovery → Ask, with collections/search/capture behind Advanced; Build defaults to desired result + knowledge, selects only a runnable capability automatically, reveals technical controls on demand, and fails closed when none is runnable; 38 focused tests and all frontend/compiler/compliance guards pass |
| 6 | P0.6 + P1.4 + P1.5: golden path, deployed Work consolidation, and legacy redirects/docs | Codex | In progress | Work remains the deployed-experience launcher; Tasks now resolve inside Runs; Apps and Missions were removed from user navigation; legacy settings/agents/traces/playground routes redirect canonically; the root README now describes Agentium and its supported journey. The EN/FR live golden-path gate compiles and launches with system Chrome, but the current local database lacks the documented E2E test principal, so behavioral execution stopped at a 401 before product state changed. |
| 7 | P2: accessibility, performance, activation telemetry, and visual cleanup | Codex | In progress | The five supported first-use surfaces share an opt-in EN/FR × light/dark × desktop/456/320 real-browser gate for WCAG AA, reduced motion, reflow, and visual evidence. Static compilation is enforced locally; authenticated execution still requires the documented isolated-workspace test principal. **P2.2 performance and P2.3 activation telemetry are implemented** (see below). Broader visual cleanup (P2.4) remains, so the row stays open. |

## P2.2 performance and perceived speed

- The optimized initial bundle is 854,344 bytes raw (205,310 bytes estimated transfer), down from 1.88 MB, and passes the unchanged 1 MB production error budget. The complete 7,480-key translation catalogue loads after the shell and Ask copy; chart registration loads only with a chart-bearing lazy surface.
- `npm run check:performance` builds production with esbuild statistics and fails closed if the initial graph exceeds 1,000,000 bytes, Chart.js or the complete catalogue becomes eager, or Ask, Settings, Knowledge, Build, or Runs stops being route-lazy or exceeds its explicit route-entry budget.
- Heavy Knowledge capture remains behind the explicit lazy `/knowledge/capture` route and each capture implementation remains deferred inside its router.
- The opt-in EN/FR golden path now records privacy-safe timings for sign-in to usable Ask, provider readiness, question to first cited answer, and citation to visible source preview. The artifact contains locale and millisecond measurements only.

Evidence: successful optimized production build; deterministic bundle gate and focused unit contracts pass; the live timing gate compiles and lists both locale runs. Behavioral timings still require the isolated-workspace principal noted in P0.6.

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
