# Agentium pump-incident demo kit

A ready-to-upload knowledge corpus, an exact demo script, expected answers, and a
reproducible ROI model for one realistic business scenario:

> A field-service team at **Nordvane Fluid Systems SA** must decide how to restore
> boiler feed-water pump **NVX-PUMP-7742** at **Helioforge Paper Mill** after P1
> incident **NVX-INC-4821**, without breaching service-level policy
> **SLA-PLATINUM-04**.

No single document answers that. The measurement is in the incident brief, the
restart rule is in the procedure PDF, the deadline and penalty are in the
service-level policy, and part availability is in the inventory CSV. That is the
point of the demo.

**All data here is synthetic.** Every company, person, site, identifier, price and
date was invented for this kit. It contains no customer or confidential data, and
no figure in it is an Agentium price.

The presenter's click-by-click script lives in
[`docs/agentium-pump-incident-demo-runbook.md`](../../docs/agentium-pump-incident-demo-runbook.md).
Read that first if you are about to present. This README covers the files.

## Upload these files, in this order

Open **Knowledge** in Agentium and drop the files into the upload area. The
dropzone accepts PDF, TXT, MD, DOCX, CSV and JSON; every file below is inside
that list and inside the backend's accepted set.

| # | File | Format | What it contributes |
| --- | --- | --- | --- |
| 1 | `demo-assets/pump-incident-demo/upload/01-incident-brief-NVX-INC-4821.md` | Markdown | The incident, the asset, and the 11.4 mm/s vibration measurement |
| 2 | `demo-assets/pump-incident-demo/upload/02-safety-procedure-PROC-SAFE-118.pdf` | PDF, real text layer | The restart rule, the repair requirements, and the temporary measure. Used for the visual citation and source preview. |
| 3 | `demo-assets/pump-incident-demo/upload/03-service-level-policy-SLA-PLATINUM-04.md` | Markdown | The restoration deadline and the service credit |
| 4 | `demo-assets/pump-incident-demo/upload/04-spare-parts-inventory-NVX-2026-03.csv` | CSV | Structured stock levels, locations and transfer lead times |
| 5 | `demo-assets/pump-incident-demo/upload/06-unrelated-fleet-vehicle-policy-POL-FLEET-22.md` | Markdown | **Scoping control.** Deliberately unrelated. It must never support an answer about the incident. |
| 6 | `demo-assets/pump-incident-demo/upload/05-note-de-service-NOTE-SVC-77.md` | Markdown, French | Upload just before the French act. Names the level 3 approver and the logging delay. |

Files 1 to 5 can be selected together in one drop. File 6 is uploaded separately
so the French act shows an ingestion happening live.

## What each part of the kit is for

| Path | Purpose |
| --- | --- |
| `demo-assets/pump-incident-demo/upload/` | The only files you upload into Agentium |
| `demo-assets/pump-incident-demo/source/safety-procedure-PROC-SAFE-118.source.md` | Editable source of the generated PDF. Edit this, never the PDF. |
| `demo-assets/pump-incident-demo/expected/expected-facts.json` | Identifiers, expected answer facts, which source must support each one, and the exact prompts |
| `demo-assets/pump-incident-demo/roi/roi-assumptions.json` | Every ROI input, editable |
| `demo-assets/pump-incident-demo/roi/roi-model.md` | Generated ROI calculation with visible formulas |
| `demo-assets/pump-incident-demo/tools/generate_assets.py` | Deterministic generator for the PDF and the ROI report |
| `demo-assets/pump-incident-demo/tools/pdf_writer.py` | Dependency-free PDF writer used by the generator |
| `demo-assets/pump-incident-demo/tools/validate_demo_kit.py` | Offline self-check for the whole kit |

## Regenerate and validate the kit

Both commands use the Python standard library only, make no network call, and can
be run from this directory:

```bash
# Rebuild the generated PDF and the ROI report
python3 tools/generate_assets.py

# Fail if any committed generated file drifted from a fresh build
python3 tools/generate_assets.py --check

# Check identifiers, expected facts, source relationships and ROI arithmetic
python3 tools/validate_demo_kit.py
```

`generate_assets.py --check` is the drift gate: the generator is byte-deterministic,
so any difference means the committed artefact no longer matches its source.

## The exact identifiers this kit tests

| Identifier | Meaning |
| --- | --- |
| `NVX-INC-4821` | The P1 incident being resolved |
| `NVX-PUMP-7742` | The failed boiler feed-water pump |
| `SITE-AUR-02` | Site Aurelia North |
| `PROC-SAFE-118` | Safety and maintenance procedure (the PDF) |
| `SLA-PLATINUM-04` | Service-level policy |
| `SEAL-KIT-3309` | Mandatory spare part for the permanent repair |
| `DEPOT-AUR` / `HUB-LYS` | Local depot with zero stock / regional hub holding the kit |
| `WORKAROUND-GP-02` | The approved temporary measure |
| `NOTE-SVC-77` | French service note on approval and logging |
| `GBX-5501` | **Decoy.** A conveyor part, plentiful locally, irrelevant to a pump incident. |
| `POL-FLEET-22` | **Control.** The unrelated fleet policy. |

## The headline modeled ROI

| Result | Value |
| --- | --- |
| Annual benefit | EUR 63 921 |
| Year-one cost | EUR 44 560 |
| Net value, year one | EUR 19 361 |
| ROI, year one | 43.45 % |
| Payback period | 8.37 months |

**These are modeled figures, not measured customer results.** They come from the
editable assumptions in `demo-assets/pump-incident-demo/roi/roi-assumptions.json`.
Replace those assumptions with the evaluator's own numbers, re-run the generator,
and present the result as their model. Full formulas and the conservatism notes are
in `demo-assets/pump-incident-demo/roi/roi-model.md`.
