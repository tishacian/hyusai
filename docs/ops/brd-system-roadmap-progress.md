# BRD → System roadmap — implementation evidence

Base: `origin/demo/agentic` at `9494149ad1ade0dc9da713588590d1ec01a9d2da`.
Implementation branch: `codex/brd-system-roadmap`.
Scope: [accepted roadmap](../agentium-delivery-roadmap.md).

## Implemented in this change

- Studio: selected page and warning pill use the primary foreground on their
  existing semantic backgrounds. Layout, branding and native NAWA styles are unchanged.
- BRD import: reads at most 5 MiB plus one byte; rejects DOCX archives above
  50 MiB expanded or 1,000 parts before Word parsing. Returns the exact upload's
  SHA-256 and size. Reports duplicated references, missing descriptions,
  generated references, and truncated rows/text instead of silently implying a
  complete extraction. The existing import route and authoring permission remain.
- NorthForge Operational Analysis: calculates and checks the largest overrun,
  `NF-04`, `25` minutes, alongside the existing 120/155/+35/three-late reference.
  The output schema and English/French reference copy include it. Existing
  published versions are not rewritten by this source change.

## Local verification — 2026-09-16

| Check | Result |
|---|---|
| BRD parser, import API, Operational Analysis | 17 passed; 1 skipped (template DOCX absent in worktree) |
| Frontend unit suite | 1,459 passed, 0 failed, 0 skipped; all 157 files |
| `check:i18n` | Passed, 7,946 keys |
| `check:nav-links --fail-closed` | Passed |
| `check:ui-chrome` | Passed |
| Production frontend build | Passed; existing budget/CommonJS warnings |
| Studio foreground/background rendering | Local Chromium component fixture inspected in light and dark; not a live Studio canary |

The first monolithic unit invocation exhausted local temporary disk space.
The full suite was rerun in groups of eight files using the existing
`FLOW_UNIT_FILTER`; all groups passed. No test or assertion was removed.
Polars 1.31.0 was installed into a temporary test dependency directory, not a
production environment.

## Release and remaining work

**No roadmap release is closed or deployed by this change.**

R0 remains open: the live Showcase contains no System named Operational Analysis
(read-only database check on 2026-09-16). It needs a scoped installation and an
explicit publication through canonical services, then Work and Studio canaries
on the candidate SHA. Remote CI execution, captures of the live journey and the
adoption baseline are not established here.

R1 is not implemented: returning a document fingerprint does not persist the
file, create a System, or provide requirement-to-Run traceability. Server-owned
proposals, reviewed/idempotent application, the two reference flows, tests,
publication and the authoring UI remain to build.

R2, R3, R5 and R6 remain open. R4 has only the additional numerical reference
above; its application lifecycle, HITL, comparative execution and external-effect
guarantees are not qualified by this change. Existing observability work retains
its separate qualification status.

No default adoption flag switch, customer activation, native NAWA change,
database migration, or replacement of a published System is included.
