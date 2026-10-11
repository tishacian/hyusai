# Automation edit loop — release 91fa7a05

Date: 2026-09-22. Live revision `91fa7a054557560761fe527a3015ce216b144348`, `revision_verified` true. Rollback `7f8c6609e9f3`. No migration.

Canaries on carakai, after the backend was healthy: 10 passed, 2 skipped. Backend log since the switch: no traceback.

## Nawa visual check

System `df04a96a-2eba-418c-9844-d0a10e878db4`, Flow page, hard-loaded after the switch.

- An explain turn shows `Read: trigger, agent, output, retrieve, approval, sap_write` and does not save.
- A run turn on that same draft starts the existing draft test and shows `Waiting for approval.`
- The page states that publishing and approval stay outside the turn.
