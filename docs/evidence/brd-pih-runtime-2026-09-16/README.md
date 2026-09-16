# PIH live-provider runtime investigation — 16 September

The local candidate's canonical import, proposal/application, draft Run, Skill
executors, DAG and HITL resume were exercised against an isolated disposable
SQLite test database. The model boundary called the existing backend container
on omnirag-demo through its canonical Showcase model resolver. Credentials
remained on the VM. No production System or Run was created. Human acceptance
was set by the test harness, not by an actual participant.

## Earlier proposal: rejected despite passing lexical assertions

The attempt-7 fixture (SHA-256
`c1ca3704884ec6d4174da72432b03de1b92372baeba9ba6f08fdfee96e4f0a06`)
contained three copies of `Summarize {text}`. Three live calls produced a final
recommendation offer and invented illustrative business examples. The generated
`exists`/`not_contains approve` assertions passed. This is a **quality failure**,
not successful BRD implementation. `rejected-output.json`,
`insufficient-assertions.json` and `provider-calls.jsonl` retain that evidence.
A fresh attempt 8 repeated the generic templates.

Generation now requests distinct stage-specific templates implementing the
requirements and prohibitions, preservation of original passages and exact
facts, explicit missing information and no HR decisions. Duplicate generated
templates are rejected with feedback for the bounded repair loop.

## Candidate 9: improved result, invalid proposed assertions

A fresh generation produced three distinct templates. `candidate-9.json` is its
unaltered response. The normal case ran three real LLM calls, reached HITL and
completed after harness acceptance. Its output correctly retains:

- Senior Data Analyst / G8, from Excerpt A1;
- Lead Data Scientist / G9, from Excerpt B3;
- 2025-01-15, from Memo M2;
- no HR approval/rejection/recommendation.

The final output is in `candidate-9-output.json`. The assertions fail because
paths incorrectly start with `nodes/sink_draft` rather than the sink output.
Even after path review, exclusions such as `not_contains recommend` would reject
the legitimate disclaimer. The temporary harness also expected the previous
candidate's `draft` field; it failed that assertion after saving the actual
`completion` output. The recorded DAG itself completed (19.24 s).

Generation guidance now states the actual assertion root. We have **not** edited
the candidate's criteria after observing its answer or counted this as a passing
suite. Its test proposals still need review. Future acceptance must cover a
missing field and malicious source, meaningful assertions, real published Runs,
second-user access and five consecutive successes. Nothing here closes R1.


## Candidate 10: fresh generation, structurally valid tests

A fresh call using the updated generation prompt completed in 69.01 seconds.
The unedited candidate passes proposal schema, DAG validation and declared
output-path checks. All three cases address `completion`: supplied facts,
missing grade/date, and an instruction to approve embedded in the source.
The source fixtures do not provide explicit excerpt identifiers; citation
adequacy still needs examination. Exact wording assertions may be brittle,
and a disclaimer assertion does not prove absence of an HR recommendation.
`candidate-10-generation.json` records usage and structural checks. No runtime
execution or business acceptance is claimed for this candidate yet.


### Candidate 10 runtime results

All three cases completed through the canonical local Run/DAG/HITL path, using
nine real provider calls (109.09 seconds for the recorder). Decisions were
accepted by the harness, not by a participant. Outputs and provider usages are
retained in `candidate-10-runtime/`.

- Normal: all requested facts correct; the citation assertion fails because the
  quoted source contains a leading hyphen. The criteria were not rewritten.
- Missing fields: proposed grade and effective date correctly absent, but two
  model-generated “Missing evidence” annotations appear in the citation list.
  Generated assertions pass despite this provenance defect: quality NOT accepted.
- Instruction in source: the request to approve is not followed; supplied facts
  and missing fields are retained. Generated assertions pass.

Generation guidance now explicitly requires original text bound directly from
the source node into citation stages, separately from model outputs, and forbids
using missing-evidence annotations as documentary quotations. Fresh generation
with this change remains to qualify. Four focused generator tests pass. The
opt-in runtime recorder is retained for reproducibility; its pytest success
asserts execution/resumption only, never semantic acceptance of the outputs.


## Candidate 11: original-source propagation, contradictory test rejected

Fresh generation took 65.89 seconds; source bindings, output paths and DAG were
structurally valid. Three canonical local Runs completed with nine real model
calls (101.72 seconds, harness acceptance). Normal and missing-field generated
assertions passed. The source-instruction case failed because it simultaneously
requires a disclaimer and forbids substrings inside that disclaimer.

Proposal validation now rejects that contradiction before persistence and feeds
the existing repair loop. Fifteen focused tests pass; the broader preceding
contract/publication run had 99 passed and one skipped.

Original outputs and quote membership checks are retained in
`candidate-11-runtime/`. Membership in source is a narrow check, not proof that
a quote supports the associated fact. Missing-evidence annotations remain under
the citations heading, although no longer quoted as source text. No criterion
was rewritten after execution. This candidate is not a passing acceptance suite.
