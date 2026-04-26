# Agentium E2E tests — Vague E / E2

Playwright scaffolding covering the 4 critical flows from
`docs/vague-e-plan.md` § E2 :

| # | Flow | File |
|---|------|------|
| 01 | Auth Keycloak (login / reload / invalid creds) | `tests/01-auth-keycloak.spec.ts` |
| 02 | Chat drop-and-ask → citation chip → sources panel | `tests/02-chat-drop-and-ask.spec.ts` |
| 03 | HITL pause → Approve → resume | `tests/03-hitl-approve.spec.ts` |
| 04 | Debug Step / Continue → outcome | `tests/04-debug-step-continue.spec.ts` |
| 05 | E1.5 canonical answer guardrail | `tests/05-eval-canonical-answer.spec.ts` |

## Activation

```bash
npx playwright install chromium
```

## Running against the staging VM

```bash
# Default target is https://agentium.papai.ai (set in playwright.config.ts)
npm run test:e2e

# With UI to watch it run
npm run test:e2e -- --headed

# Single flow
npm run test:e2e -- tests/01-auth-keycloak.spec.ts
```

## Running against a local dev server

```bash
E2E_BASE_URL=http://localhost:4200 npm run test:e2e
# The config spawns `npm run start` automatically for localhost targets.
```

## Credentials and fixtures

- **User :** `alice@acme.test` / `alice-demo` (seeded by the tenant
  isolation smoke; role `workspace.owner` on workspace `acme`).
  Override with `E2E_USERNAME` + `E2E_PASSWORD` env vars.
- **PDFs (flow 02) :** generated dynamically at test runtime.
- **Systems (flows 03/04) :** generated dynamically through the
  authenticated API and cleaned up at the end of each spec.

## Current status

VM run 2026-04-25:

```bash
E2E_BASE_URL=https://agentium.papai.ai npx playwright test --project=chromium --reporter=list
# 7 passed
```

## CI

- Retries = 2 on CI (transient network flakiness on the staging VM).
- Traces + videos retained only on failure (`trace: retain-on-failure`).
- Report published to `e2e/report/` (HTML). Attach as artifact.

## Known limits

- Targets a **shared VM** today. Tests create small throwaway systems
  and canonical answers. They clean up systems where the public API
  supports it; canonical answer cleanup remains backend-only until a
  DELETE endpoint exists.
- No mobile profile — desktop Chrome only. Mobile is out-of-scope
  until the companion app (post-Vague E).
