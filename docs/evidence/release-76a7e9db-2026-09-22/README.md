# Dossier table — release 76a7e9db

Date: 2026-09-22. Live revision `76a7e9dbab3b3d1844e7c2cf4d6e09fce77e1544`, `revision_verified` true. Rollback `b14fe69d7f59`. No migration.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T155357Z.NMDwjC`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, Flow page, hard reload.

The dossier table lists dataset versions. Two versions of the same dossier stay side by side:

- Subscriber base — cleaned — version 6 — proof absent
- Subscriber base — cleaned — version 7 — proof present

Other rows: Cells at risk — 7 days version 4 proof present; Radio cell KPIs version 4 proof absent; Subscriber base — features version 3 proof present; Subscriber base — raw export version 4 proof absent; Subscriber base — scored version 3 proof present.

None of these rows was waiting for a person. A paused run is covered by the service test, not by this page.
