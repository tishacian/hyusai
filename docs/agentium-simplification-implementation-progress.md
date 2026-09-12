# Agentium simplification implementation progress

Plan source: `docs/agentium-simplification-audit-2026-09-11.md`

This ledger records the product-wide implementation queue. Each slice is reviewed, tested, and committed independently. The existing user-owned `frontend-ng/proxy.conf.json` change is excluded from every slice.

| Order | Slice | Owner | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | P0.1 + P0.3: Ask default entry and four-item primary navigation | Claude, reviewed and landed by Codex | Complete | 17 focused tests; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 2 | P0.4: remove unsupported pricing, marketplace, and certification UI | Claude, reviewed and landed by Codex | Complete | 33 focused tests; commercial-UI source contract; i18n, nav-link, UI-chrome, and Angular compiler gates pass |
| 3 | P0.5: fail closed for catalog-only, stub, and unbound runtimes | Codex | Complete | Apps API and UI expose wired entries only; publication, run ingress, and System Builder block non-bound Skills; 67 backend and 3 focused frontend tests pass |
| 4 | P0.2 + P1.1: first-run model setup and one model settings surface | Codex | Queued | Pending |
| 5 | P1.2 + P1.3: progressive Knowledge and Build flows | Codex | Queued | Pending |
| 6 | P0.6 + P1.4 + P1.5: golden path, deployed Work consolidation, and legacy redirects/docs | Codex | Queued | Pending |
| 7 | P2: accessibility, performance, activation telemetry, and visual cleanup | Codex | Queued | Pending |

## Release rules

- Preserve canonical deep links for one compatibility release.
- Keep English and French dictionaries structurally equivalent.
- Do not expose raw provider exceptions or secrets.
- Do not make catalog presence imply runtime readiness.
- Run focused tests plus navigation, i18n, UI-chrome, and Angular compiler gates where relevant.
- Do not include unrelated user changes in commits.
