# Qualified outcome readouts — 4baa9f5d

Runtime `4baa9f5d1487161770c715ee393dd92eb3c8ddb3` is deployed from published
`demo/agentic`. The preceding c19d30e8 corrected value/cost semantics; this
release also corrects its narrow layout and verbose ledger captions.

## Release checks

- [Local gates](../outcome-card-responsive-2026-09-17/README.md): 1,503 frontend
  tests, i18n (8,057 keys), navigation, UI chrome and production build pass.
  Backend unchanged from the [19 cost/provenance tests](../outcome-card-2026-09-17/).
- [Three VM-built immutable images](vm-build.log), tag `4baa9f5d1487`.
  Build window: 02:00:22–02:09:03 UTC on 17 September.
- [Idle workers before switch](pre-switch.log), [deployment](switch.log),
  [healthy application services](runtime-health.log), zero startup exception
  matches, [exact public frontend/backend revision and HTTP 200](public-verification.log).
- [Carakai](canaries.log): **10 passed, 2 intentional local-contract skips**.
  The existing observability canary now checks the five readouts at 390 px.
  Runner artifacts: `/tmp/iteration-canaries-20260917T021050Z.6tg2zk`.
- [Worker Giskard SDK 2.19.2 fixture](worker-sdk.log): passed; three cases,
  four mocked judge calls. **This is not a live provider campaign.**

Image IDs:

| Image | ID |
|---|---|
| Backend | `sha256:b6b661c4027ce2d705df9f3d74341f13f6eec9be2a9ecd3cdfca4368ce781df1` |
| Worker | `sha256:d6baefb3112833c9ef81e04b03e9aa7c5262ac94ee402653bd44037913ee1894` |
| Frontend | `sha256:e5244abb7dbf162ee931ff76c9168a8ab545365ebb9b2658ea24de71309b8838` |

Immediate rollback: `c19d30e8133c`; earlier stable runtime: `ab15d204a73e`.
No migration, flag activation, permission change or native NAWA theme change.
Rollback preserves subsequent writes. VM build evidence also remains under
`/srv/agentium-data/roadmap-deployments/2026-09-17-4baa9f5d1487`.

## Real browser checks

Authenticated Chrome, owner account, Agentium Showcase. No fixture interception.
The public revision was rechecked after the manual smoke.

### Absent value and recorded cost

Retained Run `9b73e4e5-083b-4a8c-b47b-0e52bbbebdf3` still belongs to execution
runtime **4771f15b**. Its [raw outcome](retained-outcome.json) is unchanged:
`value_source=unset`, historical numeric value/efficiency zero, cost 0.012.
The card now renders absent value and efficiency as **—**, and recorded cost as
**$0.012 / 0,012 $US**. Catalog-tariff amounts say Calculated / Calculé;
coverage and provider billing remain unverified.

- [English, dark](en-dark.png), [French, light](fr-light.png),
  [French at 390 px](fr-narrow.png), all visually inspected.
- All five narrow readouts have width/scrollWidth **129/129 px**:
  [dimensions](fr-narrow-metrics.json). This qualifies the card, not every
  responsive surface in the product.
- Native ledger disclosure opens/closes with Enter; [checks](manual-checks.json).
- English, dark mode and the default viewport restored after qualification.

### Work → new Run → numerical check

One fresh execution from the existing published Operational Analysis application:
[Run 5369c2b1](https://agentium.papai.ai/runs/5369c2b1-5396-4238-906f-80826da0c9ef?systemId=15b05919-c93b-4648-8581-8a41cbe2fae6).
Started 02:20:33 UTC, completed in **32.54 s** on **4baa9f5d**.
Published Flow `e997f4e4-3b51-4eef-9481-389f3a9afae4`, hash
`f1cdd9b755357f0960c334129f09e9106c63c4a49d9fa1937829dc01ae59d14d`.

The [Work result](work-result.png) and its [exact Run](new-run.png) report four
orders, 120 planned minutes, 155 actual, +35, three late orders and NF-04 +25.
The [numerical-check invocation](new-run-check-dom.txt),
`7a22fa3a-051d-4a4c-8068-4febe369d7a4`, has
`numerical_reference_passed=true`, `human_validated=false`, `economic_impact=null`.
The separate semantic evaluation is skipped; it is not reported as passed.
Effective model: OpenAI `gpt-5-2025-08-07`; 2,202 provider-reported tokens.
Recorded $0.012 is catalog-calculated, not an invoice or verified saving.

### PIH and Quality

- [PIH Skill](pih-skill-dom.txt): prompt, execution editing and effective OpenAI
  model configuration remain visible. No Skill settings were changed.
- [PIH Flow](pih-flow.png): three real nodes, saved draft r3 and published v1
  shown separately. Its System Design summary still lists a generic four-stage
  RAG pipeline ([observation](pih-system-dom.txt)); use the concrete Flow for
  the demonstration. This discrepancy remains to fix, not a qualified mapping.
- [Quality selection](quality-selection.png): choosing task-success 20 for
  `2d630608-a541-408d-bfe0-b55aadb5c734` opens that exact
  [Run and its examined passages](quality-run.png). Evaluation remains partial.
  This historical execution retains runtime **63d9afa7**, not 4baa9f5d.
  No evaluation or decision was recreated. Its historical APPROVED/100% outcome
  must not be read as a new human approval.

No retained R1 Run, human decision, generated draft or publication was changed.

## Open acceptance

The [intermediate visual failure](../release-c19d30e8-2026-09-17/README.md)
is retained; final card screenshots above supersede its layout qualification.
The new Work response is French under an English shell because the published
example prompt controls its language; UI locale is not a model-output contract.
No claim is made that this smoke qualifies every translation or System summary.

QuickTime recording remained disabled; an alternative capture requires the
pending user response. No new video exists. Ten formative user sessions remain
unperformed, and Thibaud's R0 closure decision is pending. This release does not
close R0, R1 or the remaining roadmap by itself.
