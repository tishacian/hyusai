"""Deterministic synthetic telecom data for the Nawa demo.

Two tables, one operator's month:

* ``churn_raw_frame()`` — a subscriber base as an export actually arrives:
  duplicated snapshots, suspended lines, regions spelled four ways, a revenue
  column with holes and a ``-1`` sentinel. The demo's first SQL node earns its
  keep by cleaning it, and the badge on that node reads
  **8 412 → 6 903 lignes** because those two numbers are exact, not sampled.
* ``network_cell_frame()`` — hourly radio KPIs per cell, with a busy hour, a
  weekend, six chronically congested cells, three that degrade sharply inside
  the recent week and two a capacity upgrade relieved. That is what gives the
  dbt node something true to assert: its watchlist comes back with nine cells in
  the ``critique`` band, of which the three the delta column singles out were
  healthy a fortnight ago.

Everything is a pure function of a seed. The same seed gives the same bytes on
any machine, which is what lets the demo be rehearsed: the churn label is a
noisy logit rather than a rule, so a fit lands near AUC 0.86 — high enough to be
worth showing, low enough that nobody in the room suspects a leak.

The label is generated so that the demo's model ranking is a fact about the data
rather than a story told over it. Measured on the cleaned base, held out at 25%:

===========================================  =========
Fit                                          ROC AUC
===========================================  =========
Logistic regression, 20 cleaned columns          0.835
Boosted trees, same 20 columns                   0.860
Boosted trees, plus the 9 derived columns        0.856
===========================================  =========

The middle row beats the first because the world is genuinely non-additive and a
linear model cannot represent a product; see ``_churn_logit``. The third row does
*not* beat the second, and that is left as it measured — a registry earns its
place by telling you when a challenger failed to win, and a demo that quietly
reversed the number would be teaching the opposite lesson.

Usage:
    cd backend
    python -m scripts.gen_nawa_telecom_data --out-dir /tmp/nawa            # CSV
    python -m scripts.gen_nawa_telecom_data --out-dir /tmp/nawa --parquet
    python -m scripts.gen_nawa_telecom_data --describe                     # no write
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Shape of the subscriber base
# ---------------------------------------------------------------------------

#: Distinct subscribers. Every one of them gets exactly one canonical row.
SUBSCRIBERS = 8_000
#: Stale snapshots re-exported for subscribers already in the file. They carry an
#: older ``snapshot_date`` so a dedup on "latest per msisdn" keeps the good row.
DUPLICATE_ROWS = 412
#: Rows the cleaning step drops, by reason. Disjoint by construction, so the
#: cleaned count is arithmetic rather than luck.
SUSPENDED_LINES = 640
MISSING_ARPU = 297
SENTINEL_ARPU = 160

#: What the demo says out loud, and what the tests pin.
RAW_ROWS = SUBSCRIBERS + DUPLICATE_ROWS  # 8_412
CLEAN_ROWS = SUBSCRIBERS - SUSPENDED_LINES - MISSING_ARPU - SENTINEL_ARPU  # 6_903

#: The revenue value an export writes when it means "unknown". Keeping it in the
#: data is the point: a model trained on it would learn that -1 MAD predicts
#: churn, which is exactly the mistake the cleaning node exists to prevent.
ARPU_SENTINEL = -1.0

CHURN_TARGET = "churn"

#: How separable the label is from the drivers. The one dial that sets "how good
#: can a model get here", tuned so the demo's boosted fit lands near AUC 0.85 —
#: high enough to be worth showing, low enough that nobody in the room suspects
#: a leak. Measured rather than hoped: ``test_gen_nawa_telecom_data`` pins it.
GAIN = 2.15
#: Sets the base rate to ~22%, which is what a prepaid-heavy operator's churn
#: deck shows.
INTERCEPT = -1.80

#: How the three mechanisms in ``_churn_logit`` split the story, in units of
#: standard deviation. Levels are most of it, as they are in a real churn model;
#: the interaction share is sized to be the honest headroom the boosted trees
#: have over the linear baseline (see that function's docstring).
W_ADDITIVE = 1.00
W_RATIO = 1.00
W_INTERACTION = 1.35

#: Regions as the operator's own systems spell them, before anyone agrees.
REGIONS = (
    "Casablanca-Settat",
    "Rabat-Salé-Kénitra",
    "Marrakech-Safi",
    "Tanger-Tétouan",
    "Fès-Meknès",
    "Souss-Massa",
    "Oriental",
)
REGION_WEIGHTS = (0.29, 0.18, 0.13, 0.12, 0.11, 0.09, 0.08)

PLANS = ("prepaid", "postpaid", "hybrid")
PLAN_WEIGHTS = (0.52, 0.36, 0.12)
CONTRACTS = ("monthly", "annual", "two_year")
HANDSET_TIERS = ("entry", "mid", "premium")

#: Columns of the cleaned churn table, in the order the SQL node emits them.
#: The raw table adds `snapshot_date` and `line_status`, which cleaning consumes.
CHURN_FEATURE_COLUMNS = (
    "region",
    "plan",
    "contract",
    "tenure_months",
    "arpu_mad",
    "data_gb",
    "voice_minutes",
    "sms_count",
    "intl_minutes",
    "roaming_days",
    "support_tickets",
    "dropped_calls",
    "avg_download_mbps",
    "late_payments",
    "device_age_months",
    "handset_tier",
    "fiber_bundle",
    "family_lines",
    "promo_discount_pct",
    "nps",
)

# ---------------------------------------------------------------------------
# Shape of the radio KPI table
# ---------------------------------------------------------------------------

CELLS = 72
KPI_DAYS = 14
#: 72 cells × 14 days × 24 hours. Small enough to profile in a second, large
#: enough that a window function over it is a real query.
NETWORK_ROWS = CELLS * KPI_DAYS * 24

#: The window ends the evening before the reference date, so "last 7 days" in a
#: dbt model is a full week and not a partial one.
REFERENCE_DATE = date(2026, 8, 24)

#: PRB points per unit of offered load, below saturation. Set so a median cell's
#: busy hour reads near 50%, which is where an operator's fleet actually sits.
PRB_PER_LOAD = 44.0
#: Below this, a cell schedules everything it is offered and utilisation *is* the
#: offered load. Above it the counter bends: see ``_prb_from_offered_load``.
PRB_KNEE = 65.0
#: A share of a finite resource. Approached, never reached.
PRB_CEILING = 100.0
#: Where quality starts to bend. Below it a cell has slack and a subscriber
#: notices nothing; from here to the ceiling, throughput falls and latency and
#: dropped calls climb superlinearly, so the *perceived* knee lands near 80%.
PRB_QUALITY_ONSET = 62.0

#: The three populations the watchlist exists to separate, disjoint by
#: construction so a test can name them.
#:
#: Chronically saturated cells are the standing entries an engineer already
#: knows about. The ones that *matter* are the next two groups, and they are
#: drawn from the middle of the load distribution on purpose: a watchlist whose
#: movers are all cells already at the ceiling has nothing to say that a level
#: threshold did not already say.
CONGESTED_CELLS = 6
DEGRADING_CELLS = 3
#: And two that a capacity upgrade fixed mid-window, so the trend column reads
#: in both directions instead of being a one-way ratchet.
RECOVERING_CELLS = 2

SITE_PREFIXES = {
    "Casablanca-Settat": "CAS",
    "Rabat-Salé-Kénitra": "RBA",
    "Marrakech-Safi": "RAK",
    "Tanger-Tétouan": "TNG",
    "Fès-Meknès": "FEZ",
    "Souss-Massa": "AGA",
    "Oriental": "OUJ",
}


# ---------------------------------------------------------------------------
# Churn base
# ---------------------------------------------------------------------------


def _msisdn(index: int) -> str:
    """A Moroccan mobile number, stable per subscriber index."""

    return f"2126{index % 10}{index:06d}"[:12]


def _spelled_four_ways(rng: Any, regions: Any) -> list[str]:
    """The same region name, dirtied the way four source systems dirty it.

    Case and padding only: the cleaning node normalises them with `trim`/`lower`,
    and a demo that had to explain a fuzzy match would be a different demo.
    """

    styles = rng.integers(0, 4, len(regions))
    out: list[str] = []
    for region, style in zip(regions, styles, strict=True):
        text = str(region)
        if style == 1:
            text = text.upper()
        elif style == 2:
            text = text.lower()
        elif style == 3:
            text = f" {text} "
        out.append(text)
    return out


def _churn_logit(columns: dict[str, Any], np: Any) -> Any:
    """Why a subscriber leaves, as a score over the drivers and their products.

    Written as named effects rather than a fitted vector because the demo says
    them out loud: tickets and dropped calls push churn up, a fiber bundle and a
    family plan hold it down.

    The shape of this function is what makes the demo's three model versions an
    honest ranking rather than a staged one, so it is deliberate in two ways:

    * **Interactions**, not just a sum. Early friction is fatal where the same
      tickets on a ten-year line are noise; a bundle only protects a customer
      who signed something. A logistic regression cannot represent a product of
      two features, so the boosted trees beat the linear baseline because the
      world is genuinely non-additive — not because the baseline was hobbled.
    * **Ratios**, not just levels. What predicts a departure is revenue per
      month of tenure and friction per dirham billed. Axis-aligned splits
      approximate a ratio poorly, so handing the trees ``arpu_per_month`` and
      ``friction_score`` moves the metric for a real reason, which is what makes
      the demo's feature-engineering node worth its place on the canvas.

    ``GAIN`` and ``INTERCEPT`` are the only tuned numbers; see their comments.
    """

    tenure = columns["tenure_months"]
    arpu = columns["arpu_true"]
    tickets = columns["support_tickets"]
    dropped = columns["dropped_calls"]
    prepaid = columns["plan"] == "prepaid"
    monthly = columns["contract"] == "monthly"
    young = tenure <= 12

    # Levels: the effects an additive model can find on its own.
    additive = (
        0.050 * np.clip(30 - tenure, 0, None)
        - 0.010 * np.clip(tenure - 30, 0, None)
        + 0.30 * tickets
        + 0.055 * dropped
        + 0.42 * columns["late_payments"]
        - 0.026 * columns["avg_download_mbps"]
        + 0.016 * columns["promo_discount_pct"]
        + 0.010 * columns["device_age_months"]
        - 0.100 * columns["nps_true"]
        - 0.30 * columns["fiber_bundle"]
        - 0.19 * (columns["family_lines"] - 1)
        + 0.30 * prepaid
        + 0.24 * monthly
        - 0.30 * (columns["contract"] == "two_year")
        + 0.22 * np.isin(columns["region"], ["Oriental", "Souss-Massa"])
    )

    # Ratios: the same counters, per unit of what they should be judged against.
    # These are the columns the Polars node derives. Both are compressed before
    # they are used, because raw revenue-per-month reaches 109 for a one-month
    # premium line and that single tail, left alone, carries more variance than
    # every other driver combined — which would make the label a function of one
    # outlier column that every model learns equally well.
    arpu_per_month = arpu / (tenure + 1.0)
    friction_per_mad = (tickets + dropped / 4.0) / np.clip(arpu, 1.0, None)
    ratios = np.log1p(arpu_per_month) + 14.0 * np.minimum(friction_per_mad, 0.12)

    # Products: what no additive model can represent.
    interactions = (
        # A ticket in the first year is a resignation letter; the same ticket on
        # a settled line is a support call.
        1.00 * tickets * young
        # The bundle holds a committed subscriber and does nothing for a
        # month-to-month one, who can leave before the next invoice.
        - 0.85 * columns["fiber_bundle"] * (~monthly)
        # Discount-chasing on prepaid: the promo buys a month, not loyalty.
        + 0.030 * columns["promo_discount_pct"] * prepaid
        # A cell dropping calls past a knee is a different experience, not more
        # of the same one.
        + 0.60 * (dropped >= 6)
    )

    # Each mechanism is standardised before it is weighted, so the three weights
    # below read as the share of the story each one tells rather than as an
    # accident of the units the effects above happen to be written in. That is
    # what keeps the demo's model ranking honest: the interaction share is the
    # headroom the boosted trees have over the linear baseline, and the ratio
    # share is the headroom the derived features have over the raw columns. Tune
    # a coefficient for plausibility and these stay put.
    score = (
        W_ADDITIVE * _standardize(additive, np)
        + W_RATIO * _standardize(ratios, np)
        + W_INTERACTION * _standardize(interactions, np)
    )
    return INTERCEPT + GAIN * _standardize(score, np)


def _standardize(values: Any, np: Any) -> Any:
    """Centre and scale to unit variance, tolerating a constant column."""

    spread = float(values.std())
    centred = values - values.mean()
    return centred / spread if spread > 0 else centred


def churn_raw_frame(*, seed: int = 20260825, subscribers: int = SUBSCRIBERS):
    """The subscriber export, dirt included. ``RAW_ROWS`` rows by construction.

    Returns a polars frame. Row order is the export's own: canonical rows first,
    then the stale re-exported snapshots, so nothing about the shuffle can change
    which row a dedup keeps.
    """

    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed)
    count = int(subscribers)

    region = rng.choice(REGIONS, count, p=REGION_WEIGHTS)
    plan = rng.choice(PLANS, count, p=PLAN_WEIGHTS)
    contract = np.where(
        plan == "prepaid",
        "monthly",
        rng.choice(CONTRACTS, count, p=(0.34, 0.44, 0.22)),
    )
    tenure = rng.integers(1, 97, count)
    handset_tier = rng.choice(HANDSET_TIERS, count, p=(0.38, 0.44, 0.18))

    # Revenue follows the plan and the handset, which is what makes the column
    # profile in the UI look like a telecom's and not like a normal distribution.
    arpu_base = np.where(plan == "prepaid", 48.0, np.where(plan == "hybrid", 96.0, 138.0))
    arpu_true = np.round(
        np.clip(
            arpu_base
            + 18.0 * (handset_tier == "mid")
            + 52.0 * (handset_tier == "premium")
            + 0.22 * tenure
            + rng.normal(0, 26, count),
            9.0,
            None,
        ),
        2,
    )
    data_gb = np.round(
        np.clip(rng.gamma(2.1, 3.4, count) + 2.2 * (plan != "prepaid"), 0.0, None), 2
    )
    voice_minutes = rng.poisson(np.where(plan == "prepaid", 92, 168), count)
    sms_count = rng.poisson(14, count)
    intl_minutes = np.round(np.clip(rng.gamma(1.2, 6.0, count) - 3.0, 0.0, None), 1)
    roaming_days = rng.binomial(30, 0.035, count)
    support_tickets = rng.poisson(0.72, count)
    dropped_calls = rng.poisson(2.4, count)
    avg_download_mbps = np.round(np.clip(rng.normal(31.0, 12.5, count), 1.2, None), 1)
    late_payments = np.where(plan == "prepaid", 0, rng.poisson(0.42, count))
    device_age_months = rng.integers(1, 61, count)
    fiber_bundle = rng.binomial(1, np.where(plan == "postpaid", 0.31, 0.07), count)
    family_lines = 1 + rng.binomial(4, 0.22, count)
    promo_discount_pct = np.round(
        np.where(rng.random(count) < 0.34, rng.uniform(5, 35, count), 0.0), 1
    )
    nps_true = rng.integers(0, 11, count)

    logit = _churn_logit(
        {
            "tenure_months": tenure,
            "support_tickets": support_tickets,
            "dropped_calls": dropped_calls,
            "late_payments": late_payments,
            "avg_download_mbps": avg_download_mbps,
            "arpu_true": arpu_true,
            "promo_discount_pct": promo_discount_pct,
            "device_age_months": device_age_months,
            "nps_true": nps_true,
            "fiber_bundle": fiber_bundle,
            "family_lines": family_lines,
            "plan": plan,
            "contract": contract,
            "region": region,
        },
        np,
    )
    churn = (rng.random(count) < 1.0 / (1.0 + np.exp(-logit))).astype("int64")

    # Three disjoint defect blocks carved out of one permutation, so the cleaned
    # row count is exactly CLEAN_ROWS on every machine.
    order = rng.permutation(count)
    suspended_idx = order[:SUSPENDED_LINES]
    cursor = SUSPENDED_LINES
    missing_idx = order[cursor : cursor + MISSING_ARPU]
    cursor += MISSING_ARPU
    sentinel_idx = order[cursor : cursor + SENTINEL_ARPU]

    line_status = np.full(count, "active", dtype=object)
    line_status[suspended_idx] = "suspended"

    arpu = arpu_true.astype("float64").copy()
    arpu[sentinel_idx] = ARPU_SENTINEL
    arpu_nullable: list[float | None] = arpu.tolist()
    for index in missing_idx.tolist():
        arpu_nullable[index] = None

    # NPS is missing where nobody answered the survey — a hole the model has to
    # tolerate rather than a defect the cleaning removes, which is the honest
    # version of "real data has gaps".
    #
    # And the hole is not random. A subscriber on the way out is the one who
    # stops answering surveys, so non-response carries signal of its own. That
    # is worth generating faithfully because it is the mechanism the demo's two
    # model families differ on: the boosted trees route a missing value down a
    # branch and read it, while the linear baseline has it imputed away before
    # it ever sees it.
    propensity = (logit - INTERCEPT) / GAIN
    silence = 1.0 / (1.0 + np.exp(-(-1.72 + 0.62 * propensity)))
    nps: list[int | None] = nps_true.astype("int64").tolist()
    for index in np.flatnonzero(rng.random(count) < silence).tolist():
        nps[index] = None

    snapshot = REFERENCE_DATE.isoformat()
    canonical = pl.DataFrame(
        {
            "msisdn": [_msisdn(index) for index in range(count)],
            "snapshot_date": [snapshot] * count,
            "region": _spelled_four_ways(rng, region),
            "plan": [
                text.upper() if flag else text
                for text, flag in zip(plan.tolist(), rng.random(count) < 0.15, strict=True)
            ],
            "contract": contract.tolist(),
            "line_status": line_status.tolist(),
            "tenure_months": tenure.tolist(),
            "arpu_mad": arpu_nullable,
            "data_gb": data_gb.tolist(),
            "voice_minutes": voice_minutes.tolist(),
            "sms_count": sms_count.tolist(),
            "intl_minutes": intl_minutes.tolist(),
            "roaming_days": roaming_days.tolist(),
            "support_tickets": support_tickets.tolist(),
            "dropped_calls": dropped_calls.tolist(),
            "avg_download_mbps": avg_download_mbps.tolist(),
            "late_payments": late_payments.tolist(),
            "device_age_months": device_age_months.tolist(),
            "handset_tier": handset_tier.tolist(),
            "fiber_bundle": fiber_bundle.tolist(),
            "family_lines": family_lines.tolist(),
            "promo_discount_pct": promo_discount_pct.tolist(),
            "nps": nps,
            CHURN_TARGET: churn.tolist(),
        }
    )
    return pl.concat([canonical, _stale_snapshots(canonical, rng, pl)], how="vertical")


def _stale_snapshots(canonical: Any, rng: Any, pl: Any):
    """``DUPLICATE_ROWS`` older re-exports of rows already in the file.

    Older by ``snapshot_date`` and slightly staler in the counters, because a
    duplicate that was byte-identical would let a dedup-free pipeline pass by
    accident — and the point of the cleaning node is that it does not.
    """

    picked = rng.choice(canonical.height, size=DUPLICATE_ROWS, replace=False)
    stale = canonical[sorted(picked.tolist())]
    lag_days = rng.integers(28, 90, stale.height)
    dates = [
        (REFERENCE_DATE - timedelta(days=int(days))).isoformat() for days in lag_days
    ]
    return stale.with_columns(
        pl.Series("snapshot_date", dates),
        (pl.col("tenure_months") - pl.Series("lag", (lag_days // 30).tolist()))
        .clip(1)
        .alias("tenure_months"),
        pl.col("support_tickets").clip(0, 2).alias("support_tickets"),
    )


def clean_churn_sql(source: str = "input") -> str:
    """The statement the demo's first SQL node runs, and the one the seed uses.

    Shared rather than duplicated between the seeded node and the tests: the
    exact-count claim (8 412 → 6 903) is a property of *this* statement over
    *that* generator, and two copies of it would drift apart on the first edit.
    """

    return f"""
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY msisdn ORDER BY snapshot_date DESC
        ) AS snapshot_rank
    FROM {source}
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
    {CHURN_TARGET}
FROM ranked
WHERE snapshot_rank = 1
  AND line_status = 'active'
  AND arpu_mad IS NOT NULL
  AND arpu_mad >= 0
-- Ordered because duckdb is parallel and a window over 8 412 rows comes back in
-- whatever order the threads finished in. The row *set* is deterministic either
-- way, but a train/test split is taken positionally — so without this line the
-- same seed trains on a different sample every run, and the metrics the demo
-- quotes on stage stop being the metrics it rehearsed with.
ORDER BY msisdn
""".strip()


def clean_churn_frame(raw: Any | None = None, *, seed: int = 20260825):
    """The cleaned base, computed with the same duckdb statement the node runs.

    Handy for calibration and for tests that need the training frame without
    standing up a Flow.
    """

    import duckdb

    frame = churn_raw_frame(seed=seed) if raw is None else raw
    connection = duckdb.connect()
    try:
        connection.register("input", frame.to_arrow())
        return connection.execute(clean_churn_sql()).pl()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Radio KPIs
# ---------------------------------------------------------------------------


def _cell_roles(base_load: Any, rng: Any, np: Any) -> tuple[Any, Any, Any]:
    """Which cells are chronically congested, which are moving, and which way.

    The congested ones are the heaviest cells, because that is what chronic
    congestion is. The movers are drawn from the middle of the distribution and
    are disjoint from them, so a cell that degrades starts inside the healthy
    band and ends outside it — the mart then flags it on the *trend*, days before
    a level threshold would have, which is the entire argument for the node.
    """

    heaviest = np.argsort(base_load)[::-1]
    congested = np.sort(heaviest[:CONGESTED_CELLS])

    middle = np.flatnonzero(
        (base_load >= np.quantile(base_load, 0.45))
        & (base_load <= np.quantile(base_load, 0.88))
    )
    candidates = np.setdiff1d(middle, congested)
    movers = rng.permutation(candidates)[: DEGRADING_CELLS + RECOVERING_CELLS]
    return (
        congested,
        np.sort(movers[:DEGRADING_CELLS]),
        np.sort(movers[DEGRADING_CELLS:]),
    )


def _prb_from_offered_load(offered: Any, np: Any) -> Any:
    """Offered traffic in, a utilisation counter out, saturating smoothly.

    Below the knee a cell schedules everything it is handed, so utilisation is
    the offered load and the mapping is the identity. Above it the curve bends
    towards ``PRB_CEILING``: continuous, slope 1 at the knee, and asymptotic, so
    a cell offered five times its capacity reports 94% rather than 100%.

    Asymptotic and not clipped, which matters more than it looks. Clipping puts a
    large share of the busy hours on exactly 100.0, and the week-over-week delta
    of a constant is zero — so the cells degrading fastest become invisible to
    the trend column, precisely the ones the radio node exists to surface, and
    the watchlist's top rows collapse into a wall of ``100.00 / 0.00``. A
    saturating counter keeps the ordering informative all the way up.
    """

    slack = PRB_CEILING - PRB_KNEE
    linear = offered * PRB_PER_LOAD
    # Evaluated everywhere and then min-ed rather than branched on: at the knee
    # the bent curve equals the linear one, so the minimum switches between them
    # exactly there, and the denominator stays positive for every input.
    bent = PRB_CEILING - slack**2 / (np.maximum(linear, PRB_KNEE) - PRB_KNEE + slack)
    return np.minimum(linear, bent)


def network_cell_frame(*, seed: int = 20260825, cells: int = CELLS, days: int = KPI_DAYS):
    """Hourly radio KPIs, with a busy hour, a weekend and cells that move.

    Written long (one row per cell-hour) rather than pre-aggregated, because the
    demo's dbt models are the aggregation — a table that arrived already bucketed
    would make them decoration.

    Three populations are planted in it, disjoint and named in the constants
    above: cells that are chronically saturated, cells that climb into trouble
    inside the recent week, and cells a capacity upgrade relieved. The watchlist
    the dbt node builds is only worth showing because all three are there — one
    band tells you where to go, and the delta column tells you which of those the
    engineer has not already seen.
    """

    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed + 7)
    count = int(cells)

    region = rng.choice(REGIONS, count, p=REGION_WEIGHTS)
    technology = rng.choice(("4G", "5G"), count, p=(0.62, 0.38))
    site_index = rng.integers(100, 999, count)
    cell_id = [
        f"{SITE_PREFIXES[str(reg)]}-{site:03d}-{('N' if tech == '5G' else 'L')}{cell:02d}"
        for cell, (reg, tech, site) in enumerate(
            zip(region.tolist(), technology.tolist(), site_index.tolist(), strict=True),
            start=1,
        )
    ]
    site_code = [f"{SITE_PREFIXES[str(reg)]}-{site:03d}" for reg, site in zip(region.tolist(), site_index.tolist(), strict=True)]

    # Load per cell: a dense-urban tail carries far more traffic than the median,
    # which is what makes a "top congested cells" model worth writing.
    full_cell_sessions = np.where(technology == "5G", 620.0, 210.0)
    base_load = np.clip(rng.lognormal(mean=0.0, sigma=0.34, size=count), 0.42, 2.0)

    congested, degrading, recovering = _cell_roles(base_load, rng, np)
    congestion_bias = np.zeros(count)
    congestion_bias[congested] = rng.uniform(0.62, 1.05, congested.size)
    # Signed, because the two groups are disjoint: a cell either grew into a
    # problem over the fortnight or was relieved of one.
    trend = np.zeros(count)
    trend[degrading] = rng.uniform(1.5, 1.9, degrading.size)
    trend[recovering] = -rng.uniform(0.30, 0.42, recovering.size)

    hours = int(days) * 24
    start = datetime.combine(REFERENCE_DATE, datetime.min.time()) - timedelta(hours=hours)
    timestamps = [start + timedelta(hours=step) for step in range(hours)]
    hour_of_day = np.array([stamp.hour for stamp in timestamps])
    is_weekend = np.array([stamp.weekday() >= 5 for stamp in timestamps])
    # Two humps — a commute and an evening streaming peak — plus a weekend that
    # is flatter and later.
    diurnal = (
        0.42
        + 0.30 * np.exp(-0.5 * ((hour_of_day - 9) / 2.1) ** 2)
        + 0.86 * np.exp(-0.5 * ((hour_of_day - 21) / 2.6) ** 2)
    )
    diurnal = np.where(is_weekend, diurnal * 0.86 + 0.10, diurnal)
    progress = np.arange(hours) / max(hours - 1, 1)
    # A change of regime rather than a slope: most of the movement lands inside
    # the recent week, which is what "this cell was fine a fortnight ago" looks
    # like in the counters — and what makes the mart's 7-day comparison read the
    # full size of the change instead of half of it.
    ramp = 1.0 / (1.0 + np.exp(-(progress - 0.55) / 0.09))

    cell_axis = np.repeat(np.arange(count), hours)
    time_axis = np.tile(np.arange(hours), count)
    total = count * hours

    offered = (
        base_load[cell_axis]
        * diurnal[time_axis]
        * (1.0 + congestion_bias[cell_axis])
        * (1.0 + trend[cell_axis] * ramp[time_axis])
        * rng.normal(1.0, 0.075, total)
    )
    prb = np.round(_prb_from_offered_load(offered, np), 1)
    # Everything below reads the *served* utilisation rather than the traffic
    # offered to the cell, because that is what the counters on a base station
    # measure: a full cell stops admitting sessions and stops drawing more power,
    # however much demand is queued behind it.
    utilisation = prb / PRB_CEILING
    active_users = np.maximum(
        8,
        np.round(full_cell_sessions[cell_axis] * utilisation * rng.normal(1.0, 0.11, total)),
    ).astype("int64")
    # Throughput collapses as the cell saturates; latency and drops climb.
    saturation = np.clip(
        (prb - PRB_QUALITY_ONSET) / (PRB_CEILING - PRB_QUALITY_ONSET), 0.0, 1.0
    )
    peak_mbps = np.where(technology == "5G", 340.0, 96.0)[cell_axis]
    throughput = np.round(
        np.clip(peak_mbps * (1.0 - 0.78 * saturation) * rng.normal(1.0, 0.09, total), 1.0, None),
        1,
    )
    latency = np.round(
        np.clip(
            np.where(technology == "5G", 14.0, 27.0)[cell_axis]
            + 46.0 * saturation**1.7
            + rng.normal(0, 2.4, total),
            5.0,
            None,
        ),
        1,
    )
    drop_rate = np.round(
        np.clip(0.24 + 3.4 * saturation**2 + rng.normal(0, 0.12, total), 0.0, None), 2
    )
    handover = np.round(
        np.clip(99.4 - 6.2 * saturation**1.5 + rng.normal(0, 0.22, total), 80.0, 100.0), 2
    )
    # A radio's draw is a fixed baseline plus a part that follows how much of the
    # spectrum it is actually lighting up. 5G idles higher and swings wider.
    idle_kw = np.where(technology == "5G", 1.35, 0.78)[cell_axis]
    dynamic_kw = np.where(technology == "5G", 2.10, 1.15)[cell_axis]
    energy = np.round(
        np.clip(idle_kw + dynamic_kw * utilisation + rng.normal(0, 0.06, total), 0.2, None),
        2,
    )

    return pl.DataFrame(
        {
            "cell_id": [cell_id[index] for index in cell_axis.tolist()],
            "site_code": [site_code[index] for index in cell_axis.tolist()],
            "region": [str(region[index]) for index in cell_axis.tolist()],
            "technology": [str(technology[index]) for index in cell_axis.tolist()],
            "ts": [timestamps[index] for index in time_axis.tolist()],
            "active_users": active_users.tolist(),
            "prb_utilization_pct": prb.tolist(),
            "throughput_mbps": throughput.tolist(),
            "latency_ms": latency.tolist(),
            "drop_call_rate_pct": drop_rate.tolist(),
            "handover_success_pct": handover.tolist(),
            "energy_kwh": energy.tolist(),
        }
    ).sort(["cell_id", "ts"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

CHURN_FILE = "nawa_churn_raw"
NETWORK_FILE = "nawa_network_cells"


def describe() -> dict[str, Any]:
    """What the generator promises, without generating anything.

    Used by the seed's log line and by the runbook, so the numbers quoted on
    stage come from the same place the data does.
    """

    return {
        "churn_raw_rows": RAW_ROWS,
        "churn_clean_rows": CLEAN_ROWS,
        "churn_duplicates": DUPLICATE_ROWS,
        "churn_suspended": SUSPENDED_LINES,
        "churn_missing_arpu": MISSING_ARPU,
        "churn_sentinel_arpu": SENTINEL_ARPU,
        "churn_target": CHURN_TARGET,
        "network_rows": NETWORK_ROWS,
        "network_cells": CELLS,
        "network_days": KPI_DAYS,
        "network_congested_cells": CONGESTED_CELLS,
        "network_degrading_cells": DEGRADING_CELLS,
        "network_recovering_cells": RECOVERING_CELLS,
        "reference_date": REFERENCE_DATE.isoformat(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Directory the CSV/Parquet files are written to.",
    )
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument(
        "--parquet",
        action="store_true",
        help="Write Parquet instead of CSV (CSV is what the demo uploads).",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print the promised shapes and exit without generating.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.describe:
        for key, value in describe().items():
            print(f"{key}={value}")
        return 0
    if not args.out_dir:
        raise SystemExit("--out-dir is required unless --describe is passed")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "parquet" if args.parquet else "csv"

    churn = churn_raw_frame(seed=args.seed)
    network = network_cell_frame(seed=args.seed)
    for name, frame in ((CHURN_FILE, churn), (NETWORK_FILE, network)):
        path = out / f"{name}.{suffix}"
        if args.parquet:
            frame.write_parquet(path)
        else:
            frame.write_csv(path)
        print(f"{path} rows={frame.height} columns={frame.width}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
