# Release d05e84b1 — retrieved evidence reaches the answer

Live SHA: `d05e84b15c53e9a12dc92a9cab6f765be648fead`, from `demo/agentic`.
Three immutable images built on omnirag-demo on 17 September, 04:22:20–04:31:11 UTC.
Public frontend/backend identify this exact SHA. Application services are running;
backend/frontend are healthy, with zero startup exceptions. Durable jobs and both
workers were idle before the switch. Rollback: `0f06b4eb5f6b`.

No migration, flag, permission, published System, shared Skill or native NAWA theme
was changed. Retained R1 Runs and human decisions remain untouched.

## Corrected behavior

The answer agent no longer applies a second cosine threshold or sort to the
canonical retrieval result. Retrieval already owns source policy, thresholding
and ranking. Previously, a valid hybrid rank score of 0.0164 was mistaken for a
low cosine similarity and the passage disappeared before synthesis.

[Local qualification](https://bitbucket.org/datategy-root/omnirag/src/b6601f5e34fc87fdcdf66d3c4b204afae7cc7bc3/docs/evidence/synthesis-context-handoff-2026-09-17/README.md):
137 backend tests, 1,512 frontend tests; i18n (8,077 keys), navigation, chrome and
production build pass. The regression fails on the old code and covers actual
agent streaming, model prompt and citation output. Low dense evidence remains filtered.

## Actual Runs

The retained publication contains a synthetic corrected pressure of **6 bar**.
It is distinct from the NorthForge PMP-700 manual's **700 bar** operating limit.
No publication, source or expected answer was rewritten for these checks.

1. **The failing hybrid path now succeeds.**
   [Run 7c2dca09](https://agentium.papai.ai/runs/7c2dca09-ef24-4dda-9291-8c9e64b44df5)
   uses the original question, fast/chat retrieval and auto routing. The observed
   pipeline is `hybrid`; score `0.01639344262295082` is retained through synthesis.
   The answer gives 6 bar and quotes the published passage with citation [1].
   Its source is document `091af258-47b3-56db-967f-123de591fc6f` in only
   `qa-capture-inventory-4479`. Search, answer and audit invocations completed.
2. **Information absent from the source is acknowledged.**
   [Run 201a5ac4](https://agentium.papai.ai/runs/201a5ac4-d9e8-491f-86e0-6ac7b8baaecc)
   asks for the equipment serial number. The answer explicitly says it is not
   provided, cites the available sheet, and invents no serial number.
3. **An additional default API route succeeds.**
   [Run 8ec6ee27](https://agentium.papai.ai/runs/8ec6ee27-76b1-4ace-b051-2b05c2596f28)
   used C-HAH and also returned the exact source. This is additional coverage;
   it is not the reproduction of the failing hybrid route in item 1.

All three are new, stateless API conversations with separate ephemeral Contexts.
They use the same orchestrator as the UI, but do not substitute for a browser smoke,
five complete Capture repetitions, a spoken correction or a human adoption session.
The old failed Runs remain unchanged. Full answers and source/Run details are in
[capture-fast-conversation.json](capture-fast-conversation.json),
[capture-absence-conversation.json](capture-absence-conversation.json) and
[capture-conversation.json](capture-conversation.json).

## Release gates and remaining acceptance

- Protected carakai: **10 passed, 2 intentional local-contract exclusions**,
  [log](canaries.log). Includes Work, Studio, branding isolation, Hypervisor and
  exact Run/evaluation chart selection.
- Optional worker SDK 2.19.2: dependency consistency and offline fixture pass
  during image construction. This is not a fresh real-provider campaign.
- The [actual OpenAI/Giskard campaign](../release-0f06b4eb-2026-09-17/README.md)
  remains attributed to the preceding 0f06b4eb runtime, with six linked Runs.
- Authenticated manual Capture smoke: **pending**. Chrome is on Sign in; the
  reconnection question is pending. No new authenticated screenshot or video is claimed.
- R0: baseline remains 0/5 business and 0/5 developer; short video and Thibaud's
  closure decision remain outstanding. No additional R0 criterion is introduced.
- R1–R6 retain their full acceptance scope; these successful calls do not close R2.
