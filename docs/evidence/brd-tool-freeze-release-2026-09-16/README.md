# AgentLoop frozen-tool corrective release

Candidate: d5a02f49ae9c1083a1689fcc96743306b9b2d40d, pushed on demo/agentic.
Local gates: 1,466 frontend tests, 147 scoped backend tests, i18n, navigation,
UI chrome and production build pass. No migration. All three images were built
on omnirag-demo with the optional Giskard worker SDK preserved (offline qualification
passed). The six application containers now use tag d5a02f49ae9c. Public build-info
verifies the exact SHA, homepage returns 200, backend/frontend are healthy and
startup logs contain no traceback or exception. Storage checks passed.
Post-switch carakai canaries: **10 passed, 2 intentional local-fixture skips**,
2.2 minutes; exact SHA asserted. See `canaries.log`. Artifacts on carakai:
`/tmp/iteration-canaries-20260916T144757Z.dVfwis`.
Manual authenticated smoke is pending reconnection in Chrome.

Image digests:
- Backend: `sha256:c76ef7a7e98024fe17feed012c60db9c87358633ac673c03540dd2a87e7d1040`.
- Worker: `sha256:5a3c6fac4d693a8ae592efcbfcee81210ce991cc98daaafb111f0d368f7b7c33`.
- Frontend: `sha256:f19734dba215b85da330b0e9d8c613a67716056a2ee241885328c9728db20338`.

Previous runtime: 7ab88007328c5e3a2cf5eaf6663e7d9c00eec927. New tool_contract
readers are required after these contracts are persisted; rollback must preserve
compatible readers, never restore a database over later writes.

NorthForge functional acceptance remains open: see ../northforge-brd-2026-09-16/runtime-frozen-tools/.
This delivery fixes contract preservation and argument binding, not the remaining
planner clarification/refusal and human-review scenarios.
