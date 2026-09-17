# Invocation audit release — 970f4512

Runtime: `970f4512d81c9522f12cd9435227a79831fd67a1`, deployed from published
`demo/agentic`, with all three images built on omnirag-demo. Rollback: `4771f15b2d54`.
Local gates: 1,496 frontend tests, 16 backend authorization/perspective tests,
i18n, navigation, UI chrome, production build. No migration or flag change.

Both public build identities match the candidate. All six application containers
use the candidate tag, backend/frontend are healthy, homepage HTTP 200 and startup
exception count zero. No active/reserved worker work or durable jobs was present
before the switch. Giskard SDK offline qualification passes; no live campaign is claimed.

The first canary attempt was started prematurely while the backend was starting:
three revision checks failed on HTTP 502, three tests passed, two were skipped
and four did not run. Its terminal log is retained as `canaries-startup-failure.log`.
Qualification was started again only after that process ended and the runtime was
healthy with its exact public SHA.

## Real browser verification and remaining defect

Authenticated Chrome, Showcase, English, dark Cockpit, owner role. The operation
link for the retained NorthForge Run `9b73e4e5-083b-4a8c-b47b-0e52bbbebdf3`
opens invocation `65e3acad-3c06-46b2-893b-8139d706851b` with the 360 flag off.
The audit retains 4 orders, 120/155/+35 minutes, 3 late orders, NF-04 +25,
`numerical_reference_passed: true`, `human_validated: false`, `economic_impact: null`.
Its execution remains attributed to its original runtime `4771f15b`; it was not rerun.

The manual check also found that the navigation resolver still calls the gated
invocation endpoint, so breadcrumbs lose the System/Run ancestry despite the
audit being readable. This is a remaining defect, not complete navigation acceptance.
The follow-up resolver change uses invocation membership already authorized in
the canonical Run and rejects missing/filtered invocations and forged parent hints.
The canary is extended to assert the Run breadcrumb as well.

See `audit.json`, `audit-dom.txt` and `audit.png` for the actual retained evidence.
The shared result card still displays zero value/efficiency for `value_source: unset`;
that truthfulness issue is a separate remaining R0 correction. User sessions and
video remain pending.

The post-startup qualification finished with **10 passes and 2 intentional skips**.
The authoritative runner directory is the artifacts line in the retained `canaries.log`.
