# PROC-SAFE-118 Seal replacement on feed-water pumps

## Document control

Synthetic demonstration data. Nordvane Fluid Systems SA is an invented company and
this procedure exists only for an Agentium product demonstration. It is not a real
safety document and must never be used on real equipment.

| Field | Value |
| Procedure reference | PROC-SAFE-118 |
| Title | Seal replacement on boiler feed-water centrifugal pumps |
| Issued by | Nordvane Fluid Systems SA, Reliability Engineering |
| Version | 6.0, effective 2026-01-05 |
| Applies to | NVX-PUMP-7700 series boiler feed-water centrifugal pumps |
| Related policy | SLA-PLATINUM-04 |

## 1. Restart decision rule

The overall vibration velocity at the drive end decides whether a pump may run.

| Overall vibration velocity, drive end | Decision |
| Below 4.5 mm/s RMS | Normal operation |
| 4.5 to 7.1 mm/s RMS | Operation allowed, plan an inspection |
| Above 7.1 mm/s RMS | Restart prohibited, mechanical repair required first |

A pump reading above 7.1 mm/s RMS must not be restarted, not even briefly and not
even at reduced speed, until the mechanical repair described in section 3 has been
completed and a new vibration reading is below 7.1 mm/s RMS.

A visible seal leak above 0.5 litres per hour requires seal replacement whatever
the vibration reading is.

## 2. Isolation and lockout

Before any seal work begins:

- Isolate the pump electrically and apply lockout tagout, one padlock per person.
- Close and lock the suction and discharge valves.
- Depressurise and drain the casing, then verify zero pressure at the vent.
- Let the casing cool below 45 degrees Celsius before opening.
- Record the isolation in the intervention log with the incident reference.

Seal work on a pump that has not been locked out is a stop-work condition.

## 3. Permanent seal replacement

The permanent repair is a full cartridge seal replacement.

| Requirement | Value |
| Mandatory spare part | SEAL-KIT-3309 |
| Spare part always replaced with it | GSK-1180 casing gasket set |
| Conditional spare part | BRG-2214 bearing pair, only if the inspection in 3.4 fails |
| Certified technicians required | 2 |
| Certification required | Nordvane rotating-equipment level 2 or above |
| Planned duration | 5.5 hours from lockout to handover |
| Post-repair acceptance | Vibration below 7.1 mm/s RMS and leak rate below 0.1 litres per hour |

Step 3.1. Remove the coupling guard and the coupling element, then inspect the
coupling element COUP-3320 for cracking.

Step 3.2. Remove the seal gland and withdraw the cartridge seal without rotating
the shaft.

Step 3.3. Clean the seal chamber and measure the shaft runout. Runout above
0.05 mm requires shaft correction before the new seal is fitted.

Step 3.4. Inspect the bearing pair by hand for roughness and by endplay
measurement. Endplay above 0.12 mm fails the inspection and requires BRG-2214.

Step 3.5. Fit SEAL-KIT-3309 and the GSK-1180 gasket set, torque the gland evenly
to 45 newton metres, then release the lockout and refill the casing.

Step 3.6. Run the pump for 30 minutes and record the acceptance measurements.

## 4. Temporary measure WORKAROUND-GP-02

WORKAROUND-GP-02 is a temporary graphite gland packing arrangement that lets a
pump carry a reduced load while a seal kit is in transit. It uses the consumable
GLAND-PK-0440.

| Limit | Value |
| Maximum continuous duration | 48 hours |
| Maximum duty while applied | 60 percent of nominal flow |
| Approval authority required | Nordvane reliability engineer, level 3 |
| Vibration ceiling while applied | 7.1 mm/s RMS, measured after 30 minutes |
| Permitted leak rate while applied | Up to 3 litres per hour to a bunded drain |

WORKAROUND-GP-02 is permitted only when all of the following are true:

- The pump has been isolated and locked out as described in section 2.
- A level 3 reliability engineer has approved the measure.
- The replacement seal kit is already confirmed in transit.
- The customer has been informed in writing of the duty limit and the time limit.

WORKAROUND-GP-02 is not a repair. The permanent replacement in section 3 remains
due, and applying the temporary measure does not change any commitment under
SLA-PLATINUM-04.

## 5. Handover

The intervention log entry closes with the incident reference, the parts consumed,
the two acceptance measurements, and the names of both certified technicians.
