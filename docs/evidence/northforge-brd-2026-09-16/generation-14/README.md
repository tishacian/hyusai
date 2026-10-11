# Generation 14 — structurally valid, runtime pending

Real provider / WorkspaceJob generation completed in 200.24s after three responses.
Repair addressed malformed case inputs and a missing observations placeholder.
The unchanged candidate retains BRD constraints in the planner goal, objective
and evidence bindings in synthesis, and an explicit human-review node.
The review case now repeats a business question rather than asking the model
to reject its own output.

Five cases are being executed with real configured LLM and synthetic scoped
retrieval through the isolated canonical engine. The harness will reject only
the final review gate for case_review_presence. This is not user acceptance.

Assertions are incomplete: review checks only decision presence; factual cases
check numbers without citation entailment, and mutation refusal is lexical.
Outputs, actual tool selection and the exact recorded rejection must therefore
be inspected separately. No R1 closure or production deployment is claimed.
Runtime evidence: /tmp/brd-northforge-runtime-14.
