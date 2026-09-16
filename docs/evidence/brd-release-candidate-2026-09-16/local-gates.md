# R1 candidate local qualification

Code candidate: fe0f34fe (subsequent migration-test harness and evidence only).

- Frontend unit suite: 1,466 passed, zero failed/skipped.
- Scoped backend suite: 201 passed, one skipped, 104.82 seconds. Includes BRD,
  Flow Workbench/publication, evaluation campaigns, executable contracts,
  AgentLoop, authored executors and native retrieval wrappers.
- i18n: 7,981 keys, 22 domains; passed.
- Navigation and UI chrome checks: passed.
- Migrations 106/107: upgrade, unique constraints, nested-transaction violations
  and downgrade passed on an isolated PostgreSQL 16 database in 4.22 seconds.
  The disposable database was named brd_qualification and was not production.
- Production build: in progress when this record was started; result pending.

These gates do not close R1. Five full live repetitions, complete PIH/NorthForge
acceptance, worker recovery, second-user publication and formative user sessions
remain outstanding. R0 technical qualification remains on deployed SHA 7532d449;
its human baseline remains open. No remote CI exists; these are local gates.
