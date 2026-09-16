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
