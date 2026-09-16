# Incident brief NVX-INC-4821

**Synthetic demonstration data.** Nordvane Fluid Systems SA, Helioforge Paper Mill,
every person, site, identifier and figure in this file is invented for an Agentium
product demonstration. It is not customer data.

| Field | Value |
| --- | --- |
| Incident reference | NVX-INC-4821 |
| Severity | P1 |
| Asset reference | NVX-PUMP-7742 |
| Asset description | Boiler feed-water centrifugal pump, duty line B |
| Site | Site Aurelia North, site code SITE-AUR-02 |
| Customer | Helioforge Paper Mill |
| Service contract | SLA-PLATINUM-04 |
| Opened at | 2026-03-02 07:10 UTC |
| Duty dispatcher | Ines Kallbrenner |
| Lead field engineer assigned | Tobias Renn |
| Status at brief time | Open, pump stopped by plant operator |

## What happened

At 06:52 UTC on 2026-03-02 the plant operator at SITE-AUR-02 reported a visible
process-water leak at the drive-end seal of NVX-PUMP-7742 and a rising noise
level on duty line B. The operator stopped the pump at 07:04 UTC and opened
incident NVX-INC-4821 at 07:10 UTC.

Helioforge Paper Mill switched duty line B to the standby pump NVX-PUMP-7743,
which can carry only 60 percent of the nominal boiler feed-water flow. The mill
is therefore running at reduced production while NVX-INC-4821 is open.

## Measurements taken on site

| Measurement | Value | Taken at |
| --- | --- | --- |
| Overall vibration velocity, drive end | 11.4 mm/s RMS | 2026-03-02 06:58 UTC |
| Seal chamber leak rate | 1.9 litres per hour | 2026-03-02 07:02 UTC |
| Bearing housing temperature | 74 degrees Celsius | 2026-03-02 07:02 UTC |
| Suction pressure | 3.1 bar, nominal | 2026-03-02 07:02 UTC |

The vibration reading of 11.4 mm/s RMS was taken with a calibrated handheld
analyser, serial NVX-VIB-0119, and confirmed by a second reading two minutes
later.

## Constraints reported by the customer

- Helioforge Paper Mill requires the boiler feed-water duty restored before the
  next paper-machine grade change.
- The mill will not authorise any work that requires opening the boiler drum.
- The mill accepts a temporary reduced-duty arrangement if it is approved in
  writing by Nordvane Fluid Systems SA.

## Open questions for the field-service team

1. Can NVX-PUMP-7742 be restarted as it is?
2. Which spare parts are required, and where are they held?
3. What does SLA-PLATINUM-04 require, and by when?
4. Is a temporary measure allowed while the parts are in transit?
