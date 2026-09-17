# System Design reads the same draft as Flow Builder

Live inspection on 4baa9f5d found PIH Design presenting the published RAG form,
while Flow Builder presented draft r3 with three nodes. Read-only database checks
confirm this is a real version difference, not a corrupt compatibility mirror:

- System: a021f6c3-fed5-4940-a3e1-53d5a7617f57.
- Published v1: a4c67100-ecf2-421d-8be0-3038a3a8cb80, source `form`, six builder nodes.
- Draft r3: source `flow`, Transaction excerpts → PIH Document Summary Demo →
  Factual summary; SHA a622ed47e43aefb08ac432ed6b2046d53dc83abf824ecced72102624787b03a8.

Design now reads the canonical server draft, labels both draft revision and
published version, and reuses the existing graph summary. Overview and Run
snapshots remain published/historical projections. A failed or mismatched draft
read is explicit and retryable, never a fallback to a generic pipeline. The
existing frontend publication switch now follows the server's graduated default;
explicit opt-out remains false. No stored workspace flag is changed.

Local checks: 1,506 frontend tests; i18n 8,068 keys, navigation, UI chrome and
production build pass. New tests cover actual draft vs published identity,
failed/wrong-workspace reads and opt-out/specialist/360 projections. The existing
observability canary additionally compares Design with canonical draft node labels
and version identity. Backend unchanged; no dependency or migration added.

[Reference lock](../../design/brd-system-ui-reference-lock.md#system-design--draftpublication-boundary-17-september).
Live deployment and final screenshots must be recorded separately before this
correction is described as qualified in production. Retained R1 decisions and
all published versions remain untouched.
