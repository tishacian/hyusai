# NorthForge BRD revision 2

The original BRD remains unchanged and retained as document
`3a2c54b8-3529-42b3-b05b-68e7781b4197`. Its acceptance paragraph says to
report absent equipment/cause; decision D-1 instead says missing evidence
requires clarification. R-2 also calls a missing passage an unsuccessful answer.
That inconsistency is a requirement-review finding, not proof of the sole cause
of the nondeterministic planner behavior observed in earlier Runs.

Revision 2 clarifies R-2 and D-1: return an evidence gap without fabrication;
the human reviewer may request further evidence. All five acceptance paragraphs,
functional requirements, prohibitions, source numbers and tools are unchanged.
`changes.json` records exact before/after wording and both file hashes.

The two-page DOCX was rendered and both page images inspected without clipping
or overlap. The original document and historical proposals/Runs are not rewritten.

On deployed `89f8e09a`, canonical upload retained the new document as
`ffc6102b-e1c6-4c67-8ce2-38885bdba6f5`, including all five acceptance cases.
The protected-runner principal requested the existing durable generation job
`4605ebf3-c548-4c50-9f29-9ea367de70d0`, with the native planner and the two existing
collection-bound read tools. Generation is in progress, not yet reviewed/applied.
This is API-assisted technical qualification, not a user study.

## Live generation review

Job `4605ebf3-c548-4c50-9f29-9ea367de70d0` completed on release
`89f8e09a`, producing proposal `8573471a-4ed0-42a0-812a-62dc76d14bf5`.
The five-node Flow retains the two authorized read tools and explicit HITL.
Review found that `case-review-reject` sends the review procedure as the
operator objective and asserts only that `draft` exists. The sink does not
map the decision status. This does not establish rejection or retry despite
the case reference answer claiming those outcomes. The generator prompt
already forbids this conflation; instruction alone did not enforce it.

The proposal is retained unchanged and has not been applied or published.
Next correction: validate the generated human-decision test contract before
accepting a proposal, using the existing proposal validation/repair path.
Other case assertions are lexical checks, not semantic acceptance.

### Generated review contract guard (local, not deployed)

Generation now rejects a HITL candidate unless a required string sink field
maps directly to that node's decision_status, and cases linked to the node
assert both approved and rejected with equals. The existing bounded repair
loop receives the validation error. This adds no automatic human decision.
The regression test starts from the exact live proposal above and verifies
missing mapping, absent rejection/approval, unrelated cases, and a forged
model-derived verdict. Service suite: 14 passed; BRD API suite: 9 passed.

This structural guard does not detect every natural-language procedure used
as a business question, prove retry behaviour, or establish a human trial.
The generated candidate and actual Runs still require those checks. Existing
retained proposals and manually authored proposals are not rewritten.
