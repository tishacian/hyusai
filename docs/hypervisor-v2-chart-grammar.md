# Hypervisor V2 chart grammar

The Hypervisor V2 page (`/hypervisor` when `settings.features.hypervisor_v2` is
explicitly `true`) is a themed ledger, not a dashboard skin. Colour comes only
from `--ck-*` tokens. The V1 page stays on the same route when the flag is off.

## Mark grammar

One mark is one real data unit: one day, one System, one outcome hour, one
declared euro. Charts never invent a mark for a missing fact.

| Ink | Token | Meaning |
| --- | --- | --- |
| Measured | `--ck-fg-1` | Observed runs / outcomes / cost |
| Declared | `--ck-signal-cool` | Estimated hours or value from a governed `value_basis` |
| Not measured | `--ck-fg-4` | Absence, hors-dénominateur, quiet geometry |
| Zero / drop | `--ck-signal-neg` | A real zero or a stale tail, never a stand-in for missing |

System health on the register glyph reuses `--ck-signal-pos` / `--ck-signal-warn`
/ `--ck-signal-neg`.

## Tokens across themes

`:root` is the dark cockpit. `html:not(.dark)` and `[data-theme="light"]` are
the paper theme. Components do not pick a theme and do not use raw hex.

| Role | Dark | Light |
| --- | --- | --- |
| `--ck-fg-1` (measured ink) | `#f2f5f8` | `#0a0c10` |
| `--ck-signal-cool` (declared teal) | `#7dd3fc` | `#0e7490` |
| `--ck-fg-4` (not measured) | `#7b8391` | `#656b78` |
| `--ck-signal-neg` (zero / stale) | `#ef5a6f` | `#d93a52` |
| `--ck-bg-base` | `#07090c` | `#f4f2eb` |
| `--ck-bg-inset` (hero band) | `#0a0d11` | `#efede6` |
| `--ck-stroke-2` (hairline) | `rgba(255,255,255,0.08)` | `rgba(0,0,0,0.10)` |

SVG fills and strokes reference these tokens (including SVG gradient *stops*).
That is paint on a mark, not a CSS `background-image` gradient.

## Hero tonal band

`.hv2-hero` is a full-width inset band:

- background `--ck-bg-inset` on the page `--ck-bg-base`
- bounded by `border-block: 1px solid var(--ck-stroke-2)`
- no dark slab, no `box-shadow`, no CSS gradient, no raw hex

Cards beside it stay `.ck-surface` (1 px stroke, no shadow).

## `ck-chart-*` public inputs

All primitives live in `frontend-ng/src/app/shared/cockpit/charts/`.

`ck-chart-radial-days` — one spoke per day, ink then teal.

- `days: { measured, declared, weekend?, label? }[]`
- `size`, `innerRadius`, `outerRadius`, `maxValue`
- `centerValue`, `centerCaption`, `rangeLabel`
- `ticks: { index, label, anchor? }[]`

`ck-chart-sankey-flow` — one source per System.

- `sources: { label, detail?, value, stubLabel? }[]`
- `middleLabel`, `rightLabel`, `leftCaption`, `middleCaption`, `rightCaption`
- `width`, `height`, `nodeWidth`

`ck-chart-stream` — one series per System.

- `series: { label, detail?, values, tone?: ink | ink-soft | declared | declared-soft }[]`
- `weekendStarts`, `gridLines`, `ticks`, `peak: { index, label } \| null`
- `width`, `height`, `maxValue`

`ck-chart-mini-area` — register spark (ten week totals).

- `values`, `width`, `height`, `tone: 'ink' \| 'declared' \| 'negative'`, `maxValue`

`ck-chart-unit-dots` — one dot per real unit.

- `units`, `unitsPerDot`, `tone`, `dotSize`, `gap`, `width`

`ck-chart-pulse` — one vertex per day; stale tail uses `--ck-signal-neg`.

- `values`, `staleFrom`, `width`, `height`, `startLabel`, `endLabel`, `zeroLabel`

## Series contract

`GET /api/v1/hypervisor/series?window=30d|90d`

Authorization matches the balance-sheet run filter. The payload is:

```
{ window, from, to, authorization_scope, systems[] }
```

Each system carries `value_basis`, `days_since_last_run`, and `buckets[]`.

Sparse-bucket rule: the server emits a bucket only for a calendar day that has
at least one authorized completed run. Empty days are omitted. The client
rebuilds the closed `from`–`to` calendar. Chart geometry may use `0` as a
placeholder for an omitted day. A displayed fact never does.

Bucket metrics:

- `runs`, `outcomes` — `available` (count may be `0`)
- `cost` — `available` when `cost_internal` exists, else `not_measured`
- `hours` — outcomes × `hours_per_unit`, or `not_configured` without a basis
- `value_declared` — outcomes × `value_per_unit`, or `not_configured` without a basis

## Views contract

`GET /api/v1/hypervisor/views` reads `workspace.settings.hypervisor_views`.
Absence returns Direction / Operations / Conformite. `PUT` is workspace-admin
only.

```
{ id, label, denominator: hours|runs|value, period: 30d|90d,
  strata: { comprendre, detailler, decider }, register_columns, sort }
```

`units` is a legacy alias of `runs`: accepted on write, coerced to `runs` on
read. There is no fourth denominator.

A run is always a measured fact. Under `runs` the dial and rivers are ink
only, no System is hors-dénominateur, and the monument is the run count
(available even at 0). Native output units are not a denominator: the
`unites` block groups `register` by `output_unit` and never adds a brief to
an audit.

Default views:

- Direction — hours, 90d, full ledger (monument, provenance, dial, Sankey,
  rivers, hors-dénominateur, register, signal, decisions)
- Operations — runs, 30d: monument, ink dial, run rivers, signal in the
  hero; register sorted by silence; no euro columns
- Conformite — runs, 90d: native-unit catalog (register scale, never
  monument type), basis coverage, pending decision in the hero;
  register by name

`signal` and `decisions` may sit in stratum 01 (hero) or 03. `couverture`
and `unites` are 01-only catalogue blocks. An empty stratum is hidden.
Customize (P3) can restack blocks; it cannot invent a denominator.

`can_edit` is true only for a workspace admin. Non-admins still preview locally.

## Value-basis contract

Governed object on Capability (`alembic 100_capability_value_basis`).

```
{ unit, hours_per_unit?, value_per_unit?, currency,
  declared_by, declared_at, status: declared|measured|none, note? }
```

- `GET|PUT /api/v1/capabilities/{id}/value-basis` — existing Capability write
- `GET /api/v1/hypervisor/value-bases` — portfolio list, same read scope as the balance sheet
- `PUT` mirrors `value_per_outcome = value_per_unit`

Showcase seed declares a basis on Knowledge Capture, Tender Response Analyst
and SAP HANA Maintenance Copilot. Contract Risk Copilot, Compliance Review
Loop and Translation Suite stay unset so they remain hors-dénominateur.

## Fact-state vocabulary

Shared with `FACT_STATES`:

| State | Meaning | Rendered value |
| --- | --- | --- |
| `available` | A finite number exists | That number (`Intl`, `value_basis.currency`) |
| `not_measured` | Expected but not observed (e.g. no cost) | State label, never `0` |
| `not_configured` | No governed basis, or nothing in the denominator | State label, never `0` |
| `restricted` | Authorization hid the fact | State label |
| `unavailable` | The object itself is gone | State label |

V2 copy uses Rapport, not ROI. Currency is `Intl.NumberFormat` plus the basis
ISO code. The page must not emit `$`.
