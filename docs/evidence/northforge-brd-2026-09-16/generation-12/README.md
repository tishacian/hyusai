# NorthForge generation 12 — runtime qualification pending

Real configured-provider generation completed through WorkspaceJob in 57.39s.
The retained proposal is unchanged. It correctly binds the original operator
question and observations to the synthesis template. Five acceptance cases exist.

Inspection still finds a procedural question in case_review_reject_recorded:
it asks the model to review/reject rather than supplying a business question for
an external reviewer. Citation assertions are lexical (e.g. Evidence), not proof
of source entailment. These limitations prevent acceptance based on generation
success alone.

The five unchanged cases are under isolated local-engine qualification with the
real configured LLM and scoped synthetic retrieval. The harness rejects only the
final review gate for case_review_reject_recorded; it never answers planner
clarifications. Harness decisions are not human acceptance. No production System
or Run is created. Runtime evidence directory: /tmp/brd-northforge-runtime-12.
