# Unattended write stays sealed — release 65b66219

Date: 2026-09-22. Live revision `65b662192e752e6d15408f72098d88730c239844`, `revision_verified` true. Rollback `76d4d97e8784`. No migration.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T223809Z.8HzHqh`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, still unpublished. The outline still links Approval `decided_by` to SAP write `decided_by`, with Retrieve in the draft.

Draft run `498fff50-41d9-4fe9-8909-cb950233b1ed` is `hitl_pending`. The terminal ran the agent, the retrieve, then `sap_create_po_v1` and printed “Write sealed, not called.” The invocation is `sealed: true`, `called: false`, reason `unattended`. The run then paused on approval. Approve was not used.
