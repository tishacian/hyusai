# Golden verdicts and a real NorthForge absence case

16 September 2026. Initially qualified locally on `3e29282b`; subsequently
[deployed and checked with three real Golden previews](../release-6f8f8169-2026-09-16/README.md)
as `6f8f8169` on `demo/agentic`. The NorthForge investigation below was executed
on the earlier `b4fde677` runtime and retains that attribution.

## Real-provider investigation

[Run c511f059](https://agentium.papai.ai/runs/c511f059-c285-4c6d-9225-ee935b93abe5)
executes the unchanged NorthForge BRD draft and the question “Which equipment
caused the NF-04 delay?” on the live b4fde677 worker.

The planner selects the authorized history tool (confidence 0.78), reads the
passage explicitly lacking equipment and cause, and finishes its investigation
(confidence 0.92). Both native decision traces retain raw and effective fields;
neither was normalized into a human clarification. The synthesis cites the
history and says the equipment is not supplied. The Run waits at the required
final briefing review; no human decision was submitted.

[Recorded evidence](northforge-absence.json) retains the exact Run, invocations,
source passage, frozen tool-contract digest, model and pending decision. This is
one successful preparation with real OpenAI `gpt-5-2025-08-07`, not a completed
acceptance case or five-run reliability claim. The earlier low-confidence pause
still exists unchanged. The different outcome does not establish a causal model
improvement from the provenance-only code change.

The diagnostic launcher first attempted the separately gated invocation-360
route and received 404 after saving the Run result. It was corrected to use
invocations already supplied by the authorized Run detail route, then resumed
GET-only collection. No duplicate Run was launched; no feature gate was changed.

## Workbench correction

The generic Golden workbench previously reported a completed Run with no expected
value as passed, and classified a human/debug pause as failed. It also calculated
its own answer verdict in the browser.

New raw-case checkpoints record their evaluation method alongside their existing
frozen expected value. The canonical Run projection evaluates object subsets,
exact ordered arrays and JSON primitives on the server. Omitted expectations
remain unevaluated; explicit null remains a real expectation. Human/debug waits
remain pending; runtime failure is distinct from failed assertions. Existing
suite assertions are unchanged, and unmarked historical raw cases acquire no
invented verdict.

The workbench displays the server result only for the matching case and batch.
Its summary distinguishes finished executions, passed/failed checks and results
not evaluated. Pauses are neither completed nor failed checks. Each card opens
its exact canonical Run through the existing navigation directive.

## Verification

- [68 backend tests](backend.log): Golden API, suite evaluation, immutable expected
  value presence, subsets, arrays, boolean/number distinction, historical cases,
  pending human/debug states and execution failure.
- [1,478 frontend tests](frontend-unit.log): all passed. Regressions exercise
  authoritative server verdicts, mismatched batches, absent verdicts and pauses.
- `check:i18n`: passed, 8,000 keys. `check:nav-links` and `check:ui-chrome`: passed.
- [Production build](frontend-build.log): passed, existing bundle/CommonJS warnings.
- Actual Angular workbench rendered with controlled fixture responses and existing
  Cockpit tokens: [French/light desktop](fr-light-desktop.png),
  [English/dark 390 px](en-dark-mobile.png). No horizontal overflow; keyboard Tab
  reaches the next Run link. Fixture navigation uses a mocked resolver; production
  navigation is covered by the existing directive, link guard and AOT build.

Design target: existing Workbench cards and Cockpit tokens; the existing
[BRD reference lock](../../design/brd-system-ui-reference-lock.md) keeps one clear
next action. Refero copy guidance supplies distinct execution/check states.
Cards use a single text column to preserve long FR/EN labels at narrow widths.
The local JIT fixture sets the panel open on the Golden tab and adapts the signal
navigation input for JIT; it does not validate production routing or real Runs.

No new engine, permission, flag, dependency, migration or native NAWA theme change.
VM build, exact-SHA canaries and three real server verdicts are now qualified
in the release linked above. Live user UI acceptance remains pending. R0 human baseline and R1 approval/publication/second-user acceptance
remain open.
