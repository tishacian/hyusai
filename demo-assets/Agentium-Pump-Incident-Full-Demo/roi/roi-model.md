<!-- GENERATED FILE. Edit roi/roi-assumptions.json, then run:
     python3 tools/generate_assets.py -->

# Modeled demo ROI — Agentium field-service knowledge

**This is a modeled demo ROI, not a measured customer result.** Every number
below is computed from the editable assumptions in `roi-assumptions.json` by
`tools/generate_assets.py`. No figure here was observed at a customer, and no
figure here is a Nordvane, Helioforge or Agentium price. Replace the assumptions
with the evaluator's own numbers before using this in any commercial discussion.

Currency: EUR. Horizon: year one only.

## Headline result

| Result | Value |
| --- | --- |
| Annual benefit | EUR 63 921 |
| Year-one cost | EUR 44 560 |
| Net value, year one | EUR 19 361 |
| ROI, year one | 43.45 % |
| Payback period | 8.37 months |

## Organisation assumed

| Assumption | Value |
| --- | --- |
| field service engineers | 40 |
| incidents handled per year | 3600 |
| p1 incidents per year | 150 |
| loaded hourly cost eur | 58 |

## Benefit 1 — Time saved locating procedure, policy and stock facts per incident

```
incidents_per_year * (baseline_minutes_per_incident * reduction_rate) / 60 * loaded_hourly_cost_eur
= 3600 * (22 * 0.35) / 60 * 58
= 3600 * 7.7 minutes / 60 * 58 EUR per hour
= EUR 26796.00 per year
```

Conservatism: Baseline of 22 minutes counts only document lookup, not travel or repair. The 35 percent reduction is a scenario assumption chosen for this synthetic model, not a benchmark and not an observed Agentium result. It is deliberately well below a full elimination of lookup time. Replace it with a figure the evaluator is willing to defend, then re-run the generator.

## Benefit 2 — Service credits avoided on P1 restoration commitments

```
p1_incidents_per_year * baseline_breach_rate * breach_reduction_rate * credit_per_breach_eur
= 150 * 0.06 * 0.25 * 6500
= 2.25 breaches avoided * EUR 6500 per 12-hour credit block
= EUR 14625.00 per year
```

Conservatism: Only one 12-hour credit block per avoided breach is counted, although SLA-PLATINUM-04 allows up to six. Only a quarter of existing breaches are assumed to be decision-latency breaches that better information can prevent.

## Benefit 3 — Emergency freight avoided by checking regional stock before escalating

```
expedited_shipments_per_year * avoidance_rate * cost_per_expedited_shipment_eur
= 90 * 0.2 * 1250
= 18.0 shipments avoided * EUR 1250 each
= EUR 22500.00 per year
```

Conservatism: Assumes only one expedited shipment in five is avoidable. Part cost itself is not counted as a benefit because the part is still consumed.

## Annual benefit

```
annual_benefit = benefit_1 + benefit_2 + benefit_3
= 26796.00 + 14625.00 + 22500.00
= EUR 63921.00
```

## Year-one cost

| Cost line | Value |
| --- | --- |
| Implementation services | EUR 28 000 |
| Platform and model runtime, 12 months | EUR 9 600 |
| Internal effort, 120 h at EUR 58/h | EUR 6 960 |
| **Total year-one cost** | **EUR 44 560** |

```
internal_effort = internal_effort_hours * internal_effort_hourly_cost_eur
= 120 * 58 = EUR 6960.00
year_one_cost = implementation_services + platform_and_model_runtime + internal_effort
= 28000 + 9600 + 6960.00
= EUR 44560.00
```

Conservatism: Year-one cost carries the full implementation charge with no amortisation, plus a full year of runtime and the customer's own project effort.

## Net value, ROI and payback

```
net_value = annual_benefit - year_one_cost
= 63921.00 - 44560.00 = EUR 19361.00

roi_percent = net_value / year_one_cost * 100
= 19361.00 / 44560.00 * 100 = 43.45 %

payback_months = year_one_cost / (annual_benefit / 12)
= 44560.00 / 5326.75 = 8.37 months
```

## Deliberately excluded from this model

- Revenue attributed to faster production restart at the customer plant.
- Reduced technician turnover or onboarding cost.
- Any benefit from Systems or Runs beyond the grounded-answer loop.
- Any second-year benefit; the model is year one only.

## How to re-run this model with the evaluator's numbers

1. Edit `roi/roi-assumptions.json`.
2. Run `python3 tools/generate_assets.py` from the kit root.
3. Run `python3 tools/validate_demo_kit.py` to re-check the arithmetic.
4. Present the result as a model built on the evaluator's own assumptions.
