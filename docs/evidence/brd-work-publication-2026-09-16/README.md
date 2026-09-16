# BRD → Work application and evaluation evidence

Deployed: `b4fde677a75a7a9f6ab30898882104c37582709b`, pushed to
`demo/agentic` and built on `omnirag-demo` on 16 September 2026.
Public revision verified; carakai canaries passed.
Previous runtime / rollback tag: `cd8f23f27af6`.

## Implemented

- After publishing the Flow, explicitly activate the System, then create its
  application draft in the existing Studio. The **Application** toolbar action
  reopens this handoff after closing the panel or reloading. Audience selection,
  release and deployment remain in Studio; publication never activates silently.
  The activation PATCH checks the reviewed published-version ID under the
  existing System row lock. A concurrent publication is rejected before mutation.
- Work forms preserve and enforce text `minLength`/`maxLength`, including Unicode
  code points, optional omitted fields and an explicitly allowed empty string.
  FR/EN length hints are linked to the fields for assistive technology. No schema
  constraints are removed and the frozen 0.1 renderer is unchanged.
- New BRD suites retain the collection ledger manifests of their compiled
  `semantic_search_v1` authored executors, including AgentLoop tools. Golden and
  comparison preparation reject changed collection bindings or ledger drift.
  An explicit empty snapshot differs from a missing historical snapshot.
- Native planner invocations retain typed raw decision fields, the confidence
  floor, normalization reasons and the effective decision. Invalid text is
  replaced with type markers; prompts, completions and rationales are not copied
  into this trace. Existing decision semantics and thresholds are unchanged.

## Local gates

| Gate | Evidence | Result |
|---|---|---|
| Targeted backend suite | [backend.log](backend.log) | 286 passed |
| Complete frontend suite | [frontend-unit.log](frontend-unit.log), [corrected accessibility assertion](frontend-accessibility-rerun.log) | All 1,478 tests covered and passing after the focused rerun |
| FR/EN | [i18n.log](i18n.log) | Passed, 7,992 keys |
| Navigation | [nav-links.log](nav-links.log) | Passed, fail-closed |
| Shared UI chrome | [ui-chrome.log](ui-chrome.log) | Passed |
| Production frontend build | [frontend-build.log](frontend-build.log) | Passed; existing budget/CommonJS warnings |

The initial complete frontend invocation had one failing source-contract
assertion: it required a literal Publish accessible label, while the control
now switches between Publish and Application. The assertion now verifies both
states and their nonempty translations; its full 16-test file passed on rerun.
The remaining 1,462 tests passed in the complete invocation. No production code
changed after the successful build. Backend checks include publication/activation
concurrency, rejected writes without new versions or audit mutations, idempotent
activation, corpus switching and rollback, legacy-suite limitations, typed
decision provenance, and the existing dispatch and binding contracts.

## Deployment and runtime verification

The six application containers use immutable tag `b4fde677a75a`. Backend and
frontend are healthy, homepage returns 200, and public build-info verifies the
exact revision. Startup traceback/exception count is zero. The first check during
backend startup returned 502; the completed startup and subsequent checks passed.
No migration, infrastructure restart or database restoration was performed.

- [Image IDs and revision labels](images.log), [deployment log](deploy.log).
- Storage checks passed [before](storage-check.log) and [after](storage-check-after.log).
- [Runtime health](runtime-check.log), [public revision](public-build-info.json),
  [startup check](startup-check.log).
- [Worker SDK qualification](worker-sdk-check.log): Giskard 2.19.2, pip check and
  offline SDK fixtures passed. Provider models were mocked; this is not a live campaign.
- [Exact-source carakai canaries](canaries.log): **10 passed, 2 intentional local
  contract skips**, 2.0 minutes. Includes Work, Studio, Hypervisor and exact-Run
  observability. Runner artifacts:
  `/tmp/iteration-canaries-20260916T192836Z.FOTU1G` on carakai.
- [Retained-contract check](runtime-contract-check.json),
  [read-only script](read_runtime_contract.py): the new resolver reads the two
  collections from each of the retained notice/history Run contracts and reports
  the old BRD suite's missing manifest. SQL was read-only, no provider called,
  no Run created, and no historical evidence changed. This does not qualify a new
  BRD generation or Golden batch on this SHA.

VM build logs remain under
`/srv/agentium-data/roadmap-deployments/2026-09-16-b4fde677a75a/`.
The prior images remain available under `cd8f23f27af6`; rolling back removes the
new handoff and guards. Preserve recent database writes and evaluate new 0.2
form constraints before exposing them through an older renderer.

Chrome was checked after the switch and still displays sign-in. The authenticated
manual smoke, screenshots/video of the new handoff, and second-user consumption
are not supplied by the content-free carakai canaries.

## Qualification boundaries

- No migration, new flag, dependency, CSS or native NAWA theme change.
- Historical suites and Runs are not retrofitted. The six real NorthForge Runs
  from [cd8f23f2](../brd-durable-tools-2026-09-16/README.md) keep their evidence,
  pending decisions and historical corpus limitations.
- This change does not resolve the missing-equipment planner pause or rewrite
  the brittle literal refusal assertion after observing its output.
- AgentLoop/`registry_call` comparisons remain outside the existing read-only
  comparison executor set. Binding guards do not qualify that execution path.
- A ledger fingerprint does not freeze every Qdrant byte, an external model
  revision or live retrieval. Legacy retrieval suites without a manifest remain
  explicitly limited; text-only suites do not acquire a fictitious limitation.
- Authenticated manual acceptance, a generated application consumed by a second
  user, and the formative sessions are NOT RUN. Chrome remains on sign-in.
- A real-provider Giskard campaign is not established by these tests.

This deployment does not record an R0 or R1 closure decision.
