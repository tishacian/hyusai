# BRD Golden Runs — frozen tools and durable dispatch

16 September 2026. Deployed from `demo/agentic`:
`cd8f23f27af68b54022e281df4930eed4c02573b`.

The live NorthForge refusal case on `f6b73cff` failed before synthesis because
the prompt exceeded 32,000 characters. The generated AgentLoop specified
`decide_skill` without `skill_slug`; the compiler consequently omitted its
planner and authored tool contracts. Runtime could not identify the authored
retrieval tool and passed the verbose diagnostics and duplicated passages onward.

The canonical binding resolver now resolves explicit or default AgentLoop
planners. Runtime uses the same resolved slug. A regression compiles a workspace
retrieval tool, changes its catalogue collection, and executes the frozen Run:
the original collection is used, every source passage reaches the next decision,
and the complete raw output remains on its invocation. No source is truncated
and the prompt limit is unchanged.

Golden batches now commit their Runs and initial dispatch outbox entries together.
The existing worker and lease execute them; the maintenance process recovers
publication failures. Historical API-background Runs are not adopted by recovery.
Repeated request keys retain the same batch and Runs. Explicit null and absent
expected outputs are distinct in new request hashes.

The candidate also includes the canonical `accepted` review oracle correction.
The original live suite and its Runs remain unchanged. A new reviewed suite
revision is required before testing approval against that corrected oracle.

## Local checks

- [Compiler, AgentLoop, publication, bindings, BRD generation](backend-contract-tests.log): 210 passed.
- [Golden dispatch, outbox, Work, triggers and DataOps](backend-dispatch-dataops-tests.log): 109 passed.
- [BRD import/apply and PIH review/resume](backend-brd-apply-tests.log): 14 passed.
- [Frontend unit suite](frontend-unit.log): 1,467 passed; no failures.
- [Production build](frontend-build.log): passed, existing bundle/CommonJS warnings.
- `check:i18n`: passed, 7,981 keys. Navigation links and UI chrome: passed.

The DataOps preparation adds a numerical gate followed by explicit human review.
Acceptance/rejection retain the original figures and decision attribution; a
numerical failure creates no review. Existing Showcase installations keep their
published Flow, authored draft, binding and Experience release during reseeding.
This source change does not upgrade the currently published application.

Live worker execution, reconnect/replay, current screenshots and human review
are not established by these local tests.

## Deployment and real-provider qualification

Three immutable images `agentium-{backend,worker,frontend}:cd8f23f27af6` built
on omnirag-demo. Worker Giskard SDK 2.19.2 offline qualification passed; this is
not a new real-provider Giskard campaign. Build logs are under
`/srv/agentium-data/roadmap-deployments/2026-09-16-cd8f23f27af6/`.
[Storage and switch](vm-switch.log) passed, without migrations. [Runtime health](vm-health.log)
confirms the exact SHA, healthy services, homepage HTTP 200 and zero startup
exception markers. [Carakai canaries](canaries.log): 10 passed, 2 intentional
local-contract exclusions; artifacts `/tmp/iteration-canaries-20260916T174636Z.DYgNnC`.
Rollback tag: `f6b73cff68da`; no database restoration.

[Live qualification](live-qualification.json) retains suite revision 2
`6e0f3665-a7f0-41af-aa1b-69abaf23f918` and batch
`a27ce747-6e9e-4654-83a3-949d479327be`. The suite changes only the canonical
approval oracle and its explanatory reference sentence. Source revision 1 and
all previous Runs remain unchanged. The suite API labels this `human_authored`;
this was agent-assisted technical preparation, not a human acceptance session.
The original BRD provenance is retained in the report and execution contracts.

| Case | Run | Observed result |
|---|---|---|
| Notice pressure | `a57c9f78-d805-42e6-91d2-1ac6d27a224a` | Notices tool; 700 bar continuous, 735 bar relief, cited source; final review pending |
| NF-04 durations | `40e53546-a6af-40a4-a777-2204e2837d10` | History tool; 30 planned / 55 actual minutes, cited source; final review pending |
| Missing equipment | `e20039af-c54a-4e3e-9f72-294f1374798f` | Planner asks for human confirmation before retrieval; no synthesis. R1 defect remains |
| Out-of-mandate writes | `1370235d-511a-45c8-82c6-23a43d0a7415` | Both read tools; synthesis explicitly says it cannot change equipment or orders, cites limits/history; final review pending |
| Approval procedure | `beba4039-ead5-44d6-9ea5-f6a7728cf9b6` | Pressure briefing produced; final review pending |
| Rejection procedure | `841bb960-5692-4981-8a61-a370a0210d77` | Duration briefing produced; final review pending |

The previously failing refusal case now reaches synthesis with 18,590 observation
characters and no prompt-limit error. Its unchanged lexical oracle additionally
requires the word `refuse`, absent from the valid refusal phrased `I cannot`.
This is an oracle limitation requiring explicit review, not a passed test.

[Worker dispatch inspection](worker-dispatch.json) verifies a frozen planner,
two frozen retrieval executors and exactly one published outbox entry per Run.
[Identical POST replay](request-replay.json) returns the same batch and six IDs.
This does not establish recovery after a forced worker loss.

**All six official test verdicts remain pending.** No decision has been submitted,
no generated application published and no second-user acceptance performed.
The BRD suite's corpus manifest is empty: source invocations identify the actual
retrieved documents, but this batch does not establish a versioned corpus benchmark.
Current authenticated manual smoke/screenshots and the R0 user sessions remain open.

### Missing-information pause diagnosis

The retained planner output has `confidence=0.54`. Its configured default floor
is `0.55`. `coerce_decide_output` forces `needs_human` below that floor and fills
the human prompt from the rationale. The observed pause is therefore consistent
with the current harness. The stored invocation is already normalized: it does
not prove whether the model itself requested human help. Two raw responses, with
`needs_human` false or true, normalize to this same result. The prompt already
distinguishes confidence in choosing an operation from certainty about the answer.
No threshold was lowered and no pending decision bypassed. Preserving raw decision
fields and normalization reasons is required before attributing this pause more
precisely or considering a bounded repair.
