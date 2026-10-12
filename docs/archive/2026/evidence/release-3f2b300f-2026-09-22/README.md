# Frozen chart and shared proof — release 3f2b300f

Date: 2026-09-22. Live revision `3f2b300fa0e8c466d697f2659607a7abd7e7a450`, `revision_verified` true. Rollback `76a7e9dbab3b`. No migration.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T161914Z.GyTZod`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, Flow page, hard reload.

The frozen chart lists the same dossier versions as the table. It says the shared proof is absent, because this automation is not the published proof.

- Point “Subscriber base — cleaned · 6” opens the dossier and says this point has no result.
- Point “Subscriber base — cleaned · 7” opens the dossier and says result completed.

Work on the published automation `df04a96a-2eba-418c-9844-d0a10e878db4` says “Same proof: present.” The API `automation-proof` for that system returns status present, sealed true, called false, convention absent, gap absent, one source. The conversation tool `read_automation_proof` reads that same identity. A chat turn was not sent.
