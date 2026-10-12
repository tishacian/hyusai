# Porte 2 closed — release 7f8c6609

Date: 2026-09-22. Live revision `7f8c6609e9f3bc029ddb97611b81ee205fa02218`. Rollback `f864a9851460`.

Canaries, rerun after the backend was healthy: 10 passed, 2 skipped. The first attempt failed while the backend was still starting.

## Nawa checks

System `df04a96a-2eba-418c-9844-d0a10e878db4`.

- Retrieve, run `b3c8e9ad-769d-434c-9f0b-520515302e42`: 19 hits. Passage is a real IT-software chunk. Source `a11da396-f296-5e64-9b90-4d58a5574eb9`.
- SAP write in the same governed run `700d208c-f917-4b84-8143-85e50a2e59be`: `sealed: true`, `called: false`, reason `unattended`. The run then paused on Approval, decision `0071c07c-e64a-4c48-9878-a98b50f581bd`.
- Work queue [porte-2-approval/validations](https://agentium.papai.ai/work/porte-2-approval/validations) shows that pause, with Approve and Refuse after Review. The decision was left pending.
