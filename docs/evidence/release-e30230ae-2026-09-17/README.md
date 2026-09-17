# Release e30230ae — fair BRD inputs and factual retrieval

17 September 2026 · `demo/agentic` ·
`e30230aea3f58518bbe2219a5b2dbbdd757bab2f`.
Rollback images: `1e374c3c1b71`. No migration or flag change.

## Delivered and qualified

Generated acceptance cases separate the operator request from expected facts and
reviewer procedures. A narrow server guard rejects copied procedures and
review-only inputs that do not reuse a business case. It does not detect all
semantic leakage. The shared retrieval classifier recognizes trailing citation
requests such as “with source” and “avec les sources”, while passing the full
original query to retrieval. No shared Skill, published version, NAWA theme or
retained production R1 Run/decision was changed.

[Local evidence](../brd-input-separation-2026-09-17/README.md): 230 backend tests
passed, 3 opt-in tests skipped in the ordinary suite; 1,513 frontend tests passed;
8,078 FR/EN keys, navigation, chrome and production build passed.

All three images built on omnirag-demo, 05:45:14–05:53:53 UTC:

- Backend: `sha256:30945ab1d3a7e5d4db412e9c3c9c83be01e0eb076b60b712b74e8045b630eacb`
- Worker: `sha256:f94f4c32d5b9e27afea41555df9486c9132c5392fdbee75bbb5fb21347d8a175`
- Frontend: `sha256:cfa505dbe3344ac15b386168ac9948e5e9449a8b4595c421e3506042d138add4`

Zero active durable jobs and zero active/reserved tasks on both workers before
switching. Six application services use the exact candidate; frontend/backend
healthy, zero backend startup exceptions. The first public probe during startup
returned 502; after health settled, both public build identities match the full
SHA and the homepage returns 200. No restart or second deployment was needed.

Carakai was advanced with a verified incremental bundle and the exact source
marker. [Canaries](canaries.log): **10 passed, 2 intentional local-contract
exclusions**, 2.1 minutes. Protected artifacts:
`/tmp/iteration-canaries-20260917T055551Z.lgzwS6` on carakai.
The worker's optional Giskard 2.19.2 SDK passes its offline fixture; this is not a
new live-provider campaign. No remote CI service exists for this release loop.

## Same history case, actual improvement

The generated draft was applied again only in the isolated local engine fixture.
Its candidate bytes, input, assertions and mirrored live corpus metadata were
unchanged. Planner/synthesis used the real configured provider; retrieval used
the deployed Showcase service. Review acceptance was simulated locally by the
harness, not performed by a human or on production Runs.

Question: “Report planned and actual durations for NF-04, with source.”

| Observation | Before: 1e374c3c retrieval | After: e30230ae retrieval |
|---|---|---|
| History calls | 6, returning document inventory | 1, returning the actual history passage |
| Answer | Durations unavailable | Planned 30 minutes; actual 55 minutes |
| Source | Collection inventory | `northforge-intervention-history.md`, chunk 0, document `503f8bb1-0d46-54ab-9f9b-d0ac83572de6` |
| Native test | Failed | Passed, including actual invocation `83acf9f1-ab46-4dc0-90c0-b4864cc342a8` |
| Case duration | 199.9 seconds | 61.0 seconds |

[Exact outputs, checks and call records](history-comparison.json).
The output was inspected for correct attribution of planned/actual durations;
the numeric `contains` checks alone would not prove this. These are individual
observations, not a latency benchmark. The French request also retrieves the
same factual history through `hybrid`, not an inventory:
[French retrieval](french-retrieval.json).

## Remaining acceptance

This does not make the complete six-case suite green. The original six-case
qualification had four passes and two failures. Only the failed history case
was rerun after deployment; the refusal case still has brittle literal checks
despite an observed read-only refusal. No assertion was weakened to manufacture
a pass. Semantic refusal checks, complete coverage (D-1 remains uncovered),
publication, second-user use and full repetitions remain R1 work.

Chrome remains at Sign in; its existing reconnection request is pending. No new
authenticated manual screenshot or video is claimed. R0's human baseline and
closure decision remain open. Historical provider generations and production
Runs retain their original attribution and decisions.
