# Provider and rights checks — release ab96ff7c

Date: 2026-09-22. Live revision `ab96ff7c81fdbd6a4f4485dca466caca3fcb8bd1`, `revision_verified` true. Rollback `3fd6fb26243c`. No migration.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T134105Z.hXV9qN`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, Flow page, hard reload.

The preparation path says **Not ready**:

- Model — Ready (`workspace_llm_v1`)
- Provider — Ready (`openai`)
- Source — Ready
- Indexing — Not applicable
- Rights — Ready
- Runner — Not checked

The provider name comes from workspace routing. Rights use the same run authority as a system run: this caller is allowed. The runner stays unchecked because no worker heartbeat exists to read. F2 is not closed.

Work on the published automation `df04a96a-2eba-418c-9844-d0a10e878db4` shows **Start the published automation** and **Export the proof package**.
