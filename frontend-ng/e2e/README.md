# Agentium E2E tests — Vague E / E2

Playwright scaffolding covering the 4 critical flows from
`docs/vague-e-plan.md` § E2 :

| # | Flow | File |
|---|------|------|
| 01 | Auth Keycloak (login / reload / invalid creds) | `tests/01-auth-keycloak.spec.ts` |
| 02 | Chat drop-and-ask → citation chip → sources panel | `tests/02-chat-drop-and-ask.spec.ts` |
| 03 | HITL pause → Approve → resume | `tests/03-hitl-approve.spec.ts` |
| 04 | Debug Step / Continue → outcome | `tests/04-debug-step-continue.spec.ts` |

## Activation (one-time)

```bash
npm install --save-dev @playwright/test
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

The tests rely on fixtures seeded via `scripts/test-vm.sh` (not yet
ported — see § "Seed script" below) :

- **User :** `alice@papai.ai` / `Agentium2026!` (dev realm `papai-org`,
  role `workspace.owner` on a workspace `playwright-staging`).
  Override with `E2E_USERNAME` + `E2E_PASSWORD` env vars.
- **PDFs (flow 02) :** `fixtures/docs/sample-a.pdf` and
  `sample-b.pdf` — TODO, committed once generated.
- **Systems (flows 03/04) :** `hitl-demo` (ambiguous prompt triggering
  `hitl_pending`) and `debug-demo` (2-skill sequential DAG).
  Tests auto-skip when the fixture is missing, so the smoke stays
  green on a pristine env.

## Seed script — TODO

`scripts/test-vm.sh seed:e2e` is expected to :

1. Ensure realm `papai-org` has user `alice@papai.ai` with the
   workspace.owner role on `playwright-staging`.
2. Upsert systems `hitl-demo` + `debug-demo` via `/api/v1/systems`
   with appropriate control policies.
3. Drop the two sample PDFs in `fixtures/docs/`.

Tracked as the last 10 % of E2.

## CI

- Retries = 2 on CI (transient network flakiness on the staging VM).
- Traces + videos retained only on failure (`trace: retain-on-failure`).
- Report published to `e2e/report/` (HTML). Attach as artifact.

## Known limits

- Targets a **shared VM** today ; flow 03 (HITL) mutates real data.
  Should migrate to an isolated docker-compose test stack once E7
  deploy stabilises (cf. risk "Playwright flaky sur VM partagée" in
  `vague-e-plan.md`).
- No mobile profile — desktop Chrome only. Mobile is out-of-scope
  until the companion app (post-Vague E).
