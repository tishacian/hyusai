# Run outcome truthfulness — local qualification

Candidate source: `codex/brd-system-roadmap`, based on `91beb3d0`.

- Shared Run/System/Capability card: unset or unqualified value is absent, including
  historical numeric defaults; known estimated/declared zeros remain visible.
- Efficiency requires a known value and a positive finite recorded cost.
- Recorded cost does not certify ledger coverage or actual billing. Invocation
  catalogue calculations are explicitly labelled; unknown default zeros are absent.
- Currency/precision reuse the existing formatter. Invalid numbers remain absent.
- Reactive input fixes stale summaries after polling or changing the selected Run.
- FR/EN labels, existing tokens and API contracts; no NAWA or permission changes.

1,502 frontend tests pass. Five targeted tests additionally pass after the final
nullable input initialization correction. i18n (8,057 keys), navigation, chrome and
production build pass. 19 existing backend cost/provenance tests pass. The build
retains existing unrelated warnings. No backend code or migration was changed.

The existing live observability canary now checks the absent-value card against
the canonical Run when that card is rendered. Its live result and manual captures
must be recorded against the deployed candidate, not inferred from these unit tests.
