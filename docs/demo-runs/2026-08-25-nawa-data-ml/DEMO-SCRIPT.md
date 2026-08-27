# NAWA demo — Data / ML: from a dirty export to a served model (7 beats)

Rehearsed locally on 25/08/2026 (UTC) on a blank Postgres and a blank object store,
seed replayed from nothing: `backend/scripts/seed_nawa_data_demo.py`. **Deployed and
replayed on the `omnirag-demo` VM on 26/08/2026** — the identifiers below are the VM's
(see [§ Deployment](#deployment--what-was-done)).

The demo is delivered **in English**, and so is everything it seeds: dataset names, node
labels, the bands the tables carry, the brief the LLM node writes. The `nawa` workspace
declares `presentation.locale = en`, so the chrome opens English on whatever browser the
room has; nobody has to remember the switcher.

The thread: a telecom subscriber base arrives the way exports really arrive — duplicates,
suspended lines, regions spelled four different ways, a revenue column full of holes and a
`-1` that means "unknown". In seven beats it becomes a churn model served behind an API
key, and a second dbt pipeline produces a radio watchlist. **No LLM anywhere in the data
path**: SQL, Polars, scikit-learn, dbt.

This runbook is the presenter's script. The figures it quotes are not illustrative: they
come from the seed replayed on 26/08 and are reproducible from the seed value
(`--seed 20260825`, the default).

## Identifiers (VM `omnirag-demo`, state of 26/08 10:00 UTC)

The UUIDs change on every seed — the only content in this runbook that is not reproducible
from the seed value. These are **the VM's**; replaying the seed elsewhere produces other
identifiers and the **same** figures.

| Object | Value |
|---|---|
| URL | `https://agentium.papai.ai` — served revision `4483dd1a34eb` |
| Workspace | `nawa` — id `b337fdbf-2689-436e-a287-2fe903ca47cf`, `presentation.locale = en` |
| System 1 | `Churn Radar` — id `5e0937e3-652c-4eaf-addc-b25ec68e7ba6`, active |
| System 2 | `Radio Watch` — id `00548e30-e8ea-4bab-a138-31b308af487e`, active |
| Served model | `Churn Radar` **v1** (`linear`) |
| Challenger | **v2** (`gradient_boosting`); v3 is the Flow's own fit |
| Published skill | `ws.b337fdbf-2689-436e-a287-2fe903ca47cf.predict_churn_radar` |
| API key | minted by the seed; the full secret is shown once, at creation |
| MLflow registry | database `mlflow`, registered model `b337fdbf.churn-radar`, alias `champion` → v1, `challenger` → v2 |

Seven datasets, and the lineage reads in order:

| Dataset | Version | Rows | Columns | Produced by |
|---|---|---|---|---|
| `subscriber-base-raw-export` | v2 | 8 412 | 24 | the upload |
| `radio-cell-kpis` | v2 | 24 192 | 12 | the upload |
| `subscriber-base-cleaned` | v2 | 6 903 | 22 | the seed (duckdb SQL) |
| `subscriber-base-cleaned` | v3 | 6 903 | 22 | the Flow's `SQL cleanup` node |
| `subscriber-base-features` | v1 | 6 903 | 31 | the `Polars features` node |
| `subscriber-base-scored` | v1 | 6 903 | 34 | the `Score the base` node |
| `cells-at-risk-7-days` | v2 | 72 | 13 | Radio Watch's dbt node |

Read the version column as a count of how often a slug has been written, not as
part of the story: `--reset` retires the previous incarnation rather than
erasing it, so every re-seed increments the ones it rewrites. What the demo
actually rests on is the shape, and that is fixed — one version of each table
except `subscriber-base-cleaned`, which has two because the seed builds it once
and the Flow builds it again in front of the room.

## The figures to know by heart

- **8 412 → 6 903.** Exact, not sampled, and in this order: 412 duplicates first
  (8 000 remain), then out of what remains 640 suspended lines + 297 empty ARPU
  + 160 ARPU at `-1`, three disjoint blocks. 8 000 − 1 097 = 6 903.
- **Three versions, a measured ranking**: v1 `linear` **0.836617** · v2
  `gradient_boosting` **0.864133** · v3 `gradient_boosting` on the 29 engineered
  columns **0.853761**. Promoting v1 → v2 is worth **+0.027516** ROC AUC.
- **v3 does not win**, and it is left that way. A registry exists precisely so it
  can say a challenger lost.
- **Churn rate of the cleaned base: 22.16%.** The model flags 1 000 out of 6 903;
  the riskiest decile churns at **77.4%**, or **×3.5** the base rate.
- **Radio watchlist: 9 `critical`, 8 `watch`, 55 `healthy`** across 72 cells. Three of
  the nine critical ones were healthy a fortnight ago (deltas of +21 to +28 PRB points).

## Pre-demo checklist (15 min before)

1. **Data** page: the 7 datasets, all `ready`. The raw one at 8 412 and the watchlist at
   72 are the two ends of the story.
2. **Models** page: 3 versions of `Churn Radar`, **v1 marked as serving**. If v2 already
   serves, beat 5's promotion has nothing left to show — put v1 back.
3. **Skills** page: `predict_churn_radar` visible with its provenance chip
   ("answers from Churn Radar v1").
4. `/systems/5e0937e3-652c-4eaf-addc-b25ec68e7ba6/flow` (Churn Radar) and
   `/systems/00548e30-e8ea-4bab-a138-31b308af487e/flow` (Radio Watch) open with the badges
   already on the nodes (one run behind each).
5. API key in the demo terminal's clipboard, `curl` replayed **once** before going on
   stage: the first call pays for loading the model (~5 s), later ones do not, and that is
   a talking point rather than an incident.
6. Browser zoom at 100%, theme to the audience's taste.

---

## Beat 1 — The export arrives dirty (~4 min)

**Click-path**: Build → Data → `Subscriber base — raw export`.

1. **8 412 rows, 24 columns.** The column profile reads without a query: distributions,
   fill rates, cardinalities.
2. **Show the dirt, column by column** — this is what makes beat 2 necessary:
   - `region`: **28 distinct values for 7 regions**. Four source systems, four
     conventions: `Casablanca-Settat`, `CASABLANCA-SETTAT`, `casablanca-settat`,
     `« Casablanca-Settat »` with spaces.
   - `plan`: 6 spellings for 3 offers (`PREPAID` / `prepaid`…).
   - `arpu_mad`: **310 empty** and **170 at `-1`**. The `-1` is the trap: an "unknown"
     that the export writes as a number. A model trained on it learns that
     *−1 MAD predicts churn*.
   - `line_status`: 677 `suspended` rows — subscribers who cannot terminate, and who
     therefore have nothing to teach a voluntary-churn model.
   - `msisdn`: **412 numbers appear twice**, with an older `snapshot_date` and staler
     counters. A naive dedup would keep the wrong row.
   - `nps`: 1 383 empty. **That one does not get cleaned** — a subscriber who has stopped
     answering the survey is a signal, not a defect. We come back to it in beat 5.

**The argument**: none of this is decorative. Every defect corresponds to one line of
beat 2's SQL, and the total number of rows removed is verifiable to the unit.

## Beat 2 — The SQL that cleans, and its badge (~5 min)

**Click-path**: Build → Systems → `Churn Radar` → Flow → `SQL cleanup` node.

1. **The SQL workshop** in the inspector: duckdb, autocompletion over the upstream
   dataset's schema (typing `arp` offers `arpu_mad`). This is not a text field.
2. **Read the query out loud** — it does four things and nothing else:
   - `ROW_NUMBER() OVER (PARTITION BY msisdn ORDER BY snapshot_date DESC)` then
     `snapshot_rank = 1`: keep each subscriber's **latest** snapshot.
   - `lower(trim(region))` and `lower(trim(plan))`: one spelling per region.
   - `line_status = 'active'`: the suspended lines leave.
   - `arpu_mad IS NOT NULL AND arpu_mad >= 0`: the holes **and** the `-1` sentinel.
3. **`ORDER BY msisdn` at the end of the query** — the line that looks decorative and is
   not. duckdb is parallel: without it the row order changes from one run to the next, the
   train/test split is positional, and the metrics quoted on stage stop being the
   rehearsal's.
4. **The node's badge: `8 412 → 6 903 rows`.** Do the arithmetic live: the raw table holds
   677 suspended lines, 310 empty ARPU and 170 sentinels, but the dedup runs **first** and
   takes 412 stale rows with it — some of which were themselves suspended or holed. On the
   8 000 that remain: 640 + 297 + 160 = 1 097, and 8 000 − 1 097 = **6 903**. Exact, not
   rounded.

   If somebody asks whether the order matters: **here, no** — a stale re-export carries the
   same defects as the row it copies, so filtering first lands on the same 6 903 rows.
   Say so rather than bluffing. The rule is still real, and it is why the statement is
   written this way round: on data where a stale snapshot can be clean while the current one
   is not, filtering first resurrects the old row for a subscriber who should have been
   dropped.

**The argument**: the cleanup is a governed, versioned transformation with its lineage —
`subscriber-base-cleaned` v2 points at `subscriber-base-raw-export` v1. Not a notebook on
somebody's laptop.

## Beat 3 — The features, in Polars (~4 min)

**Click-path**: same Flow, `Polars features` node.

1. **22 → 31 columns**, nine derived: `arpu_per_month`, `gb_per_mad`, `friction_score`,
   `friction_per_mad`, `usage_index`, `mobility_index`, `tenure_band`, `on_promo`,
   `nps_answered`.
2. **Why ratios**: what predicts a departure is not revenue, nor the number of tickets,
   but revenue **per month of tenure** and friction **per dirham billed**. A tree
   approximates a ratio badly with orthogonal splits, so handing them over explicitly
   moves the metric for a real reason.
3. **`nps_answered`**: non-response becomes a column. We make explicit the signal the
   hole already carried.
4. **The harness**: the author's Python runs in an isolated venv, built on demand and
   cached by dependency fingerprint — this one, `polars==1.44.0`, cost 5.2 s and 231 MB
   once, and nothing on later runs. This is not `exec()` in the worker.

## Beat 4 — Training and the model card (~6 min)

**Click-path**: same Flow, `Churn training` node → then Build → Models.

1. **The training node**: `ml_train_sklearn_v1`. Target `churn`, 29 columns, estimator and
   split declared in the graph's configuration. The badge on the 26/08 run reads
   `6 903 rows · roc_auc 0.853761`. The metric is the same every time; the wall
   clock is not — 15 s on an idle VM, three times that when the box is busy
   building images, which is worth knowing before promising a number out loud.
2. **The Models page, three versions of the same lineage.** Open **v2** — the model card
   is built to be projected: metrics, confusion matrix, ROC and precision/recall curves,
   importances, input signature, lineage back to the exact dataset.
3. **Where the artifacts live**: MLflow format on the object store (MinIO on the VM), and
   a **real MLflow Model Registry** in an `mlflow` database of the existing Postgres — no
   MLflow server to operate, the client writes straight into the SQL store. A model is a
   governed object, not a `.pkl` in a bucket.
4. **And the "no lock-in" sentence is checkable in the room**, with a stock MLflow client
   that knows nothing about Agentium — this is the moment for the sceptics:

   ```python
   from mlflow.tracking import MlflowClient
   c = MlflowClient(tracking_uri="postgresql://…/mlflow", registry_uri="postgresql://…/mlflow")
   v = c.get_model_version_by_alias("b337fdbf.churn-radar", "champion")   # → v1
   import mlflow.pyfunc; mlflow.pyfunc.load_model(v.source).predict(rows)  # bytes on MinIO
   ```

   Measured on 26/08 against the live VM: `champion` → v1, seven artifacts pulled
   off MinIO, a 20-column signature, the run's `roc_auc` **0.836617** — the card's
   figure, read out of the registry.
5. **The evaluation itself is kept**, not only its summary: the card shows "Evaluation
   kept — 173 kB, skore report 0.25.0, reloadable". The run carries its location (tag
   `agentium.skore_report_state`), and `EstimatorReport.from_dict` reopens it with its
   **1 726 test rows** and its cached predictions. The concrete consequence: a metric
   nobody asked for at fit time can be computed afterwards **on the rows the card talks
   about**, instead of being replayed on a split that would no longer be the same.
6. **The detail that makes the data scientists in the room sit up**: `nps` has 1 144 holes
   in the cleaned base. Boosted trees route them down a branch and **read** the
   non-response; logistic regression cannot — so the harness adds a
   `SimpleImputer(strategy="median")` for it, decided per estimator from scikit-learn's
   `allow_nan` tag. The hole is filled for the linear model and exploited by the tree
   model. That is exactly where beat 5's gap comes from.

## Beat 5 — The promotion, with a real delta (~5 min)

**Click-path**: Build → Models → compare v1 / v2 / v3 → **Promote** v2.

1. **The ranking, as each card recorded it** — same 6 903-row base, same seed, and for
   v1/v2 the same split (v3 trains on the derived features):

   | Version | Estimator | Columns | ROC AUC |
   |---|---|---|---|
   | v1 | `linear` | 20 | **0.836617** ← serves before the demo |
   | v2 | `gradient_boosting` | 20 | **0.864133** |
   | v3 | `gradient_boosting` | 29 (+ derived) | 0.853761 |

2. **v2 beats v1 by +0.027516.** Say *why*: churn in this base is not additive. A ticket in
   the first year is a resignation letter; the same ticket on an eight-year line is a call
   to support. A logistic regression cannot represent a product of two variables. The
   baseline was not handicapped — the world is not additive.
3. **v3 does not win** (0.853761 < 0.864133) and we show it. A registry that could not say
   "this retrain lost" would be useless. Nobody promotes v3.
4. **"Compare on the same rows" → Re-evaluate both versions**, in the Comparison tab, and
   this is the point that separates a platform from a dashboard. The delta tiles subtract
   two *recorded* results; here, both pipelines are rescored on **one** split and the joined
   table comes from `skore.ComparisonReport`. Measured on 26/08, v1 against v2 on the same
   1 726 rows:

   | Metric | v1 `linear` | v2 `gradient_boosting` |
   |---|---|---|
   | ROC AUC | 0.836617 | **0.864133** |
   | Accuracy | 0.833720 | **0.852260** |
   | Precision | 0.698347 | **0.766667** |
   | Recall | 0.441253 | **0.480418** |
   | Log loss | 0.389011 | **0.367198** |
   | Brier | 0.121770 | **0.109443** |

   Both columns land **exactly** on what each card announces, which is the proof that the
   split really was reconstructed. And v2 wins on all six, including the two calibration
   metrics — the score is not only better ranked, it is more *believable*, which is what
   matters when it shows up as a gauge in beat 6.
5. **Comparing v2 and v3 raises a warning**, and it should be read out loud: v3 was trained
   on `subscriber-base-features`, not on `subscriber-base-cleaned`. The comparison
   therefore runs on the more recent of the two datasets and flags that the other was
   fitted elsewhere. Refusing would have made the only interesting comparison impossible;
   answering without saying so would have been worse.
6. **The registry also names the contender**, and that is what makes the champion/challenger
   story legible from outside. The yellow "Contender" chip on the card is the same fact as
   the `challenger` alias: **the best version that is not serving**, not the most recent.
   Before the promotion, `champion` → v1 and `challenger` → v2 — so v2, not v3, even
   though v3 is the latest fit. Say it out loud: a registry that named "the latest" would
   often name the worst, and that is precisely why promotion stays a human act.

   ```python
   c.get_model_version_by_alias("b337fdbf.churn-radar", "champion")    # → v1
   c.get_model_version_by_alias("b337fdbf.churn-radar", "challenger")  # → v2
   ```

   An A/B between the incumbent and its rival therefore needs **nothing** from our tables:
   two aliases are enough.
7. **Promote v2**, and stay on the page: the "serves" chip moves, the MLflow registry's
   `champion` alias follows, **and the two aliases swap** — `challenger` falls back to v1,
   the version just demoted, instead of staying on the winner. The published skill's
   provenance follows on its own (beat 6).

## Beat 6 — Serving: Playground, skill, API key (~7 min)

**Click-path**: Models → `Churn Radar` → Playground tab.

1. **The Playground opens pre-filled** — the training set's typical row (median of the
   numerics, most frequent level of the categoricals). Nobody demonstrates a model by
   typing forty fields.
2. **Change one thing and watch**: take `support_tickets` from 0 to 3 and empty `nps`. The
   score rises, and the **per-row contributions** say which columns pushed. A prediction
   without an explanation cannot be defended to a business owner.
3. **Two subscribers, for contrast** (v1 serving):

   | Profile | Churn score |
   |---|---|
   | Prepaid, 4 months, 3 tickets, 7 dropped calls, survey unanswered | **high** |
   | Postpaid 2-year, 74 months, fibre, 4 lines, 0 tickets, NPS 9 | **near zero** |

   And the first row's contributions read in the order you would narrate them:
   `tenure_months` 4 against a typical 49, `support_tickets` 3 against 1, the promo in
   progress.

   **A version off the alias answers too, and says so.** Open v3 from the Versions tab and
   press Predict there: the form is v3's own contract — twenty-nine columns against v1's
   twenty — and the line by the button reads `answered by v3`. The card names its own
   version, so the answer is that version's; the champion's card stays unpinned, which is
   why the cURL on it keeps the shape `mlflow models serve` takes. Worth thirty seconds if
   the room asks "so can I try the challenger before promoting it?" — the answer is yes,
   and the same row scored by two versions is the comparison tab made concrete.

4. **Publish as Skill**: the model becomes callable by an agent. Go to the Skills page and
   show the **provenance chip** — it says "answers from Churn Radar v1", and it is
   *derived*, not frozen at publication: after beat 5's promotion it reads v2 without
   anybody touching it.
5. **The API key, and the cURL**:

   ```bash
   curl -X POST "$AGENTIUM/api/v1/ml-models/<model-id>/predict" \
     -H "X-API-Key: agpk_…" -H 'Content-Type: application/json' \
     -d '{"inputs":[{"region":"casablanca-settat","plan":"prepaid","contract":"monthly",
          "tenure_months":4,"arpu_mad":38.5,"support_tickets":3,"dropped_calls":7,
          "nps":null, …}]}'
   ```

   The signature's 20 columns are **mandatory and closed**: forget one, or invent one, and
   the answer is `ML_PREDICT_FIELD_UNKNOWN` with the offending field names. A contract that
   accepted anything would not be a contract.

   The payload convention is `mlflow models serve`'s (`{"inputs": […]}`): an existing
   MLflow client works with no adapter.

6. **Three things to point out in the response**:
   - a `served` block — which version answered, which estimator, which metric. A
     prediction without its issuer is not auditable;
   - `cached: false` with a `load_ms` of several seconds on the process's first call,
     `cached: true, load_ms: 0.0` on the second, **same prediction**. `load_ms` is what
     *this* call paid to have the pipeline in memory — the cache is an optimisation, not a
     second code path;
   - after beat 5's promotion, **the same key and the same URL answer from v2**. Promoting
     is moving what production serves.
7. **Missing or wrong key → 401.** Usage is counted per key (`use_count`, `last_used_at`):
   a key left lying around is visible.

## Beat 7 — The other pipeline: dbt, and its blocking tests (~6 min)

**Click-path**: Build → Systems → `Radio Watch` → Flow → `dbt — cells at risk` node.

1. **24 192 rows in** (72 cells × 14 days × 24 h), **72 out**. A real dbt-duckdb project:
   `stg_cell_hourly` (staging) then `mart_cell_risk` (mart).
2. **The mart says what it does**: busy hour only (19:00–23:00 — a cell that saturates at
   3 am is not a customer problem), and the last seven days against the seven before them,
   because a level without a trend does not tell an engineer where to go.
3. **The `critical` band in full** — 9 cells out of 72 (plus 8 `watch`, 55 `healthy`):

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

4. **The star move is the delta column.** The first six rows have been saturated for
   months — deltas between −0.33 and +0.34, i.e. motionless: the radio engineer knows them,
   they are already on his plan and they teach nobody anything. The three in bold were
   **healthy a fortnight ago** (67, 59 and 59% PRB) and went critical in the last week,
   with a dropped-call rate up by more than a point. They are the only three rows in the
   whole table that really move: the fourth largest movement in the file is at **+2.42**.
   A threshold on the level would have drowned them among the other six; the trend isolates
   them.
5. **And it reads both ways**: `CAS-831-N65` at **−20.64** (50.86% PRB) and `RBA-142-L70`
   at **−17.43** (45.09%) — two cells that a capacity upgrade relieved, and the third
   negative movement is only at −1.34. A trend column that never went down would not be
   believed.
6. **The dbt tests, and why they are the subject**: `unique` and `not_null` on `cell_id`,
   `accepted_values` on `risk_band`. A cell appearing twice in a watchlist, or a
   utilisation of 140%, means the pipeline is wrong — and the node **refuses to publish**
   rather than passing that downstream. That is the difference between a pipeline and a
   script.

---

## Known traps

1. **v2 already promoted**: if an earlier rehearsal promoted v2, beat 5 has no move left.
   The seed **does not reassign** the champion (deliberately: it does not undo an
   operator's promotion), so v1 has to be put back by hand before the demo.
2. **The first `curl` pays for the load** (~5 s to deserialise the MLflow model). Replay it
   once before going on stage; or own it and read the `cached: false` out loud — that is
   beat 6 point 6.
3. **Two settings are mandatory** for the Polars and dbt nodes to execute:
   `RECIPE_EXECUTION_ENABLED=true` and, with no Celery worker, `WORKER_EAGER_MODE=true`.
   Without them the run still completes, but those two nodes report their refusal.
4. **First dbt run is slow**: it builds a `dbt-duckdb` venv, measured at 13.2 s for 329 MB,
   cached afterwards by dependency fingerprint. Run Radio Watch once before the demo.
5. **Two versions of `subscriber-base-cleaned`** on the Data page (v1 from the seed, v2 from
   the Flow). This is correct and explainable: the seed prepares the state, the Flow does
   the work for real. Do not present it as an accidental duplicate.
6. **Regenerating the data changes the figures**: every number here is tied to
   `--seed 20260825`. Another seed gives another world, coherent but different.
7. **Re-seeding after a copy change**: `--reset` retires the demo's own datasets and model
   versions first, so a renamed lineage replaces the old one instead of sitting beside it.
   It discards the champion promoted on stage, which is exactly why it is not the default.

## Rehearsal evidence (26/08, live VM)

This table is the run against the **live VM**, through the API driver, with no database or
object-store access. The deployment observables (SHA, dump, migrations, canaries) are in
the journal: [`agentium-safe-vm-deployment.md`](../../ops/agentium-safe-vm-deployment.md).

| Check | Result |
|---|---|
| Seed replayed with `--reset` on the VM | 7 datasets `ready`, 3 models, 2 systems active, no French artifact left |
| `subscriber-base-cleaned` | 6 903 rows from 8 412, exact |
| Fit v1 / v2 / v3 | roc_auc 0.836617 / 0.864133 / 0.853761 |
| Champion after seed | v1, not reassigned |
| Run Churn Radar | completed, 7 nodes, none failed (clean 270 ms · features 3.2 s · train 46.2 s · score 12.8 s · brief 5.8 s, on a VM that was building images at the time) |
| Run Radio Watch | completed, 3 nodes, dbt 72 rows |
| `verify_nawa_data_ml_plane` | every line `ok`, no `DRIFT` |
| MLflow registry | 3 versions of `b337fdbf.churn-radar`, `source` → the object store, alias `champion` → v1, `challenger` → v2 |
| Foreign MLflow client | `get_model_version_by_alias(…, "champion")` → v1, `pyfunc.load_model(v.source)` loads, 20-column signature |
| Comparison on the same rows | v2 > v1 on all 6 metrics; both columns land on the cards' figures |
| Published skill + minted key | `predict_churn_radar` |
| `POST /predict` with the key | 200, `served` v1 |
| Radio watchlist | 9 critical / 8 watch / 55 healthy |
| No cell-hour at the ceiling | 0 / 24 192 at 100.0% PRB |
| Workspace locale | `presentation.locale = en`; the chrome opens English with no stored preference |

## Deployment — what was done

The slice has been on `omnirag-demo` since 26/08. The detail (SHA, dump, migrations,
observables, canaries) is in the journal:
[`agentium-safe-vm-deployment.md`](../../ops/agentium-safe-vm-deployment.md), the 26/08
iteration. What matters to a presenter:

- served revision **`4483dd1a34eb`**, `revision_verified: true` on localhost and on the
  public URL;
- `096_tabular_data_plane` then `097_ml_training_plane` applied, `alembic current`
  = `097_ml_training_plane`;
- the `mlflow` database in place on `agentium-pg`, owner `agentium`. No MLflow server is
  operated: the client writes into it directly, no port, no container. MLflow creates its
  own schema on first connection — that is not an Alembic revision, and
  `MLFLOW_TRACKING_URI` must **not** be set in the compose environment, the client being
  configured in code;
- the managed venvs (`polars`, `dbt-duckdb`) are built and cached under
  `/srv/agentium-data/recipe_envs`: the demo's first run pays for no build;
- to restore or replay elsewhere: `scripts/agentium-data-plane-dump.sh <sha12>` takes all
  three parts (the `agentium` database, the `mlflow` database, the object prefixes) and
  checks that every artifact the registry names is inside the window. Since revision 096 a
  `pg_dump` alone is no longer restorable: the dataset and model rows point at MinIO objects
  that are not in the dump. The other prerequisites are in
  [`agentium-data-plane-provisioning.md`](../../ops/agentium-data-plane-provisioning.md).

### Six defects only the VM showed

They are here because they say where to look if the demo behaves differently from what is
written. All are fixed in the served revision; the detail is in the journal.

1. **The migration chain refused to apply.** Five of `097`'s columns were written *also* in
   `096`: invisible locally where the database starts from nothing, fatal on the only
   database that applies the chain for real (`DuplicateColumn`).
2. **The brief's LLM node answered "could not parse the JSON body".** The upstream node puts
   an object under its envelope's `model` key, which the wrapper took for a model name and
   passed straight to the API.
3. **The dbt node died on the VM and nowhere else.** `RLIMIT_AS` counts *reserved* address
   space, and glibc reserves a 64 MiB malloc arena per thread, up to eight per core: on the
   VM's 16 cores the arenas alone consume the 3 GiB budget, and the first thread dbt starts
   dies in the allocator (`cannot allocate memory for thread-local data: ABORT`) before the
   project's SQL runs. `MALLOC_ARENA_MAX` is now pinned for every supervised child.
4. **The "foreign" MLflow client would not load from MinIO.** A version's `source` there is
   an `s3://` URI, and mlflow's S3 artifact repository imports `boto3` by name — `botocore`,
   which `s3fs` already brings for our own reads, is not enough. Locally the object store
   hands out `file://`: the step meant to prove portability was the only one never exercised
   where it counts.
5. **`/predict` refused the artifact, citing `torchvision`.** `skops.io` builds its type
   tables at import by interrogating all of `sys.modules`; in the backend `transformers` is
   already there and its lazy import walks image processors that assume a `torchvision`
   absent from the image. The peer is now installed with `torch`, and the scan is paid at
   startup rather than on the first prediction.
6. **The serving model card's Comparison tab was empty.** The detail route serialised the
   versions without their scores, and the front compared against the *previous* version —
   which a v1 does not have. That is this demo's beat 5: check it first if the tab says
   "nothing to compare" while the lineage has three.

A seventh defect is invisible from the demo but visible from the registry: deleting a model
cleaned up the aliases, never the registered version. Four registered models still answered
`@champion` after all their versions had been deleted. If a foreign MLflow client is plugged
in during the demo, it now sees only `b337fdbf.churn-radar`.
