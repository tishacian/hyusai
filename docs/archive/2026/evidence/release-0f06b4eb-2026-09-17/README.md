# Release 0f06b4eb — cited content and published collection scope

Live SHA: `0f06b4eb5f6bcd728a95ad85bc030792a7bab999`, pushed on `demo/agentic`.
Three immutable images built on omnirag-demo, 03:57:36–04:06:07 UTC on 17 September.
Public frontend/backend report the exact SHA; six application containers use its
12-character tag. Backend/frontend are healthy, with no startup exception.
Workers and durable jobs were idle before the switch. Rollback: `def0b3cc348a`.
No migration, permission, workspace flag or native NAWA theme change.

- Local qualification: 1,512 frontend tests, 117 backend tests, 8,077 FR/EN keys,
  navigation/chrome/production build pass. FR/EN 390-pixel ChatPanel checks use
  fixture services; see [implementation evidence](../capture-scope-routing-2026-09-17/README.md).
- Protected carakai: **10 passed, 2 intentional local-contract exclusions**.
- Optional worker SDK: 2.19.2 fixture passes; this is separate from the actual
  provider campaign below.
- The earlier d5c8b93d images were built but never switched live.

## Capture: routing fixed; synthesis still fails

Run `74a382c2-4b36-4285-95bd-6a6305b97e34` used the same question as the retained
failed def0b3cc Run: “Pour la recette synthétique R2INV4479, quelle est la pression
nominale après correction ? Cite le passage source.”

The UI names the selected collection and does not display an inactive workspace
source selector. Retrieval now uses `hybrid/content_search`, touches only
`qa-capture-inventory-4479`, and retrieves the actual 6-bar passage from
`capture-9d3500c7.md`. The Run preserves this passage and its document identity.
The answer nevertheless says that no relevant context is available, without citations.

Root cause: the synthesis agent reapplies a dense similarity threshold of 0.2
to the hybrid rank-fusion score `0.01639344262295082`. The canonical retriever
had already accepted the passage with dense similarity `0.7217344`. Its threshold
metrics correctly report no removal. The duplicate downstream filter removes it.
A fix is being qualified; this Run remains unchanged and is not counted as a pass.

![Actual failed answer after successful retrieval](capture-retrieval-empty.png)

## Actual Giskard campaign

The existing synthetic OBS QA System was used without changing its draft,
shared Skills, published versions or human decisions. A new technically reviewed
suite preserves the three original inputs/assertions and adds question, answer path,
reference answer and exact source excerpts required by RAGET. This technical review
is agent-assisted, not a user study.

- Suite: `9cf497f2-1a8f-4581-b18f-5539eb80166b`.
- Comparison: `0f4ba081-3b49-46e2-9f06-3827ed6292f8`, completed, six canonical Runs.
- RAGET job: `48f3c313-e521-47e1-9f0a-36b009b82c72`, completed, 04:15:03–04:16:24 UTC.
- Method: Giskard 2.19.2, actual configured OpenAI `gpt-5` judge and
  `text-embedding-3-small`; 11 corpus chunks examined. No mocked provider.
- Baseline: three semantically correct answers; the pressure and maintenance
  answers omit the required citations. Native assertions fail these citations.
- Candidate: three correct answers, all native assertions pass. The absent-serial
  baseline also correctly recognises missing information, despite failing its
  brittle lexical native assertion. Do not claim a semantic improvement on that case.
- RAGET marks all six answers correct. Native contractual checks and semantic
  judging answer different questions; neither replaces the other.
- Judge usage: 8 actual calls, 7,448 provider-reported tokens; $0.0363475 calculated
  using the LiteLLM model catalogue. This is evaluation cost, not economic savings.
  Execution ledger costs are zero-priced entries and do not prove zero provider spend.

The comparison retains its **limited** comparability: collection ledger fingerprint,
external model revisions and live retrieval are not immutable. The exact source
bundle was checked before dispatch. Three cases do not establish general RAG quality.
This is a real RAGET report over reviewed cases, not qualification of new testset generation.

Evidence: [suite](giskard-suite.json), [comparison and Runs](giskard-campaign.json),
[actual provider report and usage](giskard-raget.json), [canaries](canaries.log),
[failed Capture Run](capture-retrieval-empty-run.json).

R0 human baseline, video and owner closure decision remain open. R1 retained
Runs/decisions were not approved, replaced or relaunched. Capture voice, five complete
repetitions, abrupt worker-loss recovery and the unprepared observability case are
not established by this release.
