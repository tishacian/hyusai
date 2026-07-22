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

### Lot 7 sequential object-graph canary

`tests/12-lot7-object-graph-canary.spec.ts` is an opt-in authenticated gate
for the Capability → Run → SkillInvocation rollout. It discovers the target
inside the explicitly selected Workspace from the System 360 marker (or, when
the selector is omitted, from the unique marker + projection probation + SHA)
and writes evidence accepted by
`backend/scripts/rollout_lot7_projections.py`.

```bash
E2E_LOT7_CANARY=1 \
E2E_LOT7_PROJECTION=capability \
E2E_LOT7_WORKSPACE_ID=<immutable-workspace-id> \
E2E_EXPECTED_SHA=<full-40-character-deployed-sha> \
E2E_USERNAME=<authorized-user> \
E2E_PASSWORD=<secret> \
E2E_ENVIRONMENT=production \
E2E_LOT7_EVIDENCE=e2e/results/lot7-capability-evidence.json \
npx playwright test tests/12-lot7-object-graph-canary.spec.ts --project=chromium
```

The canary triggers its own Run after the probation starts and uses exactly
that Run in the proof. Set `E2E_LOT7_RUN_INPUT_JSON` only when the System needs
a typed input other than the generic default. The evidence v2 content-addresses
the runtime snapshots, one rendered API/UI fact per lens and an embedded strict
JUnit artifact; a stale, failed, cancelled, HITL or wrong-SHA Run is rejected.
In protected GitLab jobs, `CI_PROJECT_ID`, `CI_PIPELINE_ID` and `CI_JOB_ID` are
embedded into that artifact and must match the OIDC-authenticated finalizer.

Repeat with `run`, then `skill_invocation`, only after the preceding evidence
has activated its workspace flag. Credentials must come from protected CI
variables; they are never written to source or evidence. Traces, video and
screenshots are disabled by the spec. The gate also requires a second
authorized workspace: it verifies the explicit
`410 OBJECT_PROJECTION_REVOKED` contract there, switches through the real SPA
selector, and delivers a delayed response from the first workspace after the
switch to prove that the old object cannot repopulate the new context.

### Lot 8 authoritative value-loop canary

`tests/13-lot8-value-loop-canary.spec.ts` discovers the unique enabled System
through `settings.experience.value_loop_canary = "v1"`; it does not embed a
workspace slug, System name or object id. It executes the persisted
Outcome → Decision → Simulate → Approve → Act command chain, triggers and waits
for a real post-action Run, then measures that Run. It repeats commands with
content-addressed idempotency keys, proves that simulation never becomes
measurement, and verifies Steer reload/history plus atomic workspace purge.

The canary is intentionally mutating and therefore disabled by default. It
selects a bounded HITL threshold that differs from the current effective
policy, applies it through the real actuator, then requires a distinct
post-action Run carrying the exact server-generated ControlPolicy execution
snapshot before it can measure an outcome. It never fabricates an operator
outcome and never patches a Run to make the proof pass. Run it only against an
explicitly enabled deployment:

```bash
E2E_LOT8_CANARY=1 \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
E2E_EXPECTED_SHA='<40-char deployed SHA>' \
E2E_LOT8_EVIDENCE='test-results/lot8-value-loop.json' \
npx playwright test e2e/tests/13-lot8-value-loop-canary.spec.ts
```

The JSON above is a redacted observation: it contains SHA-256 references, not
raw workspace/System/Run/record ids. A missing measured post-action Run writes
`not_promotable`; even a protected Playwright job writes `behavior_observed`,
never `behavior_verified`. Promotion requires the protected server-side
`scripts.collect_value_loop_evidence` collector to bind this observation, the
original Playwright JUnit digest, the exact policy snapshot and the five
authoritative DB records. The activation write must run in the same trusted
GitLab OIDC job that produced the evidence. Local collection remains explicitly
non-promotable. Authoring this test does not constitute execution evidence.

### Lot 9 Workspace App lifecycle canary

`tests/14-lot9-workspace-app-lifecycle-canary.spec.ts` is the opt-in,
authenticated preflight gate. It discovers the single structurally marked
admin workspace while runtime authority is disabled, then a compatible
two-version app from the manifest and installation contracts themselves—no
workspace slug/name, app id/name or database id is fixed in the test. It
installs the oldest exact digest, proves an idempotent replay, then exercises
upgrade, rollback and uninstall through the Governance UI. Its `finally`
restores the exact initial, non-empty installation set; immutable lifecycle and
audit receipts intentionally remain.

The canary never changes an active workspace. Such a target must first be
explicitly deactivated, then receive its lifecycle mutation and fresh
behaviour proof before a new activation. The protected rollout sequence is:

`bootstrap → preflight canary → collect → stage → post-activation canary → collect → finalize`

`stage` opens a bounded probation. During that window,
`tests/15-lot9-workspace-app-probation-canary.spec.ts` proves the exact
workspace, SHA, probation reference, installation/configuration digest,
runtime routes and action packs, then switches workspace to verify atomic
context purge. An expired or drifted probation fails closed. `abort` is the
mandatory recovery path if the post-activation step does not complete.

```bash
E2E_LOT9_CANARY=1 \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
E2E_EXPECTED_SHA='<40-char deployed SHA>' \
E2E_LOT9_EVIDENCE='test-results/lot9-workspace-app-lifecycle.json' \
npx playwright test e2e/tests/14-lot9-workspace-app-lifecycle-canary.spec.ts
```

During the staged probation:

```bash
E2E_LOT9_POST_CANARY=1 \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
E2E_EXPECTED_SHA='<40-char deployed SHA>' \
E2E_LOT9_POST_EVIDENCE='test-results/lot9-workspace-app-postactivation.json' \
npx playwright test e2e/tests/15-lot9-workspace-app-probation-canary.spec.ts
```

Both tests are disabled by default. Their observations and original JUnit
digests must be collected and consumed by the same trusted GitLab OIDC job for
their respective `stage` or `finalize` write. Source and successful local
compilation are only static evidence; behavior promotion requires execution on
the attested deployed SHA.

## Known limits

- Targets a **shared VM** today. Tests create small throwaway systems
  and canonical answers. They clean up systems where the public API
  supports it; canonical answer cleanup remains backend-only until a
  DELETE endpoint exists.
- No mobile profile — desktop Chrome only. Mobile is out-of-scope
  until the companion app (post-Vague E).
