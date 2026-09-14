# Agentium E2E tests — Vague E / E2

Playwright scaffolding covering the 4 critical flows from
`docs/vague-e-plan.md` § E2 :

| # | Flow | File |
|---|------|------|
| 00 | Clean-workspace first use: model → document → cited answer → retry, EN + FR | `tests/00-first-use-golden-path.spec.ts` |
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

## Core product release gates

`npm run check:core-release` is the single supported way to run the two core
product browser release gates. It runs
`tests/00-first-use-golden-path.spec.ts` first, then
`tests/00-core-product-accessibility.spec.ts`, and stops at the first failure
with that gate's exit code. Use `-- --golden-only` or `-- --accessibility-only`
for one gate; the two flags are mutually exclusive.

```bash
E2E_BASE_URL=http://localhost:4200 \
E2E_USERNAME=your-test-user \
E2E_PASSWORD=your-test-password \
E2E_WORKSPACE_SLUG=your-isolated-workspace \
E2E_GOLDEN_PROVIDER=ollama \
E2E_GOLDEN_MODEL=your-installed-model \
npm run check:core-release
```

Safety contract:

- **Fail-closed configuration.** All four common variables are required, and
  the golden path additionally requires `E2E_GOLDEN_PROVIDER` and
  `E2E_GOLDEN_MODEL`. The release command never falls back to the fixture demo
  credentials or workspace; a missing value stops it with exit code 2 before
  any browser starts.
- **Loopback by default.** Only `localhost`, `127.0.0.1`, and `::1` over
  http/https are accepted. These gates write into the selected workspace, so a
  remote target requires the explicit `E2E_RELEASE_GATE_ALLOW_REMOTE=1` opt-in.
- **Isolated workspace.** `E2E_WORKSPACE_SLUG` must name a workspace you are
  willing to mutate: the golden path validates and persists a real provider in
  it.
- **Separated evidence.** Each gate writes its own `output/`, `blob/`,
  `report/`, and `junit.xml` under `e2e/results/core-release/<gate>/`
  (override the root with `E2E_CORE_RELEASE_ARTIFACT_DIR`). The runner only
  creates directories inside that root and deletes nothing.
- **No secrets in the log.** It prints the target, workspace slug, gate and
  spec names, provider/model where relevant, elapsed time, and the result;
  password- and key-shaped values are redacted.

Cloud providers also require `E2E_GOLDEN_API_KEY`. Azure-compatible setups can
provide `E2E_GOLDEN_ENDPOINT` and `E2E_GOLDEN_DEPLOYMENT`. The test principal
must already belong to the isolated workspace. The test runs the same journey
in English and French and fails when the first cited answer takes
longer than `E2E_GOLDEN_MAX_FIRST_ANSWER_MS` (45 seconds by default).
It also attaches a privacy-safe JSON timing record for sign-in to usable Ask,
provider readiness, first cited answer, and citation to source preview. The
remaining budgets can be tuned with `E2E_PERF_SIGNIN_TO_COMPOSER_MS`,
`E2E_PERF_MODEL_READINESS_MS`, and `E2E_PERF_SOURCE_PREVIEW_MS`.

## Core startup performance gate

`npm run check:performance` makes a real optimized production build, reads the
Angular/esbuild dependency graph, and fails if the initial bundle exceeds
1,000,000 bytes, Chart.js or the complete translation catalogue becomes eager,
or any of Ask, Settings, Knowledge, Build, and Runs stops being route-lazy. The
gate fails closed when build statistics are missing or malformed.

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

### Core product accessibility gate

`tests/00-core-product-accessibility.spec.ts` covers the supported first-use
surfaces—Ask, Settings, Knowledge, Build, and Runs—without relying on retired
routes. For each surface it runs the shared real-browser matrix in French and
English, light and dark themes, and desktop, 456 px, and 320 px viewports. The
gate checks WCAG 2.0/2.1/2.2 A/AA with axe, reduced-motion behavior, horizontal
reflow, and captures visual evidence.

Run it only against an isolated workspace with an existing test principal,
through the same release runner and under the same safety contract as
[Core product release gates](#core-product-release-gates):

```bash
E2E_BASE_URL=http://localhost:4200 \
E2E_USERNAME='your-test-user' \
E2E_PASSWORD='your-test-password' \
E2E_WORKSPACE_SLUG='your-isolated-workspace' \
npm run check:core-release -- --accessibility-only
```

### Experience Studio lifecycle canary

`tests/17-experience-studio-canary.spec.ts` discovers an enabled workspace and
a compatible published manual ingress without embedding tenant, System, app,
or release ids. It then drives the real three-step wizard, opens Studio, edits
and saves the draft, checks readiness, creates an immutable release, and proves
that the release is still absent from Work. The default run deletes both the
undeployed Experience and any binding created by the wizard.

It also checks the authoring shell and the created editor at 456 px and 320 px,
roving keyboard focus, modal focus trapping/restoration, and—when a second
principal is supplied—the reviewer-only route and editor contract:

Studio and Work both run the same real-browser accessibility/visual matrix:
FR/EN × light/dark × desktop/456/320 CSS px. Every state is scanned by axe for
WCAG 2.0, 2.1 and 2.2 A/AA violations, captured as a PNG artifact, and checked
for page-level horizontal overflow with reduced motion enabled. The 320 px case
is the WCAG 1.4.10 reflow equivalent of a 1280 px viewport at 400% zoom. Once
`E2E_EXPERIENCE_CANARY=1` is set, a missing enabled workspace or visible Work
application fails the gate; it is never converted into a data-dependent skip.

```bash
E2E_EXPERIENCE_CANARY=1 \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
E2E_EXPERIENCE_REVIEWER_USERNAME='...' \
E2E_EXPERIENCE_REVIEWER_PASSWORD='...' \
E2E_EXPERIENCE_REQUIRE_REVIEWER=1 \
npx playwright test e2e/tests/17-experience-studio-canary.spec.ts
```

A real Pilot deployment is deliberately separate and opt-in. Deployment makes
the canary Experience non-deletable, so the gate requires both an attested SHA
and explicit acceptance that the uniquely named test application is retained:

```bash
E2E_EXPERIENCE_CANARY=1 \
E2E_EXPERIENCE_DEPLOY=1 \
E2E_EXPERIENCE_ALLOW_RETAINED=1 \
E2E_EXPECTED_SHA='<40-char deployed SHA>' \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
npx playwright test e2e/tests/17-experience-studio-canary.spec.ts
```

That path deploys only to Pilot with an Admin audience, verifies the same
created app in `/work` at desktop, 456 px, and 320 px, then creates and deploys
a second release and rolls the channel back to the first. It never executes the
bound System action.

### NAWA Agent Studio behavioural contract

`tests/18-nawa-agent-studio-canary.spec.ts` is the freeze contract of the
PR to PO demo: `/work/pr-to-po/desk` lands on the Studio, one click starts the
published agent through its Experience binding, the read nodes show their
verbatim SAP calls, the human gate opens with a proposal, and the approval is
the canonical HITL decision. The write verdict (blocked by the guardrail,
sealed, or PO created and committed) is the server's — the spec asserts that
the browser sends zero request to `/mcp/servers/{id}/invoke`. It then opens the
chat write dialogue, cancels once (nothing written, gate still open) and
confirms once with the `BAPI_PO_CREATE1` guardrail off (refusal bubble, blocked
call in the transcript). Every gate it opens is settled before it ends.

The default run keeps the create guardrail off for the run-flow approval too,
so it never reaches SAP even on an unsealed workspace:

```bash
E2E_NAWA_STUDIO=1 \
E2E_USERNAME='...' \
E2E_PASSWORD='...' \
E2E_EXPECTED_SHA='<40-char deployed SHA>' \
E2E_NAWA_STUDIO_EVIDENCE='test-results/nawa-agent-studio.json' \
npx playwright test e2e/tests/18-nawa-agent-studio-canary.spec.ts
```

`E2E_NAWA_STUDIO_WRITE=1` approves the run-flow gate with the guardrail on:
one real PO per run when the workspace carries `sap_write_unsealed`, the
sealed envelope otherwise. `E2E_NAWA_WORKSPACE_SLUG` overrides `nawa`.
`E2E_NAWA_STUDIO_RECORD=1` keeps the 1440×900 video of the passing run under
`e2e/results/` for the ops journal.

## Known limits

- Targets a **shared VM** today. Tests create small throwaway systems
  and canonical answers. They clean up systems where the public API
  supports it; canonical answer cleanup remains backend-only until a
  DELETE endpoint exists.
- The general suite still uses desktop Chrome; the Experience lifecycle canary
  explicitly resizes that browser to 456 px and 320 px for its responsive gate.
