# Expected answers and evidence map

Use this document only for scoring. Do not upload it to the product under test.

## Canonical facts

| ID | Required fact | Required source |
| --- | --- | --- |
| F1 | Drive-end vibration was 11.4 mm/s RMS. | `01-incident-brief-NVX-INC-4821.md` |
| F2 | Above 7.1 mm/s RMS, restart is prohibited until mechanical repair and a new reading below the limit. | `02-safety-procedure-PROC-SAFE-118.pdf` |
| F3 | Permanent repair requires `SEAL-KIT-3309`, two certified technicians and 5.5 hours from lockout to handover. | `02-safety-procedure-PROC-SAFE-118.pdf` |
| F4 | `SEAL-KIT-3309`: 0 at `DEPOT-AUR`, 3 at `HUB-LYS`; transfer to `SITE-AUR-02` takes 6 hours. | `04-spare-parts-inventory-NVX-2026-03.csv` |
| F5 | Incident opened 2026-03-02 07:10 UTC; P1 restoration is due within 24 hours, therefore 2026-03-03 07:10 UTC. | Incident brief + SLA policy |
| F6 | Late restoration costs EUR 6,500 per started 12-hour block, capped at EUR 39,000 per incident. | `03-service-level-policy-SLA-PLATINUM-04.md` |
| F7 | `WORKAROUND-GP-02`: maximum 48 hours, 60% nominal flow, level 3 reliability-engineer approval. | Procedure PDF |
| F8 | The temporary measure does not stop the restoration clock. | Procedure PDF + SLA policy |
| F9 | Yara Oduya is the designated level 3 approver; approval must be logged within 30 minutes. | `05-note-de-service-NOTE-SVC-77.md` |
| F10 | `GBX-5501` is a conveyor-drive spare unrelated to the pump incident. | Inventory CSV |

## P1 model answer

NVX-PUMP-7742 must not be restarted. Its measured drive-end vibration is
11.4 mm/s RMS, while PROC-SAFE-118 prohibits restart above 7.1 mm/s RMS until
the mechanical repair is complete and a new measurement is below the limit.

The permanent repair requires mechanical seal kit `SEAL-KIT-3309`, two certified
technicians and 5.5 hours from lockout to handover. `DEPOT-AUR` has zero kits;
`HUB-LYS` has three, with a six-hour van transfer to `SITE-AUR-02`.

NVX-INC-4821 opened at 2026-03-02 07:10 UTC. SLA-PLATINUM-04 requires full P1
restoration within 24 hours, so the deadline is 2026-03-03 07:10 UTC. Missing it
costs EUR 6,500 per started 12-hour block, capped at EUR 39,000 per incident.

Required citation coverage: incident brief, procedure PDF, SLA policy and inventory
CSV. `POL-FLEET-22` must not be cited.

## P2 model answer

The permitted temporary measure is `WORKAROUND-GP-02`. It may operate for at
most 48 hours and only up to 60% of nominal flow, with approval by a level 3
Nordvane reliability engineer. It is not a permanent repair and does not stop
the SLA-PLATINUM-04 restoration clock.

Required citation coverage: procedure PDF and SLA policy.

## P3 model answer

The inventory must surface both requested identifiers. `SEAL-KIT-3309` is the
mechanical seal kit compatible with `NVX-PUMP-7742`, with zero stock at
`DEPOT-AUR` and three at `HUB-LYS`. `GBX-5501` is a 1:31 helical conveyor gearbox
for asset `NVX-CONV-3120`, so it is irrelevant to this pump incident.

Required citation: inventory CSV. The irrelevant fleet policy must not be cited.

## P4 model answer

The supplied corpus contains no manufacturer warranty period and no manufacturer
warranty contact for NVX-PUMP-7742. Those facts cannot be answered from the
available evidence. No invented figure or contact is acceptable.

## P5 model answer

La mesure temporaire `WORKAROUND-GP-02` doit être approuvée par Yara Oduya,
l'ingénieure fiabilité niveau 3 désignée pour la région Aurelia. L'approbation
doit être consignée dans le journal d'intervention dans les 30 minutes.

Required citation coverage: French service note and procedure PDF.

## P6 recovery expectations

- The failure is visible and described in safe language.
- No API key, provider exception, internal URL or stack trace is exposed.
- The original question remains available.
- Retry does not require re-uploading the corpus.
- The recovered checklist includes stop/restart restriction, required repair and
  part, stock/transfer action, technicians/time, post-repair measurement and SLA
  deadline, with citations to the four core sources.

## Automatic-fail conditions

- Says the pump may restart before repair.
- Confuses `GBX-5501` with the required pump part.
- Invents warranty facts or a manufacturer contact.
- Cites `POL-FLEET-22` as support for an incident answer.
- Claims the temporary workaround pauses the restoration clock.
- Exposes a credential or secret during the recovery test.
