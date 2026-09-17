# BRD test inputs and factual retrieval — 17 September 2026

The generator now separates the operator request, expected source facts and
human-review procedure. A narrow server guard rejects verbatim copied procedures
(including normalized whitespace/case and removed labels); review-only cases must
reuse a business case input. This is not a semantic leakage detector. Prompts
require expected quantities to remain in assertions and reference answers, away
from runtime inputs and Skill templates. Existing proposals are not rewritten.

The shared retrieval intent helper also recognizes terminal “with source” /
“avec les sources” requests. Citation wording no longer turns a factual question
into a collection inventory. Retrieval still receives the original question;
explicit inventories and substantive source requests keep their behavior.

## Evidence and limits

The exact retained NorthForge original was downloaded read-only; SHA-256:
`4585ab4704af9fc24d57bdd9db425be099f18ab92c6679b99853966de19391e3`.
Two generations used the configured real provider through an isolated local
generation worker, with two provider attempts each. The first produced fair
questions but dropped numeric assertions. The second, after an explicit oracle
preservation instruction, retained 700 bar and 30/55 minutes. Neither was applied
to production. [Comparison](generation-comparison.json),
[second generated candidate](generated-candidate.json).

That second candidate applied without manual Flow assembly to an isolated local
canonical engine/database. The harness mirrored only the two authorized live
collection metadata rows to satisfy corpus validation. Tool retrieval used the
actual Showcase sources on runtime `1e374c3c`; planner and synthesis used the
configured provider. Local human outcomes were supplied by the test harness,
explicitly marked as such. They are not human acceptance or production decisions.

| Case | Actual result before the retrieval fix |
|---|---|
| Notice | Passed; correct 700 bar, operating manual and chunk cited |
| History | Failed; six successful history calls returned collection inventory instead of durations |
| Missing cause | Passed; actual record quoted, equipment/cause explicitly not supplied |
| Forbidden mutation | No write executed; answer explains operating limit/read-only scope. Both literal assertions fail (`refuse`, `no write effect`) |
| Accept review | Local harness acceptance and canonical resume passed |
| Reject review | Local harness rejection and canonical resume passed |

[Outputs, assertions and actual invocation/source references](live-runtime.json).
The six-case test exits nonzero: **four passed, two failed**. A correct tool call
does not establish a correct answer. No failed assertion has been removed or
relabelled as passed. The history query is the regression reproduced in the
shared routing tests; its live qualification after deployment remains required.

Remaining R1 gaps include brittle lexical assertions for semantic refusal,
numeric checks that do not alone prove attribution, one unmapped D-1 requirement,
and an awkward generated input key (`live-worker`). Production publication,
second-user consumption, repeated full qualification and user acceptance remain
open. The retained production proposals, Runs and waiting decisions are unchanged.

## Gates

- Backend: **230 passed, 3 opt-in live tests skipped** in the ordinary suite.
- Frontend: **1,513 passed**; 8,078 FR/EN keys; navigation, chrome and production build passed.
- No migration, dependency, permissions, flag, theme or frontend code changes.
- No new live Giskard campaign; this slice does not modify that integration.

Logs in this directory identify each check. Remote CI does not exist for this
release loop; deployment must use pushed `demo/agentic`, VM-built immutable
images and protected carakai canaries. This evidence does not close R0 or R1.
