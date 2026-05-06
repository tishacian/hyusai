# Andritz-Oriented Expert Knowledge Capture Demo

This scenario is generic to the platform: Andritz is only the workspace
story used to make the value concrete.

## Demo Goal

Show that Agentium can preserve tacit expert knowledge, not only answer
questions over existing documents. The system starts from a workspace
Knowledge scope, identifies what is missing, prepares a 20-minute expert
interview, evaluates answers during the session, then produces a
reviewable knowledge update proposal.

## Phase 0 Flow

1. Select an Andritz workspace context containing CRM / maintenance /
   SharePoint-derived references.
2. Call `POST /api/v1/knowledge-capture/plans` with:
   - `objective`: capture tacit troubleshooting and offer reasoning;
   - `expert_profile`: senior field or service expert;
   - `duration_minutes`: `20`;
   - `voice_runtime`: `cascade`.
3. Review the generated gaps and agenda.
4. Start the session with `POST /api/v1/knowledge-capture/sessions/{id}/start`.
5. For each expert answer, transcribe through `/api/v1/voice/transcribe`
   or send text directly to `POST /api/v1/knowledge-capture/sessions/{id}/turns`.
6. Use the returned `evaluation` and `next_prompt` as the live relance.
7. Generate the review artifact with
   `POST /api/v1/knowledge-capture/sessions/{id}/proposal`.
8. Accept, reject, or request changes via
   `PATCH /api/v1/knowledge-capture/proposals/{id}/review`.

## Product Framing

The demo should emphasize three user-visible outcomes:

- The system does not pretend the knowledge base is complete; it exposes
  gaps and asks the expert targeted questions.
- The voice experience is fluid enough for a demo because prompts are
  short and TTS is segmented, but precision and traceability remain more
  important than full-duplex showmanship.
- No knowledge is ingested blindly. The output is a proposal with
  captured facts, transcript, open questions and review metadata.

## GPU / Moshi / KAME Lane

The available GPU infrastructure should be used as a parallel spike via
`RealtimeVoiceRuntime`, not as the Phase 0 product dependency. The spike
only graduates if real users show better fluency without worse transcript
correction rate, worse relance quality, or weaker governance.
