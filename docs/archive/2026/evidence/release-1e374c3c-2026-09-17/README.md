# Release 1e374c3c — BRD tool proofs

17 September 2026 · `demo/agentic` ·
`1e374c3c1b71a70d88d1ffcee7fb8688ee28c2a6`.
Previous runtime/rollback images: `d05e84b15c53`.

## Runtime qualification

All three images built on omnirag-demo, 04:57:31–05:06:10 UTC:

- backend: `sha256:d4696e6e534b3278a2c8f968a92d86e6c43c1431c2321cdd72df1a1a70db0a9f`
- worker: `sha256:71f85b2f8fb17c1fa2492e1a0d3ee9a96380415f5861c34ac5026c202bc58bf6`
- frontend: `sha256:bb6e3e75cb9d3504e160b054c9e965dba2eb1786bf33334dbfff52aba73b5267`

No migration or flag/permission/NAWA-branding changes. No active durable jobs,
active or reserved worker tasks before the switch. Six application services use
the candidate images; frontend/backend healthy, zero startup exceptions.
Both public build identities match the exact SHA; homepage HTTP 200.
Carakai: **10 passed, 2 intentional local-contract exclusions**, 2.2 minutes.
The protected runner was advanced through a verified incremental bundle from
d05e84b1; its source marker contains the full SHA and newline.

[Local qualification](../brd-tool-proof-2026-09-17/README.md): 127 backend tests,
3 opt-in provider tests skipped; 1,513 frontend tests; 8,078 FR/EN keys;
navigation, chrome and production build pass. Four actual-component local
renders verify the new check links; they are not deployed manual screenshots.
The worker's offline Giskard SDK 2.19.2 fixture passes. The earlier real RAGET
campaign on 0f06b4eb remains historical; it was not rerun for this additive change.

The new evaluator was run read-only against the persisted Capture Run
7c2dca09-ef24-4dda-9291-8c9e64b44df5: it finds real retrieval invocation
2b43c403-2e02-439b-bf1f-5cc42c4cca97 and fails an unused planner assertion.
No Run/checkpoint/output was changed. This verifies the new evaluator on real
ledger data; it does not reattribute the old execution to this release or prove
a new BRD suite completed.

## Real generation: useful progress, failed technical review

Job `00f68887-2dad-4b68-82e2-665d1c2d8b64` completed on the configured workspace
provider, OpenAI gpt-5: one provider call, 11,757 reported tokens. New proposal `de87d014-e13b-4500-b7a8-827175659bd9`, hash
`52364f21b1a30386fea168e55bea7e452e315b9944eed1434047bd394d77b90a`.
The original BRD hash remains
`4585ab4704af9fc24d57bdd9db425be099f18ab92c6679b99853966de19391e3`.

The proposal includes real-invocation checks for both authored read tools.
All twelve requirement rows have proposed test links, but none is executed or
accepted. The six formerly unlinked rows now have proposed cases; this is not
proof of satisfaction. Technical inspection rejects application of this proposal:

- The notice input says “report 700 bar”, and the history input says “report 30
  and 55 minutes”. They copy acceptance instructions into the operator request.
- The absence input instructs the expected absence, and the refusal input tells
  the System to refuse. Such inputs cannot establish independent behavior.
- The two human-review inputs are reviewer instructions instead of meaningful
  operator requests; their expected human outcomes belong to the review protocol.
- Citation checks expect invented marker formats such as `[notices` or `[history`;
  presence of those strings alone does not establish source attribution.
- The broad `not_contains: completed` refusal check can reject legitimate prose.

The existing input-equals-question check cannot detect this: both fields contain
the same contaminated text. Next action: separate source acceptance procedures,
operator questions and reviewer instructions during generation, then review a
new proposal before creating a draft. Do not repair a benchmark by feeding its
answers to the System. This candidate remains **proposed, unapplied**, with no
new execution or human decision. The retained applied proposal and waiting R1
Runs are unchanged.

## Open acceptance

Authenticated Chrome remains at Sign in; reconnection was already requested.
R0 baseline: 0/5 business and 0/5 developers, video and closure decision open.
R1: fair generated cases, complete execution/refusal/review, publication and a
second authorized consumer remain open. No milestone is declared complete.
Rollback must not resume cases using `invocation_succeeded` on an older worker
that does not understand it; the new proposal has not been applied or executed.
