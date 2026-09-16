# BRD Golden Runs — frozen tools and durable dispatch

16 September 2026. Candidate under qualification; deployment is not yet claimed.

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
