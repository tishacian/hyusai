# Edit plan — release 76d4d97e

Date: 2026-09-22. Live revision `76d4d97e8784c0b693c6b198c4d854686f828906`, `revision_verified` true. Rollback `a715fc2f1643`. No migration.

The previous image in this window, `a715fc2f1643`, pinned reasoning effort so gpt-5 returns a JSON plan. This image also reads a single edge object as a one-item list.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T193013Z.OklHq0`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, still unpublished.

The sentence “add a cited search, then an approval before the SAP write” saved a draft whose read-back listed retrieve, approval and sap_write. The outline showed Approval `decided_by` connected to SAP write `decided_by`.

The model also added a decision and a backward edge. Those blocked a draft test. After those two connections were removed and the trigger was connected again, two runs with no person paused on approval: `e85ab13c-c40b-4a2c-92b0-edcecddcffe2` and `e3a5ae54-8576-4507-93c3-a5431bade2bb`. Each checkpoint list is trigger then approval. The SAP write was not called. The sealed flag was not observed. Publish was not used.
