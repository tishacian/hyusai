# Typed Judge: citations from structured evidence

Frozen Run evidence often contains JSON projections, including repeated document
passages in `citations` and `references`. Asking a model to reproduce a short,
unique literal JSON quote can reject an otherwise relevant citation because of
escaping or repeated occurrences. This is a transport-contract failure; it must
not be presented as a negative quality verdict or repaired by fuzzy matching.

When any authorized text source is a JSON object or array, Typed Judge now uses
`source-passages-v1` for every text source in that request. The server presents
the full source as ordered spans of at most 1,000 Unicode characters. Each span
ID binds the protocol, source ID, source digest and exact occurrence. The model
returns `evidence_id` and `passage_id`; the server resolves them to the existing
persisted citation shape: `evidence_id`, `start`, `end`, `quote`.

The canonical validator still verifies the exact frozen source slice. Unknown
IDs, IDs belonging to another source and extra model-supplied quotes or offsets
are rejected. Ordinary unstructured text keeps the unique-literal-quote protocol;
image citations are unchanged. A syntactically valid reference does not establish
that the answer is correct: the rubric, abstentions and human review still apply.

No source selection, snapshot, past evaluation, budget or flow version is
rewritten. The full catalogue counts toward the existing prompt byte and token
limits; an oversized prompt fails before dispatch, without truncation or an
automatic increase. The prompt protocol and response schema hashes change, so
old cached results and calibration profiles cannot silently qualify the new
protocol. Reusing an existing request key with a changed contract is rejected;
run a new evaluation to exercise the new protocol.

Offline verification against the frozen Luma baseline and the 2026-10-22 pilot
reconstructed all source digests exactly. Their new prompts are 31,016 and 29,737
UTF-8 bytes, respectively, below the existing 32,000-byte limit. These checks
validate transport and provenance, not a live provider verdict. After deployment,
run a fresh investigation and inspect its Judge questions, canonical citations,
usage and human gate before claiming the scenario qualified.
