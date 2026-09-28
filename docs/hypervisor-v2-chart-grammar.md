# Hypervisor V2 chart grammar

The Hypervisor V2 page is the default `/hypervisor`: it renders unless the
workspace sets `settings.features.hypervisor_v2` to something other than `true`
(in practice `false`), in which case the V1 page stays on the same route. It is
a themed ledger, not a dashboard skin. Colour comes only from `--ck-*` tokens.

## Mark grammar

One mark is one real data unit: one day, one System, one outcome hour, one
declared euro. Charts never invent a mark for a missing fact.

| Ink | Token | Pattern | Meaning |
| --- | --- | --- | --- |
| Measured | `--ck-data-measured` | solid, `●` in text | Observed runs / outcomes / cost |
| Declared | `--ck-data-declared` | hatch, dashes, `◐` in text | Estimated hours or value from a governed `value_basis` |
| Not measured | `--ck-data-muted` | — | Absence, hors-dénominateur, quiet geometry (marks only) |
| Zero / drop | `--ck-data-zero` | — | A real zero or a stale tail, never a stand-in for missing |

System health on the register glyph reuses `--ck-signal-pos` / `--ck-signal-warn`
/ `--ck-signal-neg`.

### Declared carries a pattern, not only a colour

Tokens v2 made the declared teal the primary colour, the one of the filled
button and of links. Colour alone would therefore say "clickable", and would
say nothing to a reader who cannot tell teal from grey (WCAG 1.4.1). Every
declared mark carries a second, colour-free cue:

- **Areas** (river bands, the Sankey value ribbon): an SVG `<pattern>` hatch,
  1.5-unit lines of `--ck-data-declared` every 10 units at 45°, over a teal
  tint of at most 0.18 opacity. L28 opened it from 2 every 6 (tint 0.22): on
  those large areas the denser hatch read as zebra noise. Two declared neighbours hatch in opposite
  directions. Pattern ids are unique per chart (`ckChartUid`). The Sankey
  ribbon's hatch fades in with its teal, so the part that leaves the measured
  hours stays unhatched.
- **Thin marks** (Cadran declared segment, register spark, Sankey value node):
  a dash pattern (`stroke-dasharray`), since a hatch does not read on a 2 to
  6 unit stroke.
- **Dots**: `◐`, a ring with its left half filled.
- **HTML bars** (provenance bar): the same hatch as a
  `repeating-linear-gradient` of `--ck-data-declared` over a 12 % tint.
- **Text and legends**: `◐` for declared, `●` for measured, `○` for a native
  unit; legends name the pattern in plain words ("trait plein = mesuré ·
  pointillé = estimé", "plein = mesuré · hachuré = estimé").

The tints stay low so the pattern lines keep 3:1 against what they sit on, in
both themes and at 1x as well as 2x device pixel ratio (measured on the
rendered page: 3.34:1 at worst, the light provenance bar). For the lighter
area hatch, the worst case is the light theme at 1x: a 1.5-unit line at 45°
covers at least 90 % of one device pixel in its worst phase, which gives
3.35:1 on the 0.18 tint over the canvas (3.47:1 over a panel), and 3.88:1 at
full coverage (2x). Dark theme: 5.09:1 and above.

Constants live in `shared/cockpit/charts/chart.types.ts`
(`CK_DECLARED_HATCH_*`, `CK_DECLARED_DASH_*`, `ckChartIsDeclared`) and
`chart-declared.spec.ts` pins the cue on every chart.

## Tokens across themes

`:root` is the dark cockpit. `html:not(.dark)` and `[data-theme="light"]` are
the paper theme (Tokens v2, `frontend-ng/src/styles/cockpit-tokens.scss`).
Components do not pick a theme and do not use raw hex.

| Role | Dark | Light |
| --- | --- | --- |
| `--ck-data-measured` → `--ck-fg-1` | `#f2f5f8` | `#151a21` |
| `--ck-data-declared` → `--ck-primary` | `#1fb8cc` | `#0a7483` |
| `--ck-data-muted` (marks only) | `#7b8391` | `#7d8693` |
| `--ck-data-zero` → `--ck-signal-neg` | `#ef5a6f` | `#b02e43` |
| `--ck-fg-3` (captions; `--ck-fg-4` and `--ck-fg-5` alias it) | `#a0a9b5` | `#525c69` |
| `--ck-bg-base` | `#0d1116` | `#f2f4f6` |
| `--ck-bg-panel` (cards) | `#121820` | `#f8f9fa` |
| `--ck-bg-inset` (hero band) | `#0a0d11` | `#edf0f2` |
| `--ck-stroke-2` (hairline) | `rgba(255,255,255,0.08)` | `rgba(21,26,33,0.10)` |

`--ck-data-muted` restores the mid-tone the text scale gave up when Tokens v2
aliased `--ck-fg-4` and `--ck-fg-5` to `--ck-fg-3`. It clears 3:1 as a graphic
(4.96 and 4.67:1 on the dark canvas and panel, 3.34 and 3.49:1 in light) but
only 4.30:1 as text on the dark relief surface, so it never colours text; text
stays on three levels.

SVG fills and strokes reference these tokens (including SVG gradient *stops*).
That is paint on a mark, not a CSS `background-image` gradient.

**Aucun dégradé ni halo sur le chrome ; les graphiques gardent leur grammaire
(dégradés SVG, motifs, halo limité au graphique) dans
`shared/cockpit/charts/`.** The provenance bar of the Impact page is a chart
drawn in HTML and follows the chart grammar too.

## Hero tonal band

`.hv2-hero` is a full-width inset band:

- background `--ck-bg-inset` on the page `--ck-bg-base`
- bounded by `border-block: 1px solid var(--ck-stroke-2)`
- no dark slab, no `box-shadow`, no CSS gradient, no raw hex

Cards beside it stay `.ck-surface` (1 px stroke, no shadow).

## `ck-chart-*` public inputs

All primitives live in `frontend-ng/src/app/shared/cockpit/charts/`.

`ck-chart-radial-days` — one spoke per day, solid ink then dotted teal.

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

`ck-chart-mini-area` — register spark (ten week totals); a declared spark is dashed.

- `values`, `width`, `height`, `tone: 'ink' \| 'declared' \| 'negative' \| 'muted'`, `maxValue`

`ck-chart-unit-dots` — one dot per real unit; a declared dot draws `◐`.

- `units`, `unitsPerDot`, `tone`, `dotSize`, `gap`, `width`

`ck-chart-pulse` — one vertex per day; stale tail uses `--ck-data-zero`.

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
