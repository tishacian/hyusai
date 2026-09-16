# PIH generation qualification — 16 September 2026

Input: the synthetic PIH SPARK-089 BRD used in the walkthrough, retained in
`backend/app/tests/fixtures/brd/pih-spark089.docx`.

Calls used the existing `agentium-backend` image and the Showcase workspace's
canonical model resolver. No production System, Skill or publication was
created. The diagnostic script supplied the candidate prompt and generation
options; it did not replace code in the running container.

Observed failures and fixes:

1. `max_tokens` was refused by configured OpenAI GPT-5; fallback Ollama was
   unreachable. The shared OpenAI client now translates the token limit for the
   reasoning model families already recognized by the platform.
2. 10,000 completion tokens were consumed with empty content (93.31 s).
   Generation now requests low reasoning effort for supported model families.
3. A response arrived (50.87 s), but categories, executor and node shapes did not
   satisfy the canonical contracts. Generation instructions now specify their
   exact shapes; Skill category choices are exposed in JSON Schema and the
   existing CaseBody schema is supplied directly.
4. The next response (38.73 s, 8,183 total tokens) produced three Skills, six
   nodes and three cases. This proposal passed draft creation but later failed runtime output validation
   because it prohibited the model metadata returned by the executor.

The fourth response passes the local API proposal/application path, draft
compilation and creation of pending draft Runs for all three case inputs.
Coverage includes BO-1, FR-1–FR-3, D1, R1 and N1. Mapping BO-1 exposed and fixed
a mismatch between imported provenance and accepted coverage sections.

**Not qualified here:** live-provider execution of the three generated Skills,
human participant review, assertion results, publication, second-user consumption,
NorthForge, five successful generations or the deployed candidate image.
Pending Runs in the local regression test are not successful executions.

`provider-attempts.json` records durations, actual provider/model and provider
usage for attempts 2–4. The first request failed before usable counters were
returned. Failed generation output now retains its available usage evidence.

## Runtime investigation

Attempt 5 adopted the required output metadata allowance but disconnected HITL;
the canonical validator rejected it. Attempt 6 received that diagnostic in its
prompt and reached HITL, but its sink read `completion` from the decision node.
HITL returns decision fields, not the upstream deliverable. This also exposed an
uncaught variable-resolution error on resume; the engine now records a terminal
failure instead of leaving a running Run.

Attempt 7 received the additional runtime diagnostic and produced the current
unchanged `pih-generated-proposal.json` fixture. The negative attempt 6 is kept
as `pih-generated-invalid-hitl.json` to prevent recurrence. Generation guidance
now explains both executor metadata and the HITL output contract.

The canonical engine regression executes all three case inputs, records three
Skill invocations, pauses at HITL, refuses resumption without a decision or with
a mismatched decision ID, then resumes after acceptance or rejection without
repeating the model calls. The three Skill **model responses are stubbed** in
this engine test; templates, mappings, executor dispatch and durable Run /
Decision state are real. The intentionally invalid fixture ends in `failed`
after resumption and records `variable_resolution_error`.

Validation: four parameterized BRD runtime tests passed, plus 42 existing DAG /
variable-pool tests. These are not five fresh generation successes: attempts 6
and 7 used explicit diagnostic feedback in the qualification prompt. Automatic
repair and the full deployed, live-provider path remain unqualified.
