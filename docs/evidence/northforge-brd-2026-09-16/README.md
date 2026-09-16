# NorthForge generation — rejected proposal

Deployed candidate: `f63f1eaf`. Retained document: `3a2c54b8-3529-42b3-b05b-68e7781b4197`.
Generation job: `bf1c59f9-81c4-452e-aed4-0f8a83620007`.
Proposal: `a1849fec-5308-4475-9b0b-754b5778be1e`. **Not applied.**

The generated proposal mixes documentary synthesis with tool investigation:

- A second manual source supplies invented corpus text instead of retrieving it.
- `goal.objective` contains a VariableRef, which the AgentLoop does not resolve there.
- A downstream task reads `completion`, absent from the AgentLoop output contract.
- Cases replace the reference equipment and durations with invented values.
- PIH HR instructions contaminate intervention templates.

The generation prompt now separates documentary instructions from intervention instructions,
clarifies objective binding and the existing output shape, and prohibits invented replacement cases.
Ten generation tests pass. This is not evidence that NorthForge executes correctly.

Further runtime investigation is required before regeneration/application: the current AgentLoop
records only a summary/status/completion from each tool output, whereas these retrieval tools
return `results`. The real source excerpts therefore do not reach downstream synthesis through
observations. Tool query input binding also needs end-to-end verification.

The BRD parser extracts context only from section 1 label/value paragraphs. Verify that the
acceptance cases in the retained document are present in extraction before asking the model
to preserve them. No test oracle or published System was changed to conceal these gaps.

Broader backend gate before this prompt correction: 208 passed, 1 skipped.
Human acceptance, real tool-choice Runs, refusal and publication remain open.

## Follow-up corrections

- Successful tool observations now retain their actual output and canonical invocation ID,
  including retrieval passages and metadata. Failed outputs are not treated as source evidence.
- A runtime test verifies that a per-request objective reaches the read tool as `query`,
  and that retrieved evidence reaches both the following decision and persisted Run output.
- The importer retains the five NorthForge acceptance paragraphs with document positions.
  Previously these paragraphs were absent from the extracted generation input.
- Generation guidance maps `objective` and `query` from the source and consumes observations,
  rather than a nonexistent AgentLoop `completion`.

Validation: import/generation/runtime and import API tests: 47 passed, 1 skipped.
The refined query-binding runtime check also passes (16 runtime tests).
These are local corrections; the deployed proposal remains unapplied. Historical extraction is not rewritten. Re-uploading identical bytes returns the retained
document (SHA deduplication), so it does not refresh extraction. Qualification must use a
reviewed document revision or an explicit re-extraction feature; no silent historical mutation.
A fresh provider generation and real retrieval execution are still required.

## Real-provider generation after evidence fixes

The first new candidate (69 seconds) used the correct source figures and a single ingress,
but was rejected on review: its test inputs contained expected answers and its `done_when`
was prose rather than a list. The retained candidate and provider usage are in `provider-attempts/`.
The next response exposed a dictionary/model mismatch in the new validator; it was fixed,
and replaying the unchanged provider response confirmed that question/input mismatch is rejected.
Replay is validation evidence, not another provider execution.

Server validation now checks the per-case objective binding, a single request ingress,
a list-valued stop condition and identical question/input text. This last check does not
prove semantic absence of answer leakage; human review is still required.

The shared prompt executor no longer silently truncates each input to 4,000 characters.
It preserves the input or refuses a rendered prompt exceeding the existing 32,000-character
limit. A source citation after character 4,000 and explicit oversize rejection are tested.

Scoped backend validation after these corrections: 73 passed, 1 skipped.
No generated candidate in this section has been applied or published to Showcase.
