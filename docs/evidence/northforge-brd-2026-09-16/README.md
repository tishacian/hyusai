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
