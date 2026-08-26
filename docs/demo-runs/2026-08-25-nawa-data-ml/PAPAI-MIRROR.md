# Nawa data/ML use case — specification for a manual rebuild (papAI mirror)

This note is everything an operator needs to rebuild the **data and ML half** of the Nawa
demo by hand, on papAI, and land on the **same figures**. It describes the input bytes
column by column, then every transformation in order, with the exact statement or script
each one runs and the exact output each one must produce.

It is written to be *arbitrable*. Every number quoted here is printed by one command that
needs no database, no object store and no running Agentium:

```bash
cd backend
python -m scripts.papai_mirror_facts              # counts and band tallies, ~2 s
python -m scripts.papai_mirror_facts --with-fits  # + the three ROC AUCs, ~5 s
```

So when the rebuild and this note disagree, the script says which one is wrong.

**Scope.** The data and ML plane only: two source tables, one cleaning step, one feature
step, three model fits, one batch scoring, one aggregation mart. The agentic surfaces
(the LLM brief, the published skill, the API key, the canvas) are described in
[`DEMO-SCRIPT.md`](./DEMO-SCRIPT.md) and summarised in §9 here, because a mirror that stops
at the scored table is still a faithful mirror of the data/ML case.

**Reading order.** §1 gets the bytes. §2 and §3 are the two inputs. §4 and §5 are the two
pipelines, step by step. §6 maps the objects onto papAI's. §7 is the reference
implementation. §8 is the acceptance checklist — the table to tick off. §9 is what the
platform adds beyond the data plane. §10 is the list of things that silently change the
figures, and it is the section to read *before* starting rather than after.

---

## 1. Getting the input bytes

Both tables are **synthetic and deterministic**: a pure function of one seed, the same
bytes on any machine. The demo's seed is `20260825` and it is the default.

```bash
cd backend
python -m scripts.gen_nawa_telecom_data --out-dir /tmp/nawa            # CSV
python -m scripts.gen_nawa_telecom_data --out-dir /tmp/nawa --parquet  # or Parquet
python -m scripts.gen_nawa_telecom_data --describe                     # shapes only
```

| File | Rows | Columns | Size | SHA-256 (first 16) |
|---|---|---|---|---|
| `nawa_churn_raw.csv` | 8 412 | 24 | 998 KB | `41d55881f136aa55` |
| `nawa_network_cells.csv` | 24 192 | 12 | 2 390 KB | `539c73c0d1964c7d` |

Full digests:

```
41d55881f136aa551f1a72a4db691fd6f6afd27904ba5ad4dd613b7cd4bf465c  nawa_churn_raw.csv
539c73c0d1964c7d4b47b879539f7759338d258dd52554f7d05b229256719ad3  nawa_network_cells.csv
```

If the digests match, everything downstream in this note is reproducible to the unit. If
they do not, check the seed first — a different seed gives a coherent but different world,
and every figure below moves.

CSV conventions that matter on import: the decimal separator is `.`, the field separator is
`,`, missing values are **empty fields** (not `NA`, not `NULL`), `snapshot_date` is
`YYYY-MM-DD` and `ts` is ISO-8601 with microseconds (`2026-08-10T00:00:00.000000`).

---

## 2. Input A — the subscriber base, as the export really arrives

`nawa_churn_raw.csv` · **8 412 rows × 24 columns** · one monthly export of the subscriber
master of a Moroccan mobile operator, dirt included.

### 2.1 Schema

| # | Column | Type | Unit / domain | Meaning |
|---|---|---|---|---|
| 1 | `msisdn` | string | 11 digits, `2126…` | Subscriber line. **Identifier, never a feature.** 8 000 distinct values over 8 412 rows |
| 2 | `snapshot_date` | date | `YYYY-MM-DD` | Date the row was extracted. 63 distinct values, from `2026-05-27` to `2026-08-24` |
| 3 | `region` | string | 7 regions, **28 spellings** | Administrative region. Dirty: case and padding vary by source system |
| 4 | `plan` | string | 3 offers, **6 spellings** | `prepaid` / `postpaid` / `hybrid`, sometimes upper-cased |
| 5 | `contract` | string | `monthly`, `annual`, `two_year` | Commitment. Always `monthly` when the plan is prepaid |
| 6 | `line_status` | string | `active`, `suspended` | 677 rows `suspended`. **Consumed by the cleaning, absent downstream** |
| 7 | `tenure_months` | integer | 1–96 months | Months since activation |
| 8 | `arpu_mad` | float | MAD/month, 9.00–279.85 | Average revenue per user. **310 empty, 170 at `-1`** |
| 9 | `data_gb` | float | GB/month | Mobile data consumed |
| 10 | `voice_minutes` | integer | min/month | Outgoing voice |
| 11 | `sms_count` | integer | count/month | SMS sent |
| 12 | `intl_minutes` | float | min/month | International calls |
| 13 | `roaming_days` | integer | days/month, 0–30 | Days spent roaming |
| 14 | `support_tickets` | integer | count/month | Support contacts |
| 15 | `dropped_calls` | integer | count/month | Calls dropped by the network |
| 16 | `avg_download_mbps` | float | Mbps | Average throughput experienced |
| 17 | `late_payments` | integer | count | Late invoices. Always 0 on prepaid |
| 18 | `device_age_months` | integer | 1–60 months | Age of the handset |
| 19 | `handset_tier` | string | `entry`, `mid`, `premium` | Handset segment |
| 20 | `fiber_bundle` | 0/1 | boolean as integer | Fixed-line bundle attached |
| 21 | `family_lines` | integer | 1–5 | Lines on the same account |
| 22 | `promo_discount_pct` | float | 0–35 % | Discount in progress. 0 when none |
| 23 | `nps` | integer | 0–10 | Last survey score. **1 383 empty — and they stay empty** |
| 24 | `churn` | 0/1 | **the target** | The subscriber left during the observation window. Base rate **22.18 %** |

### 2.2 The four defects, and the arithmetic they imply

The export is dirty on purpose, and each defect maps to exactly one line of the cleaning
statement in §A2.

| Defect | Rows affected in the file | Removed by the cleaning | How |
|---|---|---|---|
| Stale duplicate snapshots | 412 | **412** | Keep the latest `snapshot_date` per `msisdn` |
| Suspended lines | 677 | **640** | `line_status = 'active'` |
| Missing revenue | 310 | **297** | `arpu_mad IS NOT NULL` |
| Revenue at the `-1` sentinel | 170 | **160** | `arpu_mad >= 0` |
| Region / plan spelled inconsistently | 28 and 6 spellings | 0 rows | Normalised in place with `lower(trim(…))` |

**Why "rows affected" exceeds "rows removed".** The 412 duplicates are re-exports of rows
already in the file, so they inherit their original's defects: some of them are themselves
suspended or holed. Deduplication runs **first** and takes all 412 with it; the three
remaining filters then apply to the 8 000 canonical rows, where the defect blocks are
disjoint by construction:

```
8 412 − 412 duplicates                           = 8 000
8 000 − 640 suspended − 297 empty − 160 sentinel = 6 903
```

**Deduplicate first — but on this data you will not be punished for the other order.** Worth
knowing precisely, because it is the kind of thing a rebuild trips over and then
misdiagnoses. Filtering first also yields exactly 6 903 identical rows here (verified), and
the reason is that a stale re-export copies its original's defects: 1 157 of the 8 412 rows
are suspended or holed, twins included, and removing them first leaves 352 clean twins for
the dedup to take. So the arithmetic reads either way.

The rule still holds in general, and it is why the statement is written dedup-first: on real
data a stale snapshot can be *clean* while the current one is not — a line suspended this
month, say — and filtering first would then resurrect the old row for a subscriber who
should have been dropped. This generator simply does not produce that case.

### 2.3 What must **not** be cleaned

Three traps, and getting them wrong is the difference between a mirror and a lookalike.

- **`nps` keeps its 1 383 holes.** A subscriber who has stopped answering the survey is a
  subscriber on the way out: the non-response carries signal, and it is generated that way
  (the probability of silence rises with churn propensity). Dropping those rows destroys
  1 144 rows of the cleaned base and part of the model's edge. In the cleaned base, 1 144
  of 6 903 rows have no `nps` — **16.6 %**, and they must reach the model as holes.
- **`arpu_mad = -1` must be removed, not imputed.** It is an "unknown" that the export
  writes as a number. Left in, a model learns that *−1 MAD predicts churn*, which is the
  single mistake the cleaning step exists to prevent.
- **`msisdn` is never a feature.** It survives the cleaning so the score sheet can be
  joined back to a customer, and it is excluded from every fit. A platform that
  auto-selects "all columns except the target" will pick it up and must be corrected.

---

## 3. Input B — the radio cell KPIs

`nawa_network_cells.csv` · **24 192 rows × 12 columns** · hourly radio counters, long
format: one row per cell and per hour, 72 cells × 14 days × 24 h.

| # | Column | Type | Unit | Meaning |
|---|---|---|---|---|
| 1 | `cell_id` | string | `CAS-773-L54` | Radio cell. 72 distinct. `L` = 4G, `N` = 5G |
| 2 | `site_code` | string | `CAS-773` | Physical site. 71 distinct — two cells share one site |
| 3 | `region` | string | 7 regions | Clean here, unlike the subscriber export |
| 4 | `technology` | string | `4G`, `5G` | Radio access technology |
| 5 | `ts` | timestamp | hourly | `2026-08-10 00:00` to `2026-08-23 23:00`, no gaps, no timezone |
| 6 | `active_users` | integer | count | Sessions on the cell that hour |
| 7 | `prb_utilization_pct` | float | % of 100 | Spectrum utilisation. Median 28.7, max **94.9** — never 100 |
| 8 | `throughput_mbps` | float | Mbps | Average throughput. Falls as the cell saturates |
| 9 | `latency_ms` | float | ms | Climbs superlinearly past ~62 % PRB |
| 10 | `drop_call_rate_pct` | float | % | Dropped calls. Climbs with the square of saturation |
| 11 | `handover_success_pct` | float | % | Handover success |
| 12 | `energy_kwh` | float | kWh | Radio consumption: an idle floor plus a load-following part |

### 3.1 The three populations planted in it

The watchlist of §5 is only worth building because all three are present, and they are
disjoint by construction.

| Population | Cells | What it looks like in the counters |
|---|---|---|
| Chronically saturated | 6 | High all fortnight. A level threshold already finds them; the engineer already knows them |
| Degrading inside the recent week | 3 | Started healthy (59–67 % PRB), ended critical (86–88 %). **Only the trend finds them** |
| Relieved by a capacity upgrade | 2 | Fell by 17 to 21 PRB points. Present so the trend column reads in both directions |

**`prb_utilization_pct` never reaches 100.** The counter saturates asymptotically rather
than being clipped, and that is deliberate: with clipping, a large share of busy hours sit
on exactly 100.0, the week-over-week delta of a constant is zero, and the cells degrading
fastest become invisible to the very column meant to surface them. Check it on import —
**0 of 24 192 rows at 100.0** — because a platform that clips on load reintroduces the
problem.

---

## 4. Pipeline A — Churn Radar, step by step

Six steps: an import, a cleaning, a feature step, three fits, a registry decision and a
batch scoring. Nothing in this pipeline is an LLM: SQL, then a dataframe engine, then
scikit-learn.

```
A1 import        A2 SQL cleanup     A3 features        A4 fit ─► A5 registry
raw export  ──►  cleaned base  ──►  feature table  ──►  three versions, v1 serving
   8 412 × 24       6 903 × 22        6 903 × 31                    │
                                          │                        │
                                          └────────► A6 score ◄────┘
                                                     6 903 × 34
```

The scoring step has two inputs on purpose: the fit tells it *which model*, the feature
table is *what it scores*. A model reference carries no rows.

### A1 — Import the raw export

Import `nawa_churn_raw.csv` as a dataset. **8 412 rows, 24 columns.**

Typing to check after import, because a CSV reader that guesses wrong here costs an hour
later:

- `msisdn` must be **string**, not a number. It starts with `2126` and a numeric cast drops
  nothing visibly but breaks the join back at the end.
- `snapshot_date` must be a **date**, or at least a string that sorts chronologically. The
  deduplication orders on it.
- `arpu_mad` must be **float with nulls allowed**. A reader that fills empties with 0 turns
  310 holes into 310 subscribers billed nothing — a different defect, no longer removable
  by the `IS NOT NULL` test.
- `nps` must be **nullable integer or float**. Same reason, and this one is not filtered
  out later: a 0 here is a real survey score meaning "detractor".

### A2 — The cleaning statement (SQL)

One statement. It deduplicates, normalises two columns, drops three defect classes and
orders the output. Run it verbatim — it is the statement the demo's node carries, and the
`8 412 → 6 903` claim is a property of *this* text over *those* bytes.

```sql
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY msisdn ORDER BY snapshot_date DESC
        ) AS snapshot_rank
    FROM clients
)
SELECT
    msisdn,
    -- One spelling per region, whatever the source system wrote.
    lower(trim(region))                                        AS region,
    lower(trim(plan))                                          AS plan,
    contract,
    tenure_months,
    arpu_mad,
    data_gb,
    voice_minutes,
    sms_count,
    intl_minutes,
    roaming_days,
    support_tickets,
    dropped_calls,
    avg_download_mbps,
    late_payments,
    device_age_months,
    handset_tier,
    fiber_bundle,
    family_lines,
    promo_discount_pct,
    nps,
    churn
FROM ranked
WHERE snapshot_rank = 1
  AND line_status = 'active'
  AND arpu_mad IS NOT NULL
  AND arpu_mad >= 0
ORDER BY msisdn
```

`clients` is the imported raw dataset; rename it to whatever the platform's SQL step calls
its input.

**Output — 6 903 rows × 22 columns.** `snapshot_date` and `line_status` are gone: both were
consumed by the cleaning and neither is a feature. Verify: 7 distinct `region` values, 3
distinct `plan` values, no null and no negative `arpu_mad`, 1 144 null `nps`, churn rate
**22.16 %** (1 530 positives).

**`ORDER BY msisdn` is load-bearing.** It looks decorative. The engine underneath is
parallel, so without it the row *order* changes between runs while the row *set* stays the
same — and the train/test split is drawn over the frame as ordered. Drop this line and every
metric below moves in the third decimal from one run to the next, for no reason anybody can
see. Any platform whose SQL step does not guarantee output order needs an explicit sort
here.

### A3 — The derived features (Polars, or any dataframe engine)

Nine columns added to the 22, giving **6 903 rows × 31 columns**. The script the demo runs:

```python
import polars as pl


def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame:
    base = inputs["input"]
    friction = pl.col("support_tickets") + pl.col("dropped_calls") / 4.0
    return base.with_columns(
        (pl.col("arpu_mad") / (pl.col("tenure_months") + 1)).round(4).alias("arpu_per_month"),
        (pl.col("data_gb") / pl.col("arpu_mad").clip(1.0)).round(4).alias("gb_per_mad"),
        friction.round(2).alias("friction_score"),
        (friction / pl.col("arpu_mad").clip(1.0)).round(5).alias("friction_per_mad"),
        (pl.col("voice_minutes") + 0.5 * pl.col("sms_count")).alias("usage_index"),
        (pl.col("intl_minutes") + 12.0 * pl.col("roaming_days")).round(1).alias("mobility_index"),
        pl.when(pl.col("tenure_months") <= 6)
        .then(pl.lit("new"))
        .when(pl.col("tenure_months") <= 24)
        .then(pl.lit("established"))
        .otherwise(pl.lit("loyal"))
        .alias("tenure_band"),
        (pl.col("promo_discount_pct") > 0).cast(pl.Int8).alias("on_promo"),
        pl.col("nps").is_not_null().cast(pl.Int8).alias("nps_answered"),
    )
```

Restated as formulas, for a platform whose feature step is not Python:

| New column | Formula | Rounding | Type |
|---|---|---|---|
| `arpu_per_month` | `arpu_mad / (tenure_months + 1)` | 4 dp | float |
| `gb_per_mad` | `data_gb / max(arpu_mad, 1.0)` | 4 dp | float |
| `friction_score` | `support_tickets + dropped_calls / 4` | 2 dp | float |
| `friction_per_mad` | `friction_score / max(arpu_mad, 1.0)` | 5 dp | float |
| `usage_index` | `voice_minutes + 0.5 × sms_count` | — | float |
| `mobility_index` | `intl_minutes + 12 × roaming_days` | 1 dp | float |
| `tenure_band` | `new` if ≤ 6 months, `established` if ≤ 24, else `loyal` | — | string |
| `on_promo` | `1` if `promo_discount_pct > 0` else `0` | — | 0/1 |
| `nps_answered` | `1` if `nps` is present else `0` | — | 0/1 |

Three points of substance, worth saying out loud when presenting:

- **The `+ 1` in `arpu_per_month` is a guard**, not a fudge: `tenure_months` starts at 1 in
  this data, but a division that can meet a zero is a division that will.
- **`clip(1.0)` on the denominator**, likewise: `arpu_mad` is ≥ 9.00 after cleaning, so the
  clip never fires here and exists so the column stays defined on data that has not been
  cleaned the same way.
- **`nps_answered` turns a hole into a column.** It makes explicit the signal the
  missingness already carried, and it is the one derived column whose value is independent
  of the ratios.

**Verify**: `tenure_band` splits **429 `new` / 1 291 `established` / 5 183 `loyal`**;
`on_promo` sums to 2 380; `nps_answered` sums to 5 759, so 6 903 − 5 759 = 1 144 holes,
matching §2.3.

### A4 — The three fits

Three model versions, and the ranking between them is a **measured fact about the data**,
not a staged story. Same target, same split, same seed.

| Version | Trained on | Feature columns | Estimator | Hyper-parameters | ROC AUC |
|---|---|---|---|---|---|
| **v1** | cleaned base (§A2) | **20** (the base set) | Logistic regression | `max_iter=1000`, `C=1.0` | **0.836610** |
| **v2** | cleaned base (§A2) | **20** (the base set) | Hist. gradient boosting | `max_iter=220`, `learning_rate=0.08` | **0.864133** |
| **v3** | feature table (§A3) | **29** (20 + the 9 derived) | Hist. gradient boosting | `max_iter=220`, `learning_rate=0.08` | 0.853761 |

Common to all three:

- **Target**: `churn`, binary, positive class `1`, base rate 22.16 %.
- **Split**: single hold-out, `test_size = 0.25`, `random_state = 42`, **stratified on the
  target** → 5 177 train rows, 1 726 test rows.
- **`random_state = 42`** on the estimator as well as the split.
- **Metrics are read on the test split only**, never on the training rows.

**The 20-column base set** — every column of the cleaned base except `msisdn` and `churn`:

```
region, plan, contract, tenure_months, arpu_mad, data_gb, voice_minutes, sms_count,
intl_minutes, roaming_days, support_tickets, dropped_calls, avg_download_mbps,
late_payments, device_age_months, handset_tier, fiber_bundle, family_lines,
promo_discount_pct, nps
```

**The 29-column set** is those 20 plus `arpu_per_month`, `gb_per_mad`, `friction_score`,
`friction_per_mad`, `usage_index`, `mobility_index`, `tenure_band`, `on_promo`,
`nps_answered`.

#### A4.1 Preprocessing — and it differs per estimator

The demo delegates this to `skrub.tabular_pipeline(estimator)`, which asks the estimator
what it needs. Reproduce it explicitly:

**For the boosted trees (v2, v3)** — two steps, and no imputation anywhere:

1. Encode the 5 categorical columns (`region`, `plan`, `contract`, `handset_tier`, and
   `tenure_band` in the 29-column set) as **native categoricals** — an ordinal/label
   encoding the estimator reads as categorical, not one-hot.
2. Fit `HistGradientBoostingClassifier`. **Missing `nps` values are passed through as
   missing**: the estimator routes them down a branch of their own. No scaling.

**For the logistic regression (v1)** — four steps:

1. **One-hot encode** the 4 categorical columns (`region` 7 levels, `plan` 3, `contract` 3,
   `handset_tier` 3 → 16 dummy columns). All levels are low-cardinality, so plain one-hot is
   exactly equivalent to what skrub does.
2. **Impute** the numeric holes with the **median**, and add a **missingness indicator
   column**. Median rather than mean because a survey score and a revenue figure are skewed
   often enough that the mean is not a plausible value; the indicator because "was
   missing" is information and dropping it would hand the trees an unearned advantage.
3. **Scale** the numeric columns to comparable magnitudes. The demo uses a squashing scaler
   capped at ±5; a plain standard scaler is a fine substitute — measured, the two land at
   0.836610 and 0.836701, a difference in the fourth decimal.
4. Fit `LogisticRegression(C=1.0, max_iter=1000)`.

Two implementation notes that cost debugging time if missed:

- **Cast integer feature columns to float before fitting.** An integer column cannot carry
  a missing value, and the input signature written at fit time is enforced at predict time —
  so a production row with one hole would be refused by the very contract training wrote.
- **Column count check, on the one-hot path only.** The 29 input columns become **43** after
  one-hot encoding (24 numeric + 7 + 3 + 3 + 3 + 3 dummies); the 20-column set becomes 32
  (16 numeric + 16 dummies). The tree path keeps its 29 or 20 columns, categoricals
  included. A different width on either path means a level is being dropped, or a numeric is
  being read as a category.

#### A4.2 Why the ranking comes out this way

Worth being able to explain, because the whole point of the three versions is that the story
is honest.

- **v2 beats v1 by +0.027523** for two named reasons. Churn in this base is genuinely
  **non-additive**: a support ticket in the first year is a resignation letter, the same
  ticket on an eight-year line is a call to support, and a logistic regression cannot
  represent a product of two variables. And **survey non-response carries signal**: the
  trees read a missing `nps` inside an interaction, while the linear model gets it
  median-filled plus an additive indicator. The baseline was not handicapped — the world is
  not additive.
- **v3 does not win** (0.853761 < 0.864133) even though it has nine more columns, and it is
  left that way on purpose. The ratios do carry real signal, but the boosted trees had
  already extracted most of it from the levels, and the extra columns cost variance. A
  registry earns its place by telling you when a challenger **failed**; a demo that quietly
  reversed the number would teach the opposite lesson.
- **The metric ceiling is deliberate.** The label is a noisy logit rather than a rule, tuned
  so a good fit lands near 0.86 — high enough to be worth showing, low enough that nobody
  in the room suspects a leak.

#### A4.3 The evidence to capture per fit

Whatever papAI records natively, capture these so the two platforms can be compared
side by side: **ROC AUC, accuracy, precision, recall, log loss, Brier score**, the
**confusion matrix**, the **ROC and precision/recall curves**, the **class balance**, and
**permutation importances** on the test split. The two calibration metrics matter more than
they look: the score is about to be shown as a gauge and believed, and log loss and Brier
are the only two numbers that say whether a probability means what it says.

For reference, v1 against v2 on the same 1 726 test rows:

| Metric | v1 `linear` | v2 `gradient_boosting` |
|---|---|---|
| ROC AUC | 0.836610 | **0.864133** |
| Accuracy | 0.836616 | **0.852838** |
| Precision | 0.707224 | **0.762238** |
| Recall | 0.448485 | **0.487879** |
| Log loss | 0.390613 | **0.369748** |
| Brier | 0.121909 | **0.109838** |

v2 wins on all six, including both calibration metrics.

### A5 — Registry and champion

Three versions of **one lineage**, not three unrelated models. The demo keeps **v1 serving**
even though v2 is better, so that promoting v2 is a real move with a real delta to read out
(+0.027523). Reproduce that state: register the three versions under one name, mark the
**interpretable baseline as the one in production**, and leave the promotion as a manual
act.

If the platform has champion/challenger aliases, set `champion → v1` and
`challenger → v2` — the challenger being **the best version that is not serving**, not the
most recent. Naming "the latest" would often name the worst, which is exactly why promotion
stays a human decision.

### A6 — Batch scoring

Score the **feature table** (§A3, 6 903 rows) with the **serving version** — not the version
just trained. The output keeps every input column and appends three:

| Column | Type | Content |
|---|---|---|
| `prediction` | string | The predicted class, `"0"` or `"1"` |
| `confidence` | float | Probability of the predicted class, 0–1 |
| `score_1` | float | Probability of the **positive** class (`churn = 1`), 0–1 |

**Output — 6 903 rows × 34 columns.** Keeping every input column is not padding: a score
sheet whose rows cannot be joined back to a subscriber is not actionable, which is why
`msisdn` was carried through §A2 and §A3 without ever being a feature.

Verification worth doing, because it is the business figure: with v1 serving, the model
flags **about 1 000 of 6 903** subscribers, and the **riskiest decile churns at roughly
77 %** — ×3.5 the 22.16 % base rate.

Unlike every other figure in this note, treat these two as approximate. Both are read off a
probability — one either side of a 0.5 threshold, one at the edge of a 690-row decile — so a
scaler substituted in §A4.1 or a library version moves them by a row or two: the demo's own
run recorded 999 and 77.2 %, the reference implementation of §7 gives 1 000 and 77.4 %. The
**lift of ×3.5 over the base rate** is the claim; the unit digit is not.

---

## 5. Pipeline B — Radio Watch, the congestion watchlist

Two SQL models over the KPI table, plus two data tests. The demo runs them as a dbt project
on duckdb; the SQL is portable to any warehouse once `ref` and `source` are substituted.

### B1 — Staging: one row per cell-hour, with calendar keys

```sql
select
    cell_id,
    site_code,
    region,
    technology,
    cast(ts as timestamp)                        as kpi_hour,
    cast(ts as date)                             as kpi_date,
    extract('hour' from cast(ts as timestamp))   as hour_of_day,
    active_users,
    prb_utilization_pct,
    throughput_mbps,
    latency_ms,
    drop_call_rate_pct,
    handover_success_pct,
    energy_kwh
from input
```

Pure typing and key extraction — no filter, no aggregation. **24 192 rows in, 24 192 out.**
It exists so the mart is readable.

### B2 — Mart: the watchlist

```sql
with busy as (
    select *
    from stg_cell_hourly
    where hour_of_day between 19 and 23
),
bounds as (
    select max(kpi_date) as last_day from busy
),
windowed as (
    select
        busy.*,
        case
            when busy.kpi_date > bounds.last_day - interval 7 day then 'recent'
            else 'previous'
        end as window_label
    from busy cross join bounds
),
per_window as (
    select
        cell_id,
        site_code,
        region,
        technology,
        window_label,
        round(avg(prb_utilization_pct), 2) as prb_pct,
        round(avg(drop_call_rate_pct), 3)  as drop_pct,
        round(avg(throughput_mbps), 1)     as throughput_mbps,
        round(avg(latency_ms), 1)          as latency_ms,
        round(sum(energy_kwh), 1)          as energy_kwh,
        max(active_users)                  as peak_users
    from windowed
    group by 1, 2, 3, 4, 5
)
select
    recent.cell_id,
    recent.site_code,
    recent.region,
    recent.technology,
    recent.prb_pct,
    recent.drop_pct,
    recent.throughput_mbps,
    recent.latency_ms,
    recent.energy_kwh,
    recent.peak_users,
    round(recent.prb_pct - previous.prb_pct, 2)   as prb_pct_delta,
    round(recent.drop_pct - previous.drop_pct, 3) as drop_pct_delta,
    case
        when recent.prb_pct >= 85 then 'critical'
        when recent.prb_pct >= 70 then 'watch'
        else 'healthy'
    end as risk_band
from per_window recent
left join per_window previous
    on previous.cell_id = recent.cell_id
   and previous.window_label = 'previous'
where recent.window_label = 'recent'
order by recent.prb_pct desc
```

Three decisions inside it, each defensible out loud:

- **Busy hour only, 19:00–23:00.** A cell that saturates at 3 am is not a customer problem.
- **Last 7 days against the 7 before them.** A level without a trend does not tell an
  engineer where to go. The KPI window ends the evening before the reference date precisely
  so "last 7 days" is a full week and not a partial one.
- **Bands at 85 and 70 % PRB**, on the *recent* window's average.

**Output — 72 rows × 13 columns**, one per cell.

| Band | Cells |
|---|---|
| `critical` (≥ 85 % PRB) | **9** |
| `watch` (70–85 %) | **8** |
| `healthy` (< 70 %) | **55** |

The `critical` band in full, with the delta that is the whole point:

| Cell | PRB % | Δ 7 d | Drop % | Δ drop |
|---|---|---|---|---|
| `CAS-773-L54` | 92.84 | +0.05 | 2.487 | −0.039 |
| `AGA-132-N66` | 92.68 | 0.00 | 2.470 | +0.036 |
| `TNG-818-L59` | 92.67 | 0.00 | 2.451 | +0.004 |
| `AGA-528-L36` | 91.42 | −0.33 | 2.292 | 0.000 |
| `FEZ-613-L48` | 91.26 | +0.34 | 2.249 | +0.039 |
| `OUJ-917-N09` | 90.91 | −0.02 | 2.240 | −0.008 |
| **`RBA-932-L41`** | 88.42 | **+21.32** | 1.893 | **+1.469** |
| **`AGA-270-L69`** | 86.65 | **+27.80** | 1.689 | **+1.380** |
| **`RBA-440-L31`** | 86.14 | **+27.56** | 1.636 | **+1.263** |

The first six have been saturated for months — deltas between −0.33 and +0.34, motionless,
already on the engineer's plan. The three in bold were **healthy a fortnight ago** (67, 59
and 59 % PRB) and went critical inside the last week, with dropped calls up by more than a
point. They are the only three rows in the table that really move: the fourth largest
movement in the file is **+2.42**. A threshold on the level alone would have drowned them
among the other six.

And it reads downward too: `CAS-831-N65` at **−20.64** (50.86 % PRB) and `RBA-142-L70` at
**−17.43** (45.09 %) — two cells a capacity upgrade relieved. The third negative movement is
only −1.34. A trend column that never went down would not be believed.

### B3 — The two data tests

Not decoration: they decide whether the mart is publishable, and the pipeline **refuses to
hand a failing result downstream**.

| Test | Column | Rule |
|---|---|---|
| `not_null` + `unique` | `cell_id` | One row per cell, always known |
| `accepted_values` | `risk_band` | Exactly one of `critical`, `watch`, `healthy` |

A cell appearing twice means the window join fanned out; a band outside the three means a
cell's utilisation came back null or unclassifiable. Either way the pipeline is wrong, and
refusing to publish is the difference between a pipeline and a script.

---

## 6. Mapping the objects onto papAI

The two platforms share an architectural philosophy, and the vocabulary maps cleanly:

| Agentium | papAI |
|---|---|
| Flow | Workflow |
| System | Pipeline |
| Skill | Model |
| Knowledge / Dataset | Dataset |
| Capability | Endpoint |
| Run | Job |

For the rebuild, what matters is the **function** of each step rather than the name of the
module, which varies by papAI version. Map each row to whatever your version calls it:

| Step | What the module has to do | Agentium node |
|---|---|---|
| A1 | Import a CSV as a versioned, profiled dataset | upload → `TabularDataset` |
| A2 | Run author-written SQL over one dataset, output a new dataset | `sql_transform_v1` (duckdb) |
| A3 | Run author-written dataframe code, output a new dataset | `polars_transform_v1` |
| A4 | Fit a supervised classifier with declared target, features, split and seed | `ml_train_sklearn_v1` |
| A5 | Hold versions of one lineage, mark one as serving | `ml_models` + MLflow registry |
| A6 | Score a whole dataset with the serving version, append the answer | `ml_batch_score_v1` |
| B1–B3 | Run a multi-model SQL project with blocking data tests | `dbt_transform_v1` (dbt-duckdb) |

Three properties to preserve, beyond the figures, because they are what make the demo a
platform demo rather than a notebook demo:

1. **Lineage.** Every derived table points at the exact version it came from. Four
   generations deep on the churn side: raw → cleaned → features → scored.
2. **Versioning, not overwriting.** Re-running a transform mints a new version rather than
   replacing the old one. The demo's Data page deliberately shows two versions of the
   cleaned base — one from the seed, one from the pipeline run.
3. **Refusal.** A step that cannot honour its contract fails loudly instead of passing a
   wrong result downstream: the dbt tests in B3, the closed input signature at predict time.

---

## 7. Reference implementation

When the rebuild and this note disagree, this is the arbiter. It uses no platform, no
database and no object store — only the generator, the cleaning statement, the feature
script and the dbt models, imported from the demo's own sources so it cannot drift from
them.

```bash
cd backend
python -m scripts.papai_mirror_facts --with-fits
```

It prints every figure in §8. On the reference environment (Python 3.12, polars 1.44.0,
scikit-learn 1.9.0, skrub 0.10.0, duckdb) it reproduces the platform's recorded metrics
**to six decimals**: 0.836610 / 0.864133 / 0.853761.

To inspect intermediate frames rather than the summary, the pieces are importable
individually:

```python
from scripts.gen_nawa_telecom_data import churn_raw_frame, clean_churn_frame, network_cell_frame
from scripts.papai_mirror_facts import feature_frame, watchlist_frame

raw = churn_raw_frame()                  # 8 412 × 24
cleaned = clean_churn_frame(raw)         # 6 903 × 22, via the node's own SQL
features = feature_frame(cleaned)        # 6 903 × 31
watchlist = watchlist_frame(network_cell_frame())   # 72 × 13
```

---

## 8. Acceptance checklist

Tick these off and the mirror is faithful. Every line is printed by §7's command.

### Inputs

| Check | Expected |
|---|---|
| Raw export rows × columns | 8 412 × 24 |
| Distinct subscribers / duplicate rows | 8 000 / 412 |
| Distinct `region` spellings / `plan` spellings | 28 / 6 |
| `line_status = 'suspended'` rows | 677 |
| `arpu_mad` empty / at `-1` | 310 / 170 |
| `nps` empty | 1 383 |
| Raw churn rate | 22.18 % |
| Radio KPI rows × columns | 24 192 × 12 |
| Cells / sites / regions | 72 / 71 / 7 |
| KPI window | 2026-08-10 00:00 → 2026-08-23 23:00 |
| Max `prb_utilization_pct` / rows at 100.0 | 94.9 / **0** |

### Pipeline A

| Check | Expected |
|---|---|
| Cleaned base rows × columns | **6 903 × 22** |
| Distinct `region` / `plan` after normalisation | 7 / 3 |
| Null or negative `arpu_mad` | 0 |
| Null `nps` in the cleaned base | **1 144** (16.6 %) |
| Cleaned churn rate / positives | 22.16 % / 1 530 |
| Feature table rows × columns | **6 903 × 31** |
| `tenure_band` split | 429 new / 1 291 established / 5 183 loyal |
| `on_promo` / `nps_answered` sums | 2 380 / 5 759 |
| Training columns (v3) / same set after one-hot | 29 / 43 |
| Split rows | 5 177 train / 1 726 test |
| ROC AUC v1 / v2 / v3 | **0.836610 / 0.864133 / 0.853761** |
| Ranking | v2 > v3 > v1, and v2 − v1 = +0.027523 |
| Serving version before the promotion | **v1** |
| Scored table rows × columns | **6 903 × 34** |
| Columns appended by scoring | `prediction`, `confidence`, `score_1` |
| Subscribers flagged / riskiest-decile churn | ≈1 000 / ≈77 % — **×3.5 the base rate** is the claim |

### Pipeline B

| Check | Expected |
|---|---|
| Staging rows | 24 192 (unchanged) |
| Watchlist rows × columns | **72 × 13** |
| Bands | **9 critical / 8 watch / 55 healthy** |
| Cells climbing more than +20 PRB points | **3** (+21.32, +27.80, +27.56) |
| Those three, a fortnight earlier | 67, 59, 59 % PRB — all `healthy` |
| Cells falling more than −10 points | **2** (−20.64, −17.43) |
| Fourth largest movement, either way | +2.42 / −1.34 |
| Data tests | `cell_id` unique + not null, `risk_band` in the three values |

---

## 9. What the platform adds beyond the data plane

Out of scope for a data/ML mirror, listed so the two demos can be compared without
surprises. Detail in [`DEMO-SCRIPT.md`](./DEMO-SCRIPT.md).

- **A retention brief written by an LLM** as the last node of the churn pipeline, consuming
  the scored table and naming the three segments most at risk with the revenue at stake.
  The only LLM anywhere in the case, and it sits **after** the data plane, never inside it.
- **The champion published as a callable skill**, with a provenance chip that is *derived*
  rather than frozen: after the promotion it reads v2 without anybody editing it.
- **A scoped API key and a `/predict` endpoint** whose payload convention is
  `mlflow models serve`'s (`{"inputs": [...]}`), so an existing MLflow client works with no
  adapter. The 20-column signature is mandatory and closed: forget one field, or invent
  one, and the call is refused by name.
- **An interactive playground** pre-filled with the training set's typical row, showing
  per-row contributions.
- **Artifacts in MLflow format** on object storage, with a real MLflow Model Registry in a
  SQL store — no MLflow server operated. A stock client that knows nothing about Agentium
  can resolve the `champion` alias and load the model.

---

## 10. What silently changes the figures

Ordered by how often each one actually bites. Read this before starting.

1. **A different seed.** Every number in this note is tied to `--seed 20260825`. Another
   seed gives a coherent but different world.
2. **Unordered SQL output.** No `ORDER BY msisdn` at the end of §A2 and the split lands on
   different rows each run; the metrics wobble in the third decimal with no visible cause.
   The row *set* stays correct, which is what makes it hard to spot.
3. **Dropping the `nps` holes.** Costs 1 144 rows and part of the model's edge. The holes
   are signal; keep them.
4. **Imputing `arpu_mad = -1` instead of removing it.** The model learns that −1 MAD
   predicts churn.
5. **`msisdn` left in the feature list.** A near-unique identifier as a feature either leaks
   or adds pure noise, depending on the encoder. Exclude it explicitly.
6. **The same preprocessing for both estimators.** One-hot + impute + scale for the trees
   costs them their native handling of categoricals and of missing values, which is most of
   the v2 − v1 gap. Per-estimator preprocessing is the point, not an accident (§A4.1).
7. **A CSV reader that fills empties with 0.** Turns two "unknown" markers into two
   plausible values, and neither is removable afterwards.
8. **Integer feature columns not cast to float.** The fit succeeds and prediction later
   refuses any row with a hole, because the signature written at fit time is enforced.
9. **Clipping `prb_utilization_pct` at 100.** Flattens the busy-hour peaks, zeroes the
   week-over-week delta for the most saturated cells, and hides the three cells the
   watchlist exists to surface.
10. **A library upgrade.** scikit-learn or skrub moving can shift a metric in the third or
    fourth decimal. The **ordering** (v2 > v3 > v1) is the claim that must hold; the six
    decimals are the reference environment's.
11. **Scoring with the version just trained** instead of the serving one. Produces a
    plausible score sheet attributed to the wrong model, and no count reveals it.
