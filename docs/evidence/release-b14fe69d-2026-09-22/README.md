# Reservation loop — release b14fe69d

Date: 2026-09-22. Live revision `b14fe69d7f596bd2be6f7d4112e6430460aa6a5e`, `revision_verified` true. Rollback `ab96ff7c81fd`. Migration `109_automation_review`. Dump `/srv/agentium-data/automation-review-deployments/2026-09-22-b14fe69d7f59`.

Canaries: 10 passed, 2 skipped. Artifacts `/tmp/iteration-canaries-20260922T152844Z.DLjZLB`. Backend exception matches in the switch window: 0.

## Nawa visual check

Automation `0c7393e2-090b-45b5-b0bb-6c0ebcacd4bc`, Flow page, hard reload.

The reservation loop on the same automation:

- Reservation note: “VAT is still open.”
- Reread: trigger, agent, output
- Correction confirmed against that reread
- A second result of the same automation (`b63de11e`) compared in place
- The page then says the reservation and the later result keep the same object, later result completed

A result from another automation is refused by the service tests (`object_lost`). F4 is not part of this image.
