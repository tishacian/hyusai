# R1 corrective release — 7ab88007

Candidate: `7ab88007328c5e3a2cf5eaf6663e7d9c00eec927`.
Previous runtime: `f63f1eaf7e023e7ea5c428995c44ca0a3ad202ff`.

## Local gates on the candidate

- i18n: 7,981 keys checked; pass.
- Navigation links and UI chrome: pass.
- Frontend unit tests: 1,466 passed.
- Production frontend build: pass (existing CommonJS warnings).
- Scoped backend tests: 215 passed, 1 skipped.
- No migration added relative to the previous runtime.

Full gate outputs are retained alongside this file. The candidate is pushed to Bitbucket
`demo/agentic`; the VM source checkout and protected runner source both resolve to this SHA.
All three images were built on `omnirag-demo`, with the Giskard worker option preserved.
The stack was switched to this tag. Public HTTPS build-info reports the exact revision
with `revision_verified: true`; the homepage returns 200, backend and frontend are
healthy, all six application containers use the candidate tag, and the backend
startup log contains no traceback or exception. Storage checks passed.
Post-switch carakai canaries: **10 passed, 2 intentional local-fixture skips**,
2.1 minutes, exact SHA asserted. See `canaries.log`. Runner artifacts:
`/tmp/iteration-canaries-20260916T141731Z.EVUqzN` on carakai.
A hard-reloaded Chrome tab shows the sign-in page; authenticated manual smoke is pending.

Image digests:
- Backend: `sha256:f09d4caa4444c2818603a1990719246f00435d56c61ebf2ed039093e286b9f2e`.
- Worker: `sha256:8538c12936aede62eba4a0a3bf48e52945157a1784b2984a4208f045de418b92`.
- Frontend: `sha256:69e40ca46d569df562c006458b98b795a997cd21ff08c579bb8fbb3b6dd556ed`.

## Delivered correction scope

Quote membership assertions for original documentary inputs; separate BRD generation families;
retained acceptance paragraphs; AgentLoop tool-output provenance; original evidence preserved
within the existing overall prompt limit; stronger generation contract checks and bounded JSON
repair. No new adoption flag or migration is introduced.

## Qualification limits

NorthForge local-engine/live-provider qualification has three passing documentary cases
(pressure, durations, absence). Mutation refusal and the manual-review scenario remain open.
The engine harness acceptance is not human user acceptance. Five successful repetitions,
published application consumption by a second user and formative sessions remain outstanding.
AgentLoop comparison replay and frozen authored-tool contracts remain to qualify.

Do not close R1 or R0 user acceptance based on this corrective release. R0 technical evidence
and the pending adoption baseline remain separate.

## Compatibility

No database restore is part of rollback. The previous runtime predates `quotes_in_source`;
after storing suites using this operator, preserve compatible assertion readers or fix forward
rather than assuming the old image can evaluate those new suites.
