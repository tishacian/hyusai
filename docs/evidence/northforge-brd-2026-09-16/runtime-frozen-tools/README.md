# Frozen-tool NorthForge qualification

Engine source: b741c242 (same production code as d5a02f49). Candidate: unchanged
`../runtime-10/candidate.json`. Real configured Showcase provider and retrieval;
canonical Runs use an isolated local database, not production Run URLs.

Five cases executed in 277.85 seconds. Notice and history pass their retained
assertions. Absence and out-of-mandate requests pause at the planner, not the
final human review. The generated human-rejection scenario is not qualified.
Overall pytest result: failed. Harness acceptance is never human acceptance.

Full raw calls/checkpoints remain at `/tmp/brd-northforge-runtime-frozen-arguments`.
This evidence confirms successful read-tool dispatch with frozen schemas, not
R1 completion or repeatable answer quality.

## Explicit rejection retry

The original harness always accepted the final gate, so its rejection assertion
failure cannot diagnose rejection handling. A follow-up selects only the rejection
case and explicitly plans a rejected harness decision; assertions and candidate
are unchanged. It failed before reaching that gate: the synthesis prompt exceeded
32,000 characters. The real retrieval returned 13 results with requested top_k=5,
including large metadata and a 9,627-character document entry. No review occurred.
The wrapper intentionally fills the balanced lane synthesis_k=16 and candidate_pool_k=40;
top_k is not a hard cap on the passages passed to synthesis. This is not evidence
of an ignored retrieval budget. Preserve retrieval recall while correcting the
prompt evidence representation; do not reduce it to five passages as a workaround.

The input itself is still a generated review instruction, rather than a concrete
operator question preceding human review. Both generation and evidence presentation
need correction. Do not weaken the prompt limit, truncate source text silently,
or describe this retry as successful human rejection. Full local evidence:
`/tmp/brd-northforge-rejection-explicit`, 46.20 seconds.
