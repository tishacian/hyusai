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
