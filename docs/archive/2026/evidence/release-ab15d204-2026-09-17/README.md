# Invocation evidence and ancestry — ab15d204

Deployed runtime: `ab15d204a73ee9975ce52d56dccb11b92e39589d`, from published
`demo/agentic`. All three images built on omnirag-demo, tag `ab15d204a73e`.
Rollback: `970f4512d81c`. No migration, activation change or NAWA theme change.

## Qualification

- 1,497 frontend tests, i18n, links, UI chrome and production build passed;
  [local logs](../invocation-context-2026-09-17/README.md).
- Backend unchanged from the 16 authorization/perspective tests on 970f4512.
- Zero active/reserved worker tasks and durable jobs before switching.
- Storage checks passed; six application containers use the candidate tag;
  backend/frontend healthy, public frontend/backend SHA exact, homepage HTTP 200,
  backend startup exception count zero.
- Worker Giskard SDK 2.19.2 offline fixture passed. This is not a live campaign.
- Carakai: **10 passed, 2 intentional skips**, including operation → audit → Run
  and the additional Run-breadcrumb assertion. Artifacts:
  `/tmp/iteration-canaries-20260917T012226Z.6HkLvl`.

Immutable image IDs are retained in `vm-build.log`:
backend `sha256:637aedb629e4376195b0b52cdf06660eb7141826e8072f6ceb2735065c097c2a`,
worker `sha256:71695fa9d6cecf754d09064e844e6ae6ce612e4792f4ffefd4beff1dfec65b64`,
frontend `sha256:68f90d6b4af3721a9882dd05d01f2200c93096dc58a17e4ffdf907942a91b85b`.

## Real browser journey

Chrome, authenticated owner in Agentium Showcase, English/dark, existing 360 flags
disabled. Hard reload followed by a completed normal reload loaded the candidate.
The retained Run `9b73e4e5-083b-4a8c-b47b-0e52bbbebdf3` opens the numerical-check
invocation `65e3acad-3c06-46b2-893b-8139d706851b`.

- System → Run → invocation breadcrumbs and scoped navigation are retained.
- The full rendered audit equals the previous retained audit; node `check`,
  4 orders, 120/155/+35 minutes, 3 late orders, NF-04 +25.
- `numerical_reference_passed: true`, `human_validated: false`,
  `economic_impact: null` remain unchanged.
- Back to Run retains its exact identifier and System. Browser Back returns to
  the same invocation with its ancestry. Reload preserves the selected invocation.
- An intentionally absent all-zero invocation identifier shows an unavailable
  state, no stale payload, Retry and Back to Run. Retry remains unavailable;
  browser Back restores the real proof.

[Actual invocation screenshot](invocation.png), [DOM](invocation-dom.txt),
[return to Run](return-run-dom.txt), [unavailable state](unavailable.png).
The execution itself remains attributed to its original runtime `4771f15b`.
No Run was relaunched and no R1 decision was submitted.

## Remaining scope

The shared outcome card still displays `$0.00` and `0%` when `value_source` is
`unset`. This requires a separate truthfulness correction; the displayed zero is
not proof of measured economic impact. These technical browser checks do not
replace the video, five business/five developer sessions or the R0 closure decision.
