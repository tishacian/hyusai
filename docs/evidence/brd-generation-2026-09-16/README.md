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
   nodes and three cases. Its unchanged proposal is retained in
   `backend/app/tests/fixtures/brd/pih-generated-proposal.json`.

The fourth response passes the local API proposal/application path, draft
compilation and creation of pending draft Runs for all three case inputs.
Coverage includes BO-1, FR-1–FR-3, D1, R1 and N1. Mapping BO-1 exposed and fixed
a mismatch between imported provenance and accepted coverage sections.

**Not qualified here:** execution of the three generated Skills, actual human
review/resumption, assertion results, publication, second-user consumption,
NorthForge, five successful generations or the deployed candidate image.
Pending Runs in the local regression test are not successful executions.

`provider-attempts.json` records durations, actual provider/model and provider
usage for attempts 2–4. The first request failed before usable counters were
returned. Failed generation output now retains its available usage evidence.
