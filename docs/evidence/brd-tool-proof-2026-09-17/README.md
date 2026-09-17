# BRD tests → actual tool evidence

17 September 2026. Candidate implementation; live qualification not run yet.
The deployed runtime remains d05e84b1 until a separately recorded switch.

## Behavior

A reviewed case may contain:

```json
{"id":"notice-tool","operator":"invocation_succeeded","path":[],"value":"exact-existing-skill-slug"}
```

The server checks completed, error-free invocations on that completed Run.
It returns their canonical identifiers. Mentioning an invocation in output,
copying another Run's observations, a failed call or the internal executor name
of an authored wrapper does not satisfy the check. Without Run evidence the
check is unevaluated. Human-review waits remain pending. This proves the call,
not its arguments, answer quality, absence of external effects or human approval.
Only direct invocations are examined; child-System aggregation is not claimed.
No data migration, new permission, flag, runtime or orchestration service.

Generation instructions now offer this operator for existing tools and explain
that factual assertions remain necessary. They ask for relevant case links for
business outcomes, rules and prohibitions as well as functional requirements.
This is guidance, not proof that a future provider response covers every row.
Unsupported requirements remain visible; the original document and proposals
are never rewritten to improve their coverage percentage.

## User path / Parcours

**EN:** Open a generated case's Run from the Flow test results. In “Understand
this result”, “Test case checks” shows each server verdict. Open its invocation
to inspect the actual input/output and model execution. A comparison presents
the same links under the reference or candidate; each points to its own Run.
Missing evaluation is separate from these checks and from a human decision.

**FR :** Depuis les résultats de test du Flow, ouvrir le Run du cas généré.
Dans « Comprendre ce résultat », « Contrôles du cas de test » présente les
verdicts serveur. Ouvrir l'invocation pour inspecter ses entrées/sorties et le
modèle exécuté. Dans une comparaison, chaque preuve conserve son Run de référence
ou candidat. L'évaluation indisponible et la décision humaine restent distinctes.

## Qualification

- Backend: 127 passed, 3 opt-in real-provider tests skipped. Includes the actual
  canonical DAG with controlled planner/retrieval responses and a frozen authored
  tool, persisted invocations, campaign API checks, wrong-Run/failure/spoof tests,
  and the pending human gate. Provider quality is not established by those tests.
- Frontend: 1,513 tests passed, including explicit candidate ancestry in the
  canonical navigation resolver. i18n, navigation, chrome and AOT production
  build are recorded in the adjacent logs.
- Four local renders use the actual Angular components with fixture API data:
  Run/comparison × FR/light/1280 and EN/dark/390. The fixture adapts signal inputs
  for JIT rendering; production inputs are checked by the AOT build. No console
  errors or page overflow; actual anchors point to the candidate Run despite a
  reference-Run route context. These are layout checks, not live execution proof.

[Run EN/dark/mobile](run-en-dark-390.png) ·
[Comparison FR/light/desktop](comparison-fr-light-1280.png)

## Remaining R1 acceptance

Read-only inspection of retained NorthForge proposal
86658a91-fc74-4226-8429-a3ec3fe1854e confirms BO-1, R-1, R-2, R-3, N-1 and N-2
still have no linked test cases. Their operations exist; this is a test coverage
gap, not evidence that all requirements are implemented or satisfied.
Its six pending Runs are untouched. A fresh, separately reviewed generation,
real tool-choice cases, explicit human refusal/resumption, publication and a
second authorized consumer remain to qualify. No old Golden Run is relaunched
or approved by this change.
