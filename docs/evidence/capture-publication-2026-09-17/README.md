# Capture publication continuity — 17 September 2026

The publication surface now opens the indexed record in the shared authenticated
document preview. Source URLs carry the recorded collection and filename. Reading
an older proposal repairs its returned links without rewriting stored history.

Publication requires an accepted proposal; the frontend no longer accepts a
proposal as a side effect of pressing Publish. The existing server policy for
workspaces configured without expert review remains unchanged. Reopening a
published session restores its receipt. After a lost publication reply, the
frontend reads the persisted proposal before reporting failure and never issues a
second publication POST by itself. Late responses cannot restore another session
or workspace's receipt.

The shared modal now uses the existing CDK focus trap, an accessible name, and
Escape dismissal. Inline document views and NAWA brand styles are unchanged.

## Validation

- Backend: 162 service/API tests passed. URL escaping and historical payload
  preservation are covered.
- Frontend: 1,493 tests passed, including explicit review gating, a fresh successful
  publication, receipt recovery, and stale session/workspace responses.
- i18n: 8,048 keys; navigation and UI chrome guards passed.
- Production build and Angular AOT compilation passed.
- Local AOT component views: French/light desktop and English/dark 390 × 844.
  These use a synthetic local receipt and text response, not a live Capture
  publication. Opening, keyboard focus, Escape dismissal and return focus are
  checked in Chrome. Screenshots: `preview-fr-light.png` and
  `preview-en-dark-mobile.png`.

Design reference: retain Capture's existing success surface and Cockpit tokens;
reuse the same document inspector used by La Scène and report provenance. The
Refero copywriting guide's action/object rule is met by the existing “Open the
published record” label. No new visual system, theme or navigation engine.

## Remaining R2 acceptance

This correction does not close R2. Publication-to-new-conversation handoff still
needs to select the authorized collection and show its scope. A real corrected
voice capture, text parity, retrieval in a fresh conversation, five repetitions,
and formative user sessions remain to qualify.

The recovered receipt proves a committed publication; it is not a guarantee
against duplicate ingestion across a backend crash or concurrent publication
requests. Accepted-report edits also need their review validity examined across
all mutation paths before claiming that approval always covers the latest content.
