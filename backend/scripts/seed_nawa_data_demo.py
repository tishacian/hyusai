"""Seed the Nawa « Churn Radar » demo: datasets, models, Flows, published skill.

What this leaves behind, on the ``nawa`` workspace, is a data/ML plane with no
empty page in it:

* **Data** — the raw subscriber export (8 412 rows, dirt included), the cleaned
  base (6 903), the engineered feature table, the scored table, and the radio
  KPI table. Every derived one carries the lineage of the one before it.
* **Models** — three real versions of the ``Churn Radar`` lineage with genuinely
  different scores: a linear baseline (ROC AUC 0.835), the same 20 columns under
  gradient boosting (0.860), then the Flow's own fit on the engineered features
  (0.856). **v1 serves**, on purpose — promoting the boosted version on stage is
  then a real move with a +0.024 delta to read out, and the third version is
  there to make the honest point that a retrain does not always win.
* **Flow Builder** — ``Churn Radar`` (clean → features → fit → score → brief)
  and ``Radio Watch`` (dbt over the cell KPIs), both published, both with a run
  behind them so the canvas badges are already on the nodes.
* **Skills** — the champion published as a workspace Skill, with its provenance
  chip, and one API key minted so the cURL of the last demo beat runs first try.
* **A business page** — ``Retention Board`` at ``/work/retention-board``, live,
  where a stakeholder who will never open a canvas reads who is flagged, what
  one month of their revenue is worth, and how the model's riskiest decile
  compares with the base. One button, one run, every tile off the same payload.

Idempotent, and specifically idempotent in the way a rehearsal needs. Re-running
reconciles the Systems, reuses a dataset version whose name and row count already
match, reuses a fitted model of the same estimator over the same columns, and
leaves the serving version alone — so promoting a challenger on stage survives
the next seed. ``--refresh`` opts back into adding versions. Nothing is ever
deleted.

Two settings have to be on, or the Polars and dbt nodes will fail their half of
the pipeline (the run still completes; those two nodes report the refusal):

    RECIPE_EXECUTION_ENABLED=true   # author-written Python may run at all
    WORKER_EAGER_MODE=true          # ...inline, when no Celery worker is up

Usage:
    cd backend
    RECIPE_EXECUTION_ENABLED=true WORKER_EAGER_MODE=true \\
        python -m scripts.seed_nawa_data_demo                   # full seed
    python -m scripts.seed_nawa_data_demo --skip-runs           # no Flow runs
    python -m scripts.seed_nawa_data_demo --skip-radio          # no dbt run
    python -m scripts.seed_nawa_data_demo --refresh             # add versions
    python -m scripts.seed_nawa_data_demo --reset               # replace, in place
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

import app.models  # noqa: F401 — register every mapper before create_all
from app.db.base import Base, SessionLocal, engine
from app.models.capability import Capability
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services.skills_registry import seed_skills_and_capabilities
from app.services.systems import flow_publication

from scripts.gen_nawa_telecom_data import (
    CHURN_FEATURE_COLUMNS,
    CHURN_TARGET,
    CLEAN_ROWS,
    NETWORK_ROWS,
    RAW_ROWS,
    churn_raw_frame,
    clean_churn_sql,
    describe,
    network_cell_frame,
)

# ---------------------------------------------------------------------------
# Names. Every one of them is spoken during the demo, so they live together.
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_SLUG = "nawa"
DEFAULT_WORKSPACE_NAME = "Nawa"
SEED_ACTOR = "nawa-data-seed"

RAW_DATASET_NAME = "Subscriber base — raw export"
CLEAN_DATASET_NAME = "Subscriber base — cleaned"
FEATURE_DATASET_NAME = "Subscriber base — features"
SCORED_DATASET_NAME = "Subscriber base — scored"
NETWORK_DATASET_NAME = "Radio cell KPIs"
RADIO_DATASET_NAME = "Cells at risk — 7 days"

MODEL_NAME = "Churn Radar"

CHURN_SYSTEM_NAME = "Churn Radar"
RADIO_SYSTEM_NAME = "Radio Watch"
DESK_SYSTEM_NAME = "Churn Desk"
BOARD_SYSTEM_NAME = "Retention Board"
CHURN_CAPABILITY_SLUG = "nawa_churn_radar"
RADIO_CAPABILITY_SLUG = "nawa_radio_watch"
DESK_CAPABILITY_SLUG = "nawa_churn_desk"
BOARD_CAPABILITY_SLUG = "nawa_retention_board"
API_KEY_NAME = "Nawa demo"

#: The stable name the page invokes the board through. A page names a key, not
#: a System and not a Flow version, so republishing the graph behind it is not
#: an edit to the document.
BOARD_BINDING_KEY = "churn.board.load"
BOARD_EXPERIENCE_SLUG = "retention-board"
BOARD_EXPERIENCE_NAME = "Retention Board"
#: The one component every tile reads from. Named here because the document
#: repeats it in every ``dataBinding`` and a typo would be a blank tile rather
#: than an error.
BOARD_ACTION_ID = "load-board"

CHURN_SKILL_SLUGS = [
    "sql_transform_v1",
    "polars_transform_v1",
    "ml_train_sklearn_v1",
    "ml_batch_score_v1",
    "ml_predict_v1",
    "azure_llm_v1",
]
RADIO_SKILL_SLUGS = ["dbt_transform_v1"]
#: The board reads and computes; it neither trains, scores nor writes a table.
#: Two skills is the whole of it, and that is the claim its capability makes.
BOARD_SKILL_SLUGS = ["system_run_read_v1", "python_recipe_v1"]
#: The desk's own two: the planner, and the writer that phrases the verdict. The
#: third skill it may call is the published model, which has no slug until the
#: model card publishes it — so it is bound to the System by id, not claimed here.
DESK_SKILL_SLUGS = ["decide_next_v1", "azure_llm_v1"]

# ---------------------------------------------------------------------------
# The Polars feature node's script
# ---------------------------------------------------------------------------

#: Ratios and bands a churn analyst would actually add: intensity per dirham and
#: per month of tenure, which is the shape the drivers really have even though
#: the export ships them as levels.
FEATURE_CODE = '''import polars as pl


def transform(inputs: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Derive the churn features the raw counters only imply.

    Ratios rather than more counters: what predicts a departure is revenue per
    month of tenure and friction per dirham billed, not the absolute number of
    tickets a heavy user opens.
    """
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
        # Whether the survey was answered at all. Not a hole to be filled: the
        # subscribers who stop answering are the ones on the way out.
        pl.col("nps").is_not_null().cast(pl.Int8).alias("nps_answered"),
    )
'''

#: The columns the script above adds. The training node lists its features
#: explicitly, so this has to be stated rather than discovered.
ENGINEERED_COLUMNS = (
    "arpu_per_month",
    "gb_per_mad",
    "friction_score",
    "friction_per_mad",
    "usage_index",
    "mobility_index",
    "tenure_band",
    "on_promo",
    "nps_answered",
)

# ---------------------------------------------------------------------------
# The dbt project of the Radio Watch node
# ---------------------------------------------------------------------------

RADIO_MODELS = [
    {
        "name": "stg_cell_hourly",
        "sql": (
            "-- Staging: one row per cell-hour, with the calendar keys the mart\n"
            "-- groups on. Casting here keeps the mart readable.\n"
            "select\n"
            "    cell_id,\n"
            "    site_code,\n"
            "    region,\n"
            "    technology,\n"
            "    cast(ts as timestamp)                        as kpi_hour,\n"
            "    cast(ts as date)                             as kpi_date,\n"
            "    extract('hour' from cast(ts as timestamp))   as hour_of_day,\n"
            "    active_users,\n"
            "    prb_utilization_pct,\n"
            "    throughput_mbps,\n"
            "    latency_ms,\n"
            "    drop_call_rate_pct,\n"
            "    handover_success_pct,\n"
            "    energy_kwh\n"
            "from {{ source('inputs', 'input') }}\n"
        ),
    },
    {
        "name": "mart_cell_risk",
        "sql": (
            "-- Mart: the congestion watchlist. Busy hour only (19h–23h), because\n"
            "-- a cell that saturates at 3am is not a customer problem, and the\n"
            "-- last seven days against the seven before them, because a level\n"
            "-- without a trend does not tell an engineer where to go.\n"
            "with busy as (\n"
            "    select *\n"
            "    from {{ ref('stg_cell_hourly') }}\n"
            "    where hour_of_day between 19 and 23\n"
            "),\n"
            "bounds as (\n"
            "    select max(kpi_date) as last_day from busy\n"
            "),\n"
            "windowed as (\n"
            "    select\n"
            "        busy.*,\n"
            "        case\n"
            "            when busy.kpi_date > bounds.last_day - interval 7 day then 'recent'\n"
            "            else 'previous'\n"
            "        end as window_label\n"
            "    from busy cross join bounds\n"
            "),\n"
            "per_window as (\n"
            "    select\n"
            "        cell_id,\n"
            "        site_code,\n"
            "        region,\n"
            "        technology,\n"
            "        window_label,\n"
            "        round(avg(prb_utilization_pct), 2) as prb_pct,\n"
            "        round(avg(drop_call_rate_pct), 3)  as drop_pct,\n"
            "        round(avg(throughput_mbps), 1)     as throughput_mbps,\n"
            "        round(avg(latency_ms), 1)          as latency_ms,\n"
            "        round(sum(energy_kwh), 1)          as energy_kwh,\n"
            "        max(active_users)                  as peak_users\n"
            "    from windowed\n"
            "    group by 1, 2, 3, 4, 5\n"
            ")\n"
            "select\n"
            "    recent.cell_id,\n"
            "    recent.site_code,\n"
            "    recent.region,\n"
            "    recent.technology,\n"
            "    recent.prb_pct,\n"
            "    recent.drop_pct,\n"
            "    recent.throughput_mbps,\n"
            "    recent.latency_ms,\n"
            "    recent.energy_kwh,\n"
            "    recent.peak_users,\n"
            "    round(recent.prb_pct - previous.prb_pct, 2)   as prb_pct_delta,\n"
            "    round(recent.drop_pct - previous.drop_pct, 3) as drop_pct_delta,\n"
            "    case\n"
            "        when recent.prb_pct >= 85 then 'critical'\n"
            "        when recent.prb_pct >= 70 then 'watch'\n"
            "        else 'healthy'\n"
            "    end as risk_band\n"
            "from per_window recent\n"
            "left join per_window previous\n"
            "    on previous.cell_id = recent.cell_id\n"
            "   and previous.window_label = 'previous'\n"
            "where recent.window_label = 'recent'\n"
            "order by recent.prb_pct desc\n"
        ),
    },
]

#: Two data tests, and they are the point of the node: a cell that appears twice
#: in a watchlist, or a utilisation of 140%, means the pipeline is wrong — and
#: the node refuses to publish rather than handing that downstream.
RADIO_TESTS_YML = """version: 2

models:
  - name: mart_cell_risk
    description: >
      Busy-hour congestion watchlist per cell, with the 7-day delta and a risk
      band. One row per cell.
    columns:
      - name: cell_id
        description: Radio cell. One row per cell, always known.
        tests:
          - not_null
          - unique
      - name: risk_band
        description: Congestion band derived from busy-hour PRB utilisation.
        tests:
          - accepted_values:
              values: ['critical', 'watch', 'healthy']
"""

#: The synthesis prompt of the last node before the sink. Written as a literal
#: on the node so the demo can edit it live in the inspector. English, like
#: every other string the audience reads: the agentic half of the canvas has to
#: speak the same language as the data half.
BRIEF_PROMPT = (
    "You are a retention analyst at a Moroccan telecom operator. "
    "From the churn scoring table that has just been produced "
    "(columns: msisdn, region, plan, contract, tenure_months, arpu_mad, "
    "prediction, confidence, score_1), write an English brief of at most "
    "8 lines for the retention committee: the three segments most at risk, the "
    "estimated monthly revenue at stake, and one retention action per segment. "
    "Quote figures, not generalities."
)


# ---------------------------------------------------------------------------
# The Retention Board's recipe node
# ---------------------------------------------------------------------------

#: The columns the board's arithmetic actually reads. Named rather than taken
#: whole because every one of them crosses into the recipe sandbox as JSON on
#: each refresh: seven columns over the base is a payload, thirty is a
#: transfer. ``score_1`` is what ``ml_batch_score_v1`` calls the probability of
#: the positive class, and a rename of it fails the read loudly instead of
#: producing a board of zeros.
BOARD_COLUMNS = (
    "msisdn",
    "region",
    "plan",
    "tenure_months",
    "arpu_mad",
    "churn",
    "prediction",
    "score_1",
)

#: The view the recipe reads its rows under.
BOARD_SOURCE_VIEW = "scored"


def scored_slug() -> str:
    """The lineage the board reads, named the way a pin names one.

    By slug rather than by dataset id, and derived from the name rather than
    looked up, for the same reason the pipeline's own nodes pin slugs: a pin
    follows the newest ready version of that lineage. Every re-score mints a
    version, and a board pinned to an id would keep reporting the base as it
    stood the day it was seeded.
    """

    from app.services.tabular_datasets import slugify

    return slugify(SCORED_DATASET_NAME)

#: The board's arithmetic, authored rather than hidden in a platform skill:
#: every figure a stakeholder will challenge is a line somebody can open in the
#: node inspector and read. Kept to the standard library — the numbers here are
#: sums and sorts over one table, and a dependency would buy a slower first
#: refresh for nothing.
BOARD_CODE = '''"""Shape what the pipeline already produced into one retention board.

Every figure is computed here, at read time, from the scored base and the model
that scored it. Nothing is carried in from a document: a board that quotes a
number somebody typed last month is worse than a board with no number on it.

The two rate figures travel together on purpose. A decile churn rate on its own
sounds like a model result; next to the base rate it *is* one, because the gap
between them is the only part that the model can claim.
"""

#: Beyond this the table stops being a call list and becomes a data export.
TOP_AT_RISK = 20

#: Probability ranges rather than adjectives. "Critical" is a judgement the
#: operator has not made yet, and "50-75%" reads the same in every language —
#: which matters, because these labels are data and travel unlocalised.
BANDS = (
    (0.00, 0.25, "0-25%"),
    (0.25, 0.50, "25-50%"),
    (0.50, 0.75, "50-75%"),
    (0.75, 1.01, "75-100%"),
)

#: Stated in words on the page, because a monetary claim without its definition
#: is the one figure in a committee that always gets challenged. Measured ARPU,
#: modelled weighting, one month: the sentence says which half is which.
REVENUE_LABEL = (
    "One month of recurring revenue from the flagged subscribers, each "
    "subscriber's measured ARPU multiplied by the model's predicted "
    "probability that they leave. The revenue is measured; the weighting is "
    "modelled."
)

NO_BRIEF = (
    "The retention brief is written by the last node of the Churn Radar "
    "pipeline. That pipeline has not produced one yet, so there is nothing to "
    "quote here. The figures above are this board's own arithmetic and stand "
    "without it."
)


def _number(value):
    """A float, treating an absent cell as zero rather than as a failure.

    A hole in ARPU cannot reach here — the cleaning node drops those rows — so
    the only way to arrive is a column the board does not model. Zero keeps one
    odd row out of the totals instead of emptying the page.
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _msisdn(value):
    """The subscriber's number as text, because it is a name and not a quantity.

    It arrives from the base as an integer, and left that way a table renderer
    is entitled to group its digits — a subscriber called 21,260,006,270 is one
    nobody can dial. Text also makes the tie-break in the call list total
    instead of dependent on what the column happened to be parsed as.
    """

    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _score_column(row):
    """The probability column the scoring node added, found by its convention.

    ``ml_batch_score_v1`` writes ``score_<positive class>``, so the column name
    carries which class the number is about. Reading it is what keeps the
    positive class out of this script as a literal. Two columns, or none, means
    this is not the table the board was written against, and saying so is
    better than reporting a confident zero.
    """

    names = sorted(name for name in row if name.startswith("score_"))
    if len(names) != 1:
        raise ValueError(
            "the scored base must carry exactly one score_<class> column, "
            "found: " + (", ".join(names) or "none")
        )
    return names[0]


def _rate_pct(numerator, denominator):
    """A percentage with one decimal, or None when there is nothing to divide."""

    if not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


def main(inputs):
    scored = inputs.get("scored") or {}
    rows = scored.get("rows") or []
    if not rows:
        raise ValueError("the scored base is empty; there is no board to draw")
    model = scored.get("model") or {}

    score_column = _score_column(rows[0])
    # The class the score is about, read off the column the model itself named.
    positive = score_column[len("score_") :]

    base_size = len(rows)
    churned = sum(1 for row in rows if _number(row.get("churn")) >= 0.5)

    # The riskiest tenth, by the model's own ranking, judged on what those
    # subscribers actually did. Measured, not predicted: this is the number
    # that says the ranking is worth acting on.
    by_score = sorted(rows, key=lambda row: _number(row.get(score_column)), reverse=True)
    decile_size = max(1, base_size // 10)
    decile = by_score[:decile_size]
    decile_churned = sum(1 for row in decile if _number(row.get("churn")) >= 0.5)

    # Flagged is the model's own verdict, not a threshold this script invented.
    flagged = [row for row in rows if str(row.get("prediction")) == positive]

    at_risk = []
    for row in flagged:
        score = _number(row.get(score_column))
        arpu = _number(row.get("arpu_mad"))
        at_risk.append(
            {
                "msisdn": _msisdn(row.get("msisdn")),
                "region": row.get("region"),
                "plan": row.get("plan"),
                "tenure_months": row.get("tenure_months"),
                "arpu_mad": round(arpu, 2),
                "score": round(score, 4),
                "revenue_at_stake_mad": round(arpu * score, 2),
            }
        )
    revenue_at_stake = sum(entry["revenue_at_stake_mad"] for entry in at_risk)
    # By what is at stake rather than by probability: a near-certain departure
    # on a 40 MAD line is not the call to make first. The msisdn breaks ties so
    # two refreshes of the same table list the same subscribers in the same
    # order.
    at_risk.sort(key=lambda entry: (-entry["revenue_at_stake_mad"], entry["msisdn"] or ""))

    bands = []
    for lower, upper, label in BANDS:
        count = sum(
            1 for row in rows if lower <= _number(row.get(score_column)) < upper
        )
        bands.append({"label": label, "value": count})

    system_run = inputs.get("system_run") or {}
    produced = system_run.get("output") or {}
    brief = ""
    if isinstance(produced, dict):
        brief = str(produced.get("completion") or "").strip()

    return {
        "summary": {
            "subscribers_at_risk": len(flagged),
            "base_size": base_size,
            "revenue_at_stake_mad": round(revenue_at_stake, 2),
            "revenue_at_stake_label": REVENUE_LABEL,
            "riskiest_decile_churn_pct": _rate_pct(decile_churned, decile_size),
            "base_churn_pct": _rate_pct(churned, base_size),
            "model_name": model.get("name"),
            "model_version": model.get("version"),
            "model_metric_key": model.get("metric_key"),
            "model_metric_value": model.get("metric_value"),
        },
        "at_risk": at_risk[:TOP_AT_RISK],
        "bands": bands,
        "brief": brief or NO_BRIEF,
    }
'''


def board_main():
    """The recipe's ``main`` as a callable, compiled from the seeded source.

    The script above is the artifact that runs: it is what the recipe plane
    executes and what an operator edits in the node inspector. Tests that
    re-implemented its arithmetic would be testing a copy, so they compile this
    one instead and call it with a frame they built by hand.
    """

    namespace: dict[str, Any] = {}
    exec(compile(BOARD_CODE, "<board_recipe>", "exec"), namespace)  # noqa: S102
    return namespace["main"]


#: What the run's ``output_ref`` promises, and therefore what a block may bind
#: to: the Experience validates every authored selector against this schema at
#: release time, so a tile bound to a path the board does not produce is caught
#: before anyone deploys it rather than rendering blank on stage.
BOARD_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "subscribers_at_risk": {"type": "integer"},
                "base_size": {"type": "integer"},
                "revenue_at_stake_mad": {"type": "number"},
                "revenue_at_stake_label": {"type": "string"},
                "riskiest_decile_churn_pct": {"type": ["number", "null"]},
                "base_churn_pct": {"type": ["number", "null"]},
                "model_name": {"type": ["string", "null"]},
                "model_version": {"type": ["integer", "string", "null"]},
                "model_metric_key": {"type": ["string", "null"]},
                "model_metric_value": {"type": ["number", "null"]},
            },
            "required": [
                "subscribers_at_risk",
                "base_size",
                "revenue_at_stake_mad",
                "revenue_at_stake_label",
                "riskiest_decile_churn_pct",
                "base_churn_pct",
            ],
            "additionalProperties": False,
        },
        "at_risk": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "msisdn": {"type": ["string", "null"]},
                    "region": {"type": ["string", "null"]},
                    "plan": {"type": ["string", "null"]},
                    "tenure_months": {"type": ["integer", "number", "null"]},
                    "arpu_mad": {"type": "number"},
                    "score": {"type": "number"},
                    "revenue_at_stake_mad": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
        "bands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "integer"},
                },
                "required": ["label", "value"],
                "additionalProperties": False,
            },
        },
        "brief": {"type": "string"},
    },
    "required": ["summary", "at_risk", "bands", "brief"],
    "additionalProperties": False,
}

#: The board takes no arguments: a stakeholder presses one button and reads the
#: base as it stands. Closed rather than merely empty, so the published ingress
#: refuses a payload instead of quietly ignoring it.
BOARD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Workspace, capabilities, catalog
# ---------------------------------------------------------------------------


def ensure_workspace(db: DBSession, slug: str, name: str) -> Workspace:
    """Find the workspace, or create it. Never resets an existing one.

    Migration 065 documents the posture this follows: the Nawa workspace is the
    operator's to create, and its absence is a normal state. A seed that refused
    to create it would make a fresh database undemoable, so this one creates it
    and says so — but it only ever merges settings on a workspace that exists.
    """

    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if workspace is None:
        workspace = Workspace(
            id=str(uuid4()),
            name=name,
            slug=slug,
            mode="portfolio",
            settings={},
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        print(f"workspace created: slug={slug} id={workspace.id}")
    else:
        print(f"workspace found: slug={slug} id={workspace.id}")

    settings = dict(workspace.settings or {})
    features = dict(settings.get("features") or {})
    catalog = dict(settings.get("catalog") or {})
    # The demo is delivered in English, and every string it seeds is English —
    # so the chrome around them has to open that way too, on whatever browser
    # the room happens to have. Declared rather than switched by hand: a reader
    # who picks a language still keeps it.
    presentation = dict(settings.get("presentation") or {})
    presentation["locale"] = "en"
    settings["presentation"] = presentation
    enabled = list(catalog.get("enabled_skills") or [])
    for slug_ in (*CHURN_SKILL_SLUGS, *RADIO_SKILL_SLUGS, *BOARD_SKILL_SLUGS):
        if slug_ not in enabled:
            enabled.append(slug_)
    catalog["enabled_skills"] = enabled
    settings["catalog"] = catalog
    # ``experience_v1`` is an explicit opt-in rather than a graduated default,
    # and it gates the whole ``/work`` surface — without it the board would be
    # released, deployed and answering 404. The demo's business page is the
    # reason this workspace wants it, so the seed that creates the page is the
    # place that asks for it.
    features["experience_v1"] = True
    settings["features"] = features
    settings["nawa_data_demo"] = {
        "seeded_at": datetime.utcnow().isoformat(),
        "generator": describe(),
    }
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.commit()
    db.refresh(workspace)
    return workspace


def ensure_capability(
    db: DBSession,
    workspace: Workspace,
    *,
    slug: str,
    name: str,
    description: str,
    skill_slugs: list[str],
    input_unit: str,
    output_unit: str,
    value_per_outcome: float,
) -> Capability:
    """Upsert the capability that claims the demo's skills.

    Without a claiming capability the catalog policy files a skill under
    ``unclaimed``, which greys its palette row — so this is not decoration, it is
    what makes the nodes droppable on the canvas.
    """

    rows = db.query(Skill).filter(Skill.slug.in_(skill_slugs)).all()
    by_slug = {row.slug: row.id for row in rows}
    missing = [item for item in skill_slugs if item not in by_slug]
    if missing:
        raise SystemExit(
            f"Skills not seeded: {missing}. Run the skills registry seed first."
        )

    payload = {
        "workspace_id": workspace.id,
        "name": name,
        "description": description,
        "tier": "client",
        "industry": "telecom",
        "input_unit": input_unit,
        "output_unit": output_unit,
        "skill_ids": [by_slug[item] for item in skill_slugs],
        "pricing": {"unit": "per_run", "unit_price": 0.08, "currency": "EUR"},
        "value_per_outcome": value_per_outcome,
        "confidence_threshold": 0.7,
        "sla": {"target_latency_ms": 120_000, "availability": "99.0%"},
        "roi_model": {"seed": SEED_ACTOR, "value_driver": "retention"},
        "is_seeded": "Y",
    }
    capability = (
        db.query(Capability)
        .filter(Capability.workspace_id == workspace.id, Capability.slug == slug)
        .first()
    )
    if capability:
        for key, value in payload.items():
            setattr(capability, key, value)
    else:
        capability = Capability(id=str(uuid4()), slug=slug, **payload)
        db.add(capability)
    db.commit()
    db.refresh(capability)
    return capability


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def _reusable_dataset(
    db: DBSession, workspace: Workspace, *, name: str, rows: int | None = None
) -> TabularDataset | None:
    """The newest ready dataset already carrying this name and row count.

    What makes re-running the seed safe. Every ingest and every transform mints
    a *new version* of its lineage by design, so a seed that always ingested
    would leave a second rehearsal looking at ``v4`` of five identical tables —
    and, worse, would retrain the lineage and re-promote a fresh baseline over
    whatever was promoted on stage. Matching on the row count as well as the
    name means a changed generator still produces a new version rather than
    silently reusing the old shape.

    The *earliest* match, which is the part that took a run to learn: the Churn
    Radar Flow cleans the base as well, so after one run two ready "Subscriber
    base — cleaned" versions exist with identical row counts. Reaching for the newest
    moved this anchor onto the Flow's output, whose id no longer matched the
    dataset the seeded models were fitted against — so those models looked absent
    and were retrained, which is exactly the duplication this function exists to
    prevent. The first version is the one the seed itself created; it stays put.
    """

    query = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.name == name,
            TabularDataset.status == "ready",
        )
        .order_by(TabularDataset.version.asc())
    )
    for candidate in query.all():
        if rows is None or int(candidate.row_count or 0) == int(rows):
            return candidate
    return None


def _upload_frame(
    db: DBSession,
    workspace: Workspace,
    *,
    name: str,
    filename: str,
    frame: Any,
    description: str,
) -> TabularDataset:
    """Ingest a frame through the real upload path, CSV bytes included.

    Not ``register_frame``: the demo's first beat is an upload, and a dataset
    that never was one would have no ``upload_key``, no original filename and no
    ingest duration — three things the dataset detail page shows. Paying the CSV
    round-trip here means the seeded rows and the demonstrated ones came through
    the same parser.
    """

    from app.services.tabular_datasets import create_upload, ingest_dataset

    dataset = create_upload(
        db,
        workspace_id=workspace.id,
        name=name,
        filename=filename,
        content_type="text/csv",
        payload=frame.write_csv().encode("utf-8"),
        description=description,
        created_by=SEED_ACTOR,
    )
    db.commit()
    dataset_id = dataset.id
    result = ingest_dataset(dataset_id)
    if result.get("status") != "ready":
        raise SystemExit(f"ingest failed for {name}: {result}")
    db.expire_all()
    fresh = db.query(TabularDataset).filter(TabularDataset.id == dataset_id).one()
    print(
        f"dataset ready: {fresh.name} v{fresh.version} "
        f"rows={fresh.row_count} columns={fresh.column_count} slug={fresh.slug}"
    )
    return fresh


def ensure_datasets(
    db: DBSession, workspace: Workspace, *, seed: int, refresh: bool = False
) -> dict[str, TabularDataset]:
    """The raw export and the radio KPIs, uploaded; then the cleaned base.

    The cleaning runs through ``run_sql_transform`` — the very service the SQL
    node calls, on the very statement the node carries — so the 8 412 → 6 903
    the demo quotes is produced by production code, not asserted by the seed.
    """

    from app.services.tabular_transforms import run_sql_transform

    raw = None if refresh else _reusable_dataset(
        db, workspace, name=RAW_DATASET_NAME, rows=RAW_ROWS
    )
    if raw is None:
        raw = _upload_frame(
            db,
            workspace,
            name=RAW_DATASET_NAME,
            filename="nawa_churn_raw.csv",
            frame=churn_raw_frame(seed=seed),
            description=(
                "Monthly export of the subscriber master: duplicate snapshots, "
                "suspended lines, regions spelled four different ways, ARPU "
                "missing or set to -1. Exactly as it arrives."
            ),
        )
    else:
        print(f"dataset kept: {raw.name} v{raw.version} rows={raw.row_count}")
    if int(raw.row_count or 0) != RAW_ROWS:
        raise SystemExit(f"raw export ingested {raw.row_count} rows, expected {RAW_ROWS}")

    network = None if refresh else _reusable_dataset(
        db, workspace, name=NETWORK_DATASET_NAME, rows=NETWORK_ROWS
    )
    if network is None:
        network = _upload_frame(
            db,
            workspace,
            name=NETWORK_DATASET_NAME,
            filename="nawa_network_cells.csv",
            frame=network_cell_frame(seed=seed),
            description=(
                "Hourly radio KPIs per cell over 14 days: PRB utilisation, "
                "throughput, latency, drop-call rate, energy."
            ),
        )
    else:
        print(f"dataset kept: {network.name} v{network.version} rows={network.row_count}")

    cleaned = None if refresh else _reusable_dataset(
        db, workspace, name=CLEAN_DATASET_NAME, rows=CLEAN_ROWS
    )
    if cleaned is None:
        cleaned_ref = run_sql_transform(
            db,
            workspace_id=workspace.id,
            sql=clean_churn_sql("clients"),
            output_name=CLEAN_DATASET_NAME,
            declared=[{"dataset_id": raw.id, "view": "clients"}],
            node_id="task.clean",
        )
        cleaned = (
            db.query(TabularDataset)
            .filter(TabularDataset.id == cleaned_ref["dataset_id"])
            .one()
        )
        print(
            f"dataset ready: {cleaned.name} v{cleaned.version} "
            f"rows={cleaned.row_count} (from {raw.row_count}) slug={cleaned.slug}"
        )
    else:
        print(f"dataset kept: {cleaned.name} v{cleaned.version} rows={cleaned.row_count}")
    if int(cleaned.row_count or 0) != CLEAN_ROWS:
        raise SystemExit(
            f"cleaning produced {cleaned.row_count} rows, expected {CLEAN_ROWS}"
        )
    return {"raw": raw, "network": network, "cleaned": cleaned}


# ---------------------------------------------------------------------------
# Flow graphs
# ---------------------------------------------------------------------------


def churn_flow(*, raw_slug: str, model_slug: str, features: list[str]) -> dict[str, Any]:
    """source → clean (SQL) → features (Polars) → fit → score → brief → sink.

    ``schema_version: 3`` without ``io_mode: strict``, which is the shape the
    Flow Builder writes: the walker then hands each node the merged output of its
    predecessors, so a dataset envelope travels the wire by reference while the
    statement, the script and the training spec stay graph-owned configuration.

    The scoring node has two parents on purpose. The fit before it is what orders
    them; the feature table beside it is what it actually scores — a model
    reference carries no rows.
    """

    return {
        "schema_version": 3,
        "variant": "nawa_churn_radar_v1",
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Trigger",
                "position": {"x": 40, "y": 220},
                "data": {
                    "description": (
                        "Manual or scheduled. No input required: the pipeline "
                        "starts from the dataset pinned on the next node."
                    )
                },
            },
            {
                "id": "task.clean",
                "kind": "task",
                "type": "task",
                "label": "SQL cleanup",
                "position": {"x": 260, "y": 220},
                "config": {
                    "skill_slug": "sql_transform_v1",
                    "params": {
                        "sql": clean_churn_sql("clients"),
                        "output_name": CLEAN_DATASET_NAME,
                        "sources": [{"dataset_slug": raw_slug, "view": "clients"}],
                    },
                },
                "data": {
                    "description": (
                        "duckdb over the Parquet: deduplicated by msisdn (latest "
                        "snapshot), active lines only, ARPU present and positive, "
                        "regions normalised."
                    )
                },
            },
            {
                "id": "task.features",
                "kind": "task",
                "type": "task",
                "label": "Polars features",
                "position": {"x": 500, "y": 220},
                "config": {
                    "skill_slug": "polars_transform_v1",
                    "params": {
                        "code": FEATURE_CODE,
                        "output_name": FEATURE_DATASET_NAME,
                    },
                },
                "data": {
                    "description": (
                        "Ratios and tenure bands computed by a Polars script "
                        "running in an isolated environment."
                    )
                },
            },
            {
                "id": "task.train",
                "kind": "task",
                "type": "task",
                "label": "Churn training",
                "position": {"x": 740, "y": 220},
                "config": {
                    "skill_slug": "ml_train_sklearn_v1",
                    "params": {
                        "task": "classification",
                        "target": CHURN_TARGET,
                        "features": features,
                        "algo": "gradient_boosting",
                        "knobs": {"max_iter": 220, "learning_rate": 0.08},
                        "test_size": 0.25,
                        "cross_validation": 0,
                        "model_name": MODEL_NAME,
                    },
                },
                "data": {
                    "description": (
                        "Preprocessing decided by skrub, scikit-learn gradient "
                        "boosting, artifact in MLflow format. A new version of "
                        "the lineage on every execution; the serving champion is "
                        "never replaced automatically."
                    )
                },
            },
            {
                "id": "task.score",
                "kind": "task",
                "type": "task",
                "label": "Score the base",
                "position": {"x": 980, "y": 220},
                "config": {
                    "skill_slug": "ml_batch_score_v1",
                    "params": {
                        "model_slug": model_slug,
                        "output_name": SCORED_DATASET_NAME,
                        "explain": True,
                    },
                },
                "data": {
                    "description": (
                        "The lineage's champion answers — not the version just "
                        "trained. The dataset produced keeps every input column "
                        "and adds prediction, confidence and score."
                    )
                },
            },
            {
                "id": "task.brief",
                "kind": "task",
                "type": "llm",
                "label": "Retention brief",
                "position": {"x": 1220, "y": 220},
                "config": {
                    "skill_slug": "azure_llm_v1",
                    "params": {"prompt": BRIEF_PROMPT},
                    # Overlay mode does not merge `config.params` implicitly, so the
                    # prompt is read back through the node's own namespace. That is
                    # also what makes an inspector edit reach the run.
                    "inputs_map": {
                        "prompt": {
                            "node_id": "node",
                            "path": ["config", "params", "prompt"],
                        }
                    },
                },
                "data": {
                    "description": (
                        "The agentic plane consumes the data plane: a written "
                        "brief on the segments at risk, in the same canvas."
                    )
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Result",
                "position": {"x": 1460, "y": 220},
            },
        ],
        "edges": [
            {"from": "src", "to": "task.clean", "kind": "data"},
            {"from": "task.clean", "to": "task.features", "kind": "data"},
            {"from": "task.features", "to": "task.train", "kind": "data"},
            {"from": "task.train", "to": "task.score", "kind": "data"},
            {"from": "task.features", "to": "task.score", "kind": "data"},
            {"from": "task.score", "to": "task.brief", "kind": "data"},
            {"from": "task.brief", "to": "sink", "kind": "data"},
        ],
    }


def radio_flow(*, network_slug: str) -> dict[str, Any]:
    """source → dbt build (2 models, 2 data tests) → sink."""

    return {
        "schema_version": 3,
        "variant": "nawa_radio_watch_v1",
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Trigger",
                "position": {"x": 40, "y": 200},
            },
            {
                "id": "task.dbt",
                "kind": "task",
                "type": "task",
                "label": "dbt — cells at risk",
                "position": {"x": 300, "y": 200},
                "config": {
                    "skill_slug": "dbt_transform_v1",
                    "params": {
                        "models": RADIO_MODELS,
                        "tests_yml": RADIO_TESTS_YML,
                        "output_model": "mart_cell_risk",
                        "output_name": RADIO_DATASET_NAME,
                        "sources": [{"dataset_slug": network_slug, "view": "input"}],
                    },
                },
                "data": {
                    "description": (
                        "dbt-duckdb in an isolated environment: staging + mart, "
                        "and two data tests that decide whether the result is "
                        "publishable."
                    )
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Watchlist",
                "position": {"x": 580, "y": 200},
            },
        ],
        "edges": [
            {"from": "src", "to": "task.dbt", "kind": "data"},
            {"from": "task.dbt", "to": "sink", "kind": "data"},
        ],
    }


def desk_flow(*, predict_slug: str) -> dict[str, Any]:
    """source → bounded AgentLoop → sink. The other half of the story.

    Everything else in this demo is a pipeline: a schedule pushes a whole
    subscriber base through it. This is the surface where somebody *asks*, and
    the interesting part is that the agent is not told to call the model. It is
    given a goal, a catalog of two skills and a subscriber, and the churn model
    is one of the things it may reach for — which is what "a published model is
    a skill an agent can call" means when it is true rather than asserted.

    The loop does not invent the twenty feature values. The walker hands the
    chosen skill the envelope it already has, so the subscriber rides in on the
    run input under ``rows`` and the model's closed contract is satisfied by
    construction; what the model decides is *which* skill, and when it is done.
    Read-only tier: neither skill mutates anything, so no gate interrupts.
    """

    return {
        "schema_version": 3,
        "variant": "nawa_churn_desk_v1",
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Question",
                "position": {"x": 40, "y": 200},
            },
            {
                "id": "loop.desk",
                "kind": "agent_loop",
                "type": "agent_loop",
                "label": "Retention agent",
                "position": {"x": 320, "y": 200},
                "config": {
                    "skill_slug": "decide_next_v1",
                    "decide_skill": "decide_next_v1",
                    "skill_allowlist": [predict_slug, "azure_llm_v1"],
                    "confidence_floor": 0.55,
                    "privilege_tier": "recommend",
                    "on_budget": "exit",
                    "budget": {"max_turns": 4},
                    "goal": {
                        "objective": (
                            "Say whether this subscriber should be called by "
                            "retention, and why. Score them with the churn "
                            "model before advising: an opinion without the "
                            "model's number is not an answer here."
                        ),
                        "done_when": [predict_slug],
                        "status": "active",
                    },
                },
                "data": {
                    "description": (
                        "A bounded think → gate → act loop. Its catalog holds "
                        "the published churn model and a writer; the model "
                        "chooses, the membrane decides what it may run."
                    )
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Verdict",
                "position": {"x": 620, "y": 200},
            },
        ],
        "edges": [
            {"from": "src", "to": "loop.desk", "kind": "data"},
            {"from": "loop.desk", "to": "sink", "kind": "data"},
        ],
    }


def board_flow(*, scored_slug: str) -> dict[str, Any]:
    """source → read the last brief → shape the board → sink. Read-only, all of it.

    The constraint that decided this graph is that a stakeholder presses
    *Refresh*, not *Run the pipeline*. Nothing here may retrain, re-score or
    mint a table: the board reads what last night's pipeline left behind, and
    the two nodes it uses are the only two that read without writing.

    That also rules out the transform nodes, which would otherwise be the
    obvious way to compute this. A SQL or Polars node publishes a **new dataset
    version** on every execution — five refreshes would leave five versions of
    the same table on the Data page — so the shaping happens in a recipe, whose
    output is JSON and whose side effect is a row in the execution ledger.

    Declared schemas on both ends. The source pins an empty closed input, which
    is what lets the page carry a button rather than a form; the sink pins the
    payload the tiles bind to, which is what lets the release refuse a selector
    the board does not actually produce.
    """

    return {
        "schema_version": 3,
        "variant": "nawa_retention_board_v1",
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "label": "Refresh",
                "position": {"x": 40, "y": 200},
                "config": {"input_schema": BOARD_INPUT_SCHEMA},
                "data": {
                    "description": (
                        "One button on the business page. No arguments: the "
                        "board reads the base as the pipeline left it."
                    )
                },
            },
            {
                "id": "task.brief",
                "kind": "task",
                "type": "task",
                "label": "Last retention brief",
                "position": {"x": 300, "y": 200},
                "config": {
                    "skill_slug": "system_run_read_v1",
                    "params": {"system_name": CHURN_SYSTEM_NAME},
                    # Overlay mode does not merge `config.params` implicitly, so
                    # the System named is read back through the node's own
                    # namespace — the same route the pipeline's prompt takes,
                    # and what makes an inspector edit reach the run.
                    "inputs_map": {
                        "system_name": {
                            "node_id": "node",
                            "path": ["config", "params", "system_name"],
                        }
                    },
                },
                "data": {
                    "description": (
                        "Reads what the Churn Radar pipeline concluded last "
                        "time it ran. A read, not a re-run: the committee is "
                        "shown the brief the pipeline wrote, not a fresh "
                        "paraphrase of it."
                    )
                },
            },
            {
                "id": "task.board",
                "kind": "task",
                "type": "task",
                "label": "Board arithmetic",
                "position": {"x": 580, "y": 200},
                "config": {
                    "skill_slug": "python_recipe_v1",
                    "params": {
                        "code": BOARD_CODE,
                        "sources": [
                            {
                                "dataset_slug": scored_slug,
                                "view": BOARD_SOURCE_VIEW,
                                "columns": list(BOARD_COLUMNS),
                            }
                        ],
                    },
                    # Without a map the walker would fold the run input into the
                    # payload, and the recipe's stored input would carry the
                    # ingress envelope beside the rows. The map is empty of new
                    # ports on purpose: in overlay mode it changes nothing about
                    # what arrives, only where it may come from.
                    "inputs_map": {
                        "system_run": {
                            "node_id": "task.brief",
                            "path": ["system_run"],
                        }
                    },
                },
                "data": {
                    "description": (
                        "Counts, rates and money, computed over the scored "
                        "base at read time. Author-written and editable here: "
                        "every figure the board shows is a line in this script."
                    )
                },
            },
            {
                "id": "sink",
                "kind": "sink",
                "label": "Board",
                "position": {"x": 860, "y": 200},
                "config": {"output_schema": BOARD_OUTPUT_SCHEMA},
            },
        ],
        "edges": [
            {"from": "src", "to": "task.brief", "kind": "data"},
            {"from": "task.brief", "to": "task.board", "kind": "data"},
            {"from": "task.board", "to": "sink", "kind": "data"},
        ],
    }


# ---------------------------------------------------------------------------
# The Retention Board's document
# ---------------------------------------------------------------------------


def _copy(key: str, english: str) -> dict[str, Any]:
    """One localized string, written where the block that shows it is written.

    The fallback is what a renderer draws when a dictionary is missing a key,
    so it carries the English rather than a placeholder: a page that degrades
    to ``board.kpi.revenue.label`` has failed, and a page that degrades to
    "Revenue at stake" has merely lost its French.
    """

    return {"$i18n": key, "fallback": english}


def _bind(selector: str) -> dict[str, Any]:
    """Read one path out of whatever the board button's run produced.

    Display blocks never fetch. The button invokes the System once and every
    tile on the page reads that one run, which is why the board is internally
    consistent: the revenue figure and the subscriber count cannot come from
    two different refreshes.
    """

    return {
        "source": "run-output",
        "componentId": BOARD_ACTION_ID,
        "selector": selector,
    }


#: French and English, key for key. The workspace opens in English and every
#: other seeded string is English, but a document is released once and read for
#: longer than a demo — and a stakeholder surface in Morocco that cannot be read
#: in French is a surface with an audience problem, not a translation backlog.
BOARD_I18N: dict[str, dict[str, str]] = {
    "en": {
        "board.header.title": "Retention Board",
        "board.header.subtitle": (
            "Who is about to leave, what that is worth this month, and what to "
            "do about it."
        ),
        "board.action.label": "Refresh the board",
        "board.glance.title": "This month, at a glance",
        "board.glance.description": (
            "Every figure below is computed from the scored subscriber base "
            "when you press Refresh. Nothing here is a stored number."
        ),
        "board.kpi.at_risk.label": "Subscribers flagged at risk",
        "board.kpi.at_risk.description": "Lines the model expects to leave.",
        "board.kpi.revenue.label": "Revenue at stake (MAD / month)",
        "board.kpi.revenue.description": "See how this is calculated, below.",
        "board.kpi.decile.label": "Churn in the riskiest 10% (%)",
        "board.kpi.decile.description": (
            "Observed departures among the tenth of the base the model ranks "
            "highest."
        ),
        "board.kpi.base_rate.label": "Churn across the whole base (%)",
        "board.kpi.base_rate.description": (
            "The baseline the figure on its left has to beat to be worth "
            "acting on."
        ),
        "board.kpi.model.label": "Model score",
        "board.kpi.model.description": (
            "The serving model's headline metric, named in the provenance "
            "table at the foot of this page."
        ),
        "board.revenue_basis.body": (
            "Revenue at stake is one month of recurring revenue from the "
            "flagged subscribers, each subscriber's measured ARPU multiplied "
            "by the model's predicted probability that they leave. The revenue "
            "is measured; the weighting is modelled. It is an exposure, not a "
            "loss that has been booked, and not a saving a campaign would "
            "recover in full."
        ),
        "board.bands.title": "Risk bands",
        "board.bands.caption": (
            "Subscribers by predicted probability of leaving."
        ),
        "board.at_risk.title": "Call these first",
        "board.at_risk.caption": (
            "Flagged subscribers, ordered by the revenue their departure would "
            "put at stake."
        ),
        "board.at_risk.msisdn": "Line",
        "board.at_risk.region": "Region",
        "board.at_risk.plan": "Plan",
        "board.at_risk.tenure": "Tenure (months)",
        "board.at_risk.arpu": "ARPU (MAD)",
        "board.at_risk.score": "Probability",
        "board.at_risk.stake": "At stake (MAD)",
        "board.brief.title": "What the pipeline concluded",
        "board.brief.description": (
            "The retention brief written by the Churn Radar pipeline the last "
            "time it ran. Read here, not regenerated: this is the analysis the "
            "pipeline produced, not a new one."
        ),
        "board.provenance.title": "Where these numbers come from",
        "board.provenance.description": (
            "The model version that scored the base, and the size of the base "
            "it scored."
        ),
        "board.provenance.caption": "Serving model and scored population.",
        "board.provenance.model": "Model",
        "board.provenance.version": "Version",
        "board.provenance.metric": "Metric",
        "board.provenance.metric_value": "Value",
        "board.provenance.base_size": "Subscribers scored",
        "board.empty": "Press Refresh to load the board.",
    },
    "fr": {
        "board.header.title": "Tableau de rétention",
        "board.header.subtitle": (
            "Qui est sur le point de partir, ce que cela représente ce mois-ci, "
            "et quoi faire."
        ),
        "board.action.label": "Actualiser le tableau",
        "board.glance.title": "Ce mois-ci, en un coup d'œil",
        "board.glance.description": (
            "Chaque chiffre ci-dessous est calculé sur la base scorée au moment "
            "où vous actualisez. Aucun n'est une valeur stockée."
        ),
        "board.kpi.at_risk.label": "Abonnés signalés à risque",
        "board.kpi.at_risk.description": (
            "Les lignes dont le modèle attend le départ."
        ),
        "board.kpi.revenue.label": "Revenu exposé (MAD / mois)",
        "board.kpi.revenue.description": "Voir le mode de calcul ci-dessous.",
        "board.kpi.decile.label": "Résiliation dans les 10% les plus risqués (%)",
        "board.kpi.decile.description": (
            "Départs constatés dans le dixième de la base que le modèle classe "
            "en tête."
        ),
        "board.kpi.base_rate.label": "Résiliation sur toute la base (%)",
        "board.kpi.base_rate.description": (
            "La référence que le chiffre de gauche doit dépasser pour valoir "
            "la peine."
        ),
        "board.kpi.model.label": "Score du modèle",
        "board.kpi.model.description": (
            "La métrique principale du modèle en service, nommée dans le "
            "tableau de provenance en bas de page."
        ),
        "board.revenue_basis.body": (
            "Le revenu exposé correspond à un mois de revenu récurrent des "
            "abonnés signalés, l'ARPU mesuré de chacun multiplié par la "
            "probabilité de départ prédite par le modèle. Le revenu est "
            "mesuré ; la pondération est modélisée. C'est une exposition, pas "
            "une perte constatée, ni une économie qu'une campagne "
            "récupérerait intégralement."
        ),
        "board.bands.title": "Bandes de risque",
        "board.bands.caption": (
            "Abonnés par probabilité de départ prédite."
        ),
        "board.at_risk.title": "À appeler en priorité",
        "board.at_risk.caption": (
            "Abonnés signalés, classés par le revenu que leur départ mettrait "
            "en jeu."
        ),
        "board.at_risk.msisdn": "Ligne",
        "board.at_risk.region": "Région",
        "board.at_risk.plan": "Offre",
        "board.at_risk.tenure": "Ancienneté (mois)",
        "board.at_risk.arpu": "ARPU (MAD)",
        "board.at_risk.score": "Probabilité",
        "board.at_risk.stake": "En jeu (MAD)",
        "board.brief.title": "Ce que le pipeline a conclu",
        "board.brief.description": (
            "La note de rétention rédigée par le pipeline Churn Radar lors de "
            "sa dernière exécution. Relue ici, pas régénérée : c'est l'analyse "
            "que le pipeline a produite, pas une nouvelle."
        ),
        "board.provenance.title": "D'où viennent ces chiffres",
        "board.provenance.description": (
            "La version du modèle qui a scoré la base, et la taille de la base "
            "scorée."
        ),
        "board.provenance.caption": "Modèle en service et population scorée.",
        "board.provenance.model": "Modèle",
        "board.provenance.version": "Version",
        "board.provenance.metric": "Métrique",
        "board.provenance.metric_value": "Valeur",
        "board.provenance.base_size": "Abonnés scorés",
        "board.empty": "Actualisez pour charger le tableau.",
    },
}

#: Everyone who belongs to the workspace, named role by role rather than left
#: open. The board exists for the roles that are *not* engineers — a viewer with
#: no Builder access is the reader this page was written for — and an empty
#: policy would have granted the same thing by accident rather than on purpose.
BOARD_ACCESS_POLICY: dict[str, Any] = {
    "role_templates": [
        "workspace_viewer",
        "workspace_contributor",
        "workspace_reviewer",
        "workspace_admin",
        "workspace_owner",
    ]
}


def board_document() -> dict[str, Any]:
    """One page, filled by one click.

    The spine is the order a stakeholder reads in: what is at risk, what it is
    worth, whether the model's ranking beats the base rate, then the list to
    act on and the brief that explains it. The button sits at the top rather
    than the bottom because a page whose tiles are all empty until you scroll
    past them to find the control is a page that looks broken.

    Every tile reads ``run-output`` from that one button. No tile carries a
    ``queryBinding``: the alternative — each tile invoking the System for
    itself — would run the board five times per view and could show a revenue
    figure and a subscriber count from two different refreshes.
    """

    return {
        "i18n": BOARD_I18N,
        "pages": [
            {
                "id": "board",
                "title": _copy("board.header.title", "Retention Board"),
                "components": [
                    {
                        "type": "header",
                        "id": "board-header",
                        "props": {
                            "title": _copy("board.header.title", "Retention Board"),
                            "subtitle": _copy(
                                "board.header.subtitle",
                                BOARD_I18N["en"]["board.header.subtitle"],
                            ),
                        },
                    },
                    {
                        "type": "action_button",
                        "id": BOARD_ACTION_ID,
                        "props": {
                            "label": _copy("board.action.label", "Refresh the board"),
                            "bindingKey": BOARD_BINDING_KEY,
                            # The board takes no arguments, and the published
                            # ingress refuses any — so this is the whole of the
                            # request a stakeholder sends.
                            "input": {},
                            "afterSuccess": "stay",
                        },
                    },
                    # Between the click and the figures there are a couple of
                    # seconds of nothing, and afterwards there may be a node
                    # that failed — the scored table missing because the
                    # pipeline has not run, say. Both look identical on a page
                    # of empty tiles, so the run says which it is out loud.
                    {
                        "type": "runtime_status",
                        "id": "board-status",
                    },
                    {
                        "type": "section",
                        "id": "at-a-glance",
                        "props": {
                            "title": _copy(
                                "board.glance.title", "This month, at a glance"
                            ),
                            "description": _copy(
                                "board.glance.description",
                                BOARD_I18N["en"]["board.glance.description"],
                            ),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "kpi-at-risk",
                        "props": {
                            "label": _copy(
                                "board.kpi.at_risk.label",
                                "Subscribers flagged at risk",
                            ),
                            "description": _copy(
                                "board.kpi.at_risk.description",
                                BOARD_I18N["en"]["board.kpi.at_risk.description"],
                            ),
                            "dataBinding": _bind("summary.subscribers_at_risk"),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "kpi-revenue",
                        "props": {
                            "label": _copy(
                                "board.kpi.revenue.label",
                                "Revenue at stake (MAD / month)",
                            ),
                            "description": _copy(
                                "board.kpi.revenue.description",
                                BOARD_I18N["en"]["board.kpi.revenue.description"],
                            ),
                            "dataBinding": _bind("summary.revenue_at_stake_mad"),
                        },
                    },
                    # The two rates are adjacent because neither means anything
                    # alone: the decile rate is a model result only relative to
                    # the base rate beside it.
                    {
                        "type": "kpi",
                        "id": "kpi-decile-churn",
                        "props": {
                            "label": _copy(
                                "board.kpi.decile.label",
                                "Churn in the riskiest 10% (%)",
                            ),
                            "description": _copy(
                                "board.kpi.decile.description",
                                BOARD_I18N["en"]["board.kpi.decile.description"],
                            ),
                            "dataBinding": _bind("summary.riskiest_decile_churn_pct"),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "kpi-base-churn",
                        "props": {
                            "label": _copy(
                                "board.kpi.base_rate.label",
                                "Churn across the whole base (%)",
                            ),
                            "description": _copy(
                                "board.kpi.base_rate.description",
                                BOARD_I18N["en"]["board.kpi.base_rate.description"],
                            ),
                            "dataBinding": _bind("summary.base_churn_pct"),
                        },
                    },
                    {
                        "type": "kpi",
                        "id": "kpi-model-metric",
                        "props": {
                            "label": _copy("board.kpi.model.label", "Model score"),
                            "description": _copy(
                                "board.kpi.model.description",
                                BOARD_I18N["en"]["board.kpi.model.description"],
                            ),
                            "dataBinding": _bind("summary.model_metric_value"),
                        },
                    },
                    {
                        "type": "callout",
                        "id": "revenue-basis",
                        "props": {
                            "body": _copy(
                                "board.revenue_basis.body",
                                BOARD_I18N["en"]["board.revenue_basis.body"],
                            )
                        },
                    },
                    {
                        "type": "chart",
                        "id": "risk-bands",
                        "props": {
                            "title": _copy("board.bands.title", "Risk bands"),
                            "caption": _copy(
                                "board.bands.caption",
                                BOARD_I18N["en"]["board.bands.caption"],
                            ),
                            "kind": "bar",
                            "labelKey": "label",
                            "valueKey": "value",
                            "a11y": {
                                "emptyText": _copy(
                                    "board.empty", "Press Refresh to load the board."
                                )
                            },
                            "dataBinding": _bind("bands"),
                        },
                    },
                    {
                        "type": "table",
                        "id": "at-risk-table",
                        "props": {
                            "title": _copy("board.at_risk.title", "Call these first"),
                            "caption": _copy(
                                "board.at_risk.caption",
                                BOARD_I18N["en"]["board.at_risk.caption"],
                            ),
                            "columns": [
                                {
                                    "key": "msisdn",
                                    "label": _copy("board.at_risk.msisdn", "Line"),
                                },
                                {
                                    "key": "region",
                                    "label": _copy("board.at_risk.region", "Region"),
                                },
                                {
                                    "key": "plan",
                                    "label": _copy("board.at_risk.plan", "Plan"),
                                },
                                {
                                    "key": "tenure_months",
                                    "label": _copy(
                                        "board.at_risk.tenure", "Tenure (months)"
                                    ),
                                },
                                {
                                    "key": "arpu_mad",
                                    "label": _copy("board.at_risk.arpu", "ARPU (MAD)"),
                                },
                                {
                                    "key": "score",
                                    "label": _copy(
                                        "board.at_risk.score", "Probability"
                                    ),
                                },
                                {
                                    "key": "revenue_at_stake_mad",
                                    "label": _copy(
                                        "board.at_risk.stake", "At stake (MAD)"
                                    ),
                                },
                            ],
                            "a11y": {
                                "emptyText": _copy(
                                    "board.empty", "Press Refresh to load the board."
                                )
                            },
                            "dataBinding": _bind("at_risk"),
                        },
                    },
                    {
                        "type": "section",
                        "id": "brief-heading",
                        "props": {
                            "title": _copy(
                                "board.brief.title", "What the pipeline concluded"
                            ),
                            "description": _copy(
                                "board.brief.description",
                                BOARD_I18N["en"]["board.brief.description"],
                            ),
                        },
                    },
                    {
                        "type": "result",
                        "id": "retention-brief",
                        "props": {"dataBinding": _bind("brief")},
                    },
                    {
                        "type": "section",
                        "id": "provenance-heading",
                        "props": {
                            "title": _copy(
                                "board.provenance.title",
                                "Where these numbers come from",
                            ),
                            "description": _copy(
                                "board.provenance.description",
                                BOARD_I18N["en"]["board.provenance.description"],
                            ),
                        },
                    },
                    # The summary object read as one row: which model answered,
                    # which version of it, and over how many subscribers. A
                    # figure whose provenance is a page away is a figure that
                    # gets argued about.
                    {
                        "type": "table",
                        "id": "board-provenance",
                        "props": {
                            "caption": _copy(
                                "board.provenance.caption",
                                BOARD_I18N["en"]["board.provenance.caption"],
                            ),
                            "columns": [
                                {
                                    "key": "model_name",
                                    "label": _copy(
                                        "board.provenance.model", "Model"
                                    ),
                                },
                                {
                                    "key": "model_version",
                                    "label": _copy(
                                        "board.provenance.version", "Version"
                                    ),
                                },
                                {
                                    "key": "model_metric_key",
                                    "label": _copy(
                                        "board.provenance.metric", "Metric"
                                    ),
                                },
                                {
                                    "key": "model_metric_value",
                                    "label": _copy(
                                        "board.provenance.metric_value", "Value"
                                    ),
                                },
                                {
                                    "key": "base_size",
                                    "label": _copy(
                                        "board.provenance.base_size",
                                        "Subscribers scored",
                                    ),
                                },
                            ],
                            "a11y": {
                                "emptyText": _copy(
                                    "board.empty", "Press Refresh to load the board."
                                )
                            },
                            "dataBinding": _bind("summary"),
                        },
                    },
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# The Retention Board's binding, draft, release and deployment
# ---------------------------------------------------------------------------

BOARD_RELEASE_NOTES = (
    "Retention Board — the business reading of the Churn Radar pipeline: who "
    "is flagged, what one month of their revenue is worth, and how the "
    "model's riskiest decile compares with the base."
)


def ensure_board_binding(db: DBSession, workspace: Workspace, system: System) -> Any:
    """The stable key the page invokes, pointed at the current publication.

    Created once and *retargeted* afterwards. The alternative — delete and
    recreate — would work here and be wrong everywhere else: a binding key is
    the contract a released document holds, and rewriting the row under it is
    how a republished graph reaches a page that was authored against the
    previous version. Retargeting is the operation the Studio offers a human
    for exactly this, so the seed performs the same one.
    """

    from app.services.experience import bindings as binding_service

    version_id = system.published_flow_version_id
    if not version_id:
        raise SystemExit(
            f"{system.name}: the System has no published Flow version, so "
            f"'{BOARD_BINDING_KEY}' cannot be bound. Flow publication has to be "
            "enabled on this workspace before the board can answer /work."
        )

    try:
        row = binding_service.get_binding(
            db, workspace_id=workspace.id, binding_key=BOARD_BINDING_KEY
        )
    except binding_service.BindingError:
        row = binding_service.create_binding(
            db,
            workspace=workspace,
            actor=SEED_ACTOR,
            binding_key=BOARD_BINDING_KEY,
            system_id=system.id,
            published_flow_version_id=version_id,
            ingress_id="src",
            # The board reads. Nothing it does needs a stakeholder to confirm
            # they meant it, and a confirmation dialog in front of a refresh
            # button teaches people to click through dialogs.
            confirmation_policy="direct-safe",
            on_unavailable="unavailable",
        )
    else:
        if row.published_flow_version_id != version_id:
            row = binding_service.retarget_binding(
                db,
                workspace=workspace,
                binding_key=BOARD_BINDING_KEY,
                actor=SEED_ACTOR,
            )
    db.commit()
    db.refresh(row)
    print(
        f"binding ready: {row.binding_key} → {system.name} "
        f"ingress={row.ingress_id} version={row.published_flow_version_id}"
    )
    return row


def _board_release(db: DBSession, workspace: Workspace, experience: Any) -> Any:
    """The release carrying this document, reused when one already does.

    A release is immutable evidence, so re-cutting an identical one is not
    harmless housekeeping: it would leave the Releases list growing by one on
    every rehearsal, each entry indistinguishable from the last. The document
    digest and the binding snapshot together are what a release *is*, so a
    release that already matches both is the release this seed wanted.
    """

    from app.models.experience import ExperienceRelease
    from app.services.experience import lifecycle

    check = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise SystemExit(
            f"{BOARD_EXPERIENCE_SLUG}: the draft is not releasable — "
            f"{check['blockers']}"
        )
    _row, draft, _deployments = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    access = dict(experience.access_policy or {})
    for candidate in (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.experience_id == experience.id,
            ExperienceRelease.workspace_id == workspace.id,
        )
        .order_by(ExperienceRelease.release_number.desc())
        .all()
    ):
        if (
            candidate.content_sha256 == draft.content_sha256
            and (candidate.bindings_snapshot or []) == check["bindings"]
            and dict(candidate.access_snapshot or {}) == access
        ):
            return candidate
    return lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes=BOARD_RELEASE_NOTES,
        expected_draft_revision=int(draft.revision),
        expected_content_sha256=draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=check["bindings_sha256"],
        actor=SEED_ACTOR,
    )


def ensure_board_experience(db: DBSession, workspace: Workspace) -> Any:
    """The business page itself: identity, draft, release, live deployment.

    Through the lifecycle service rather than by writing the four tables. The
    migrations that seeded the earlier apps had no ORM to reach for and wrote
    rows directly; a script does, and the service is where the ready-check
    lives — the one that certifies every block type, resolves every
    ``dataBinding`` against the page and every selector against the published
    output contract. A seed that bypassed it could deploy a board whose tiles
    are bound to paths the System does not produce, and would find out on
    stage.

    Deployed to ``live`` rather than ``pilot``: a pilot audience is a subset of
    the release's, which is the right tool for trialling a change on a few
    people and the wrong one for a page whose entire purpose is that the
    business can open it.
    """

    from app.models.experience import Experience, ExperienceDeployment
    from app.services.experience import lifecycle

    document = board_document()
    binding_keys = lifecycle.referenced_binding_keys(document)

    experience = (
        db.query(Experience)
        .filter(
            Experience.workspace_id == workspace.id,
            Experience.slug == BOARD_EXPERIENCE_SLUG,
        )
        .one_or_none()
    )
    if experience is None:
        experience, _draft = lifecycle.create_experience(
            db,
            workspace=workspace,
            actor=SEED_ACTOR,
            name=BOARD_EXPERIENCE_NAME,
            slug=BOARD_EXPERIENCE_SLUG,
            pattern="dashboard",
            languages=["en", "fr"],
            # No ``live_href``. The work shell reads that field as "this
            # application really lives somewhere else" and redirects off
            # ``/work/<slug>``, which for this page would redirect away from
            # the thing being built.
            theme={},
            access_policy=BOARD_ACCESS_POLICY,
            description=(
                "Who is about to churn, what it is worth, and what to do "
                "about it."
            ),
        )
        db.commit()
        db.refresh(experience)
    else:
        experience = lifecycle.update_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience.id,
            name=BOARD_EXPERIENCE_NAME,
            pattern="dashboard",
            languages=["en", "fr"],
            theme={},
            access_policy=BOARD_ACCESS_POLICY,
            actor=SEED_ACTOR,
        )
        db.commit()
        db.refresh(experience)

    _row, draft, _deployments = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    lifecycle.save_draft(
        db,
        workspace_id=workspace.id,
        experience_id=experience.id,
        pages=document,
        binding_keys=binding_keys,
        expected_revision=int(draft.revision),
        actor=SEED_ACTOR,
    )
    db.commit()
    db.refresh(experience)

    release = _board_release(db, workspace, experience)
    db.commit()

    deployment = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == experience.id,
            ExperienceDeployment.channel == "live",
        )
        .one_or_none()
    )
    if deployment is None or deployment.release_id != release.id:
        deployment = lifecycle.deploy(
            db,
            workspace=workspace,
            experience_id=experience.id,
            channel="live",
            release_id=release.id,
            expected_current_release_id=(
                deployment.release_id if deployment is not None else None
            ),
            expected_deployment_updated_at=(
                deployment.updated_at if deployment is not None else None
            ),
            # Live audience is frozen by the release's access snapshot, and
            # passing it again would only be a second chance to disagree with
            # it.
            audience=None,
            actor=SEED_ACTOR,
        )
        db.commit()
    db.refresh(deployment)
    print(
        f"experience live: /work/{experience.slug} release "
        f"r{release.release_number} audience={deployment.audience}"
    )
    return experience


# ---------------------------------------------------------------------------
# Systems
# ---------------------------------------------------------------------------


def ensure_system(
    db: DBSession,
    workspace: Workspace,
    capability: Capability,
    *,
    name: str,
    objective: str,
    flow: dict[str, Any],
    system_type: str,
    execution_mode: str = "batch_processing",
    extra_skill_ids: tuple[str, ...] = (),
) -> System:
    """Upsert one System by name and reconcile its published Flow.

    ``extra_skill_ids`` binds a Skill the claiming Capability cannot hold: a
    workspace-published model is authored, not seeded, so it has no slug for
    ``ensure_capability`` to look up — but every slug an executable node names,
    including an AgentLoop's allowlist, has to be bound or the walker refuses
    the graph.
    """

    bound = list(capability.skill_ids or [])
    for skill_id in extra_skill_ids:
        if skill_id and skill_id not in bound:
            bound.append(skill_id)
    payload = {
        "objective": objective,
        "capability_id": capability.id,
        "skill_ids": bound,
        "flow_definition": flow,
        "settings": {
            "nawa_data_demo": True,
            "surface": "system",
            "system_type": system_type,
            "brand": "Nawa",
        },
        # Canonical vocabulary, enforced by ``ck_systems_execution_mode``: the
        # pipelines run over a whole subscriber base on a schedule, the desk
        # answers one question at a time.
        "execution_mode": execution_mode,
        "execution_profile": {"nawa_data_demo": True, "persona": "data_scientist"},
        "coordination_pattern": "graph",
        "status": "active",
        "created_by": SEED_ACTOR,
        "default_prompt_type": "factual",
        "default_model": "gpt-4o-mini",
        "retrieval_mode_default": "hybrid",
    }
    outcome: flow_publication.FlowReconcileResult | None = None
    system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == name)
        .first()
    )
    if system:
        for key, value in payload.items():
            if key == "flow_definition":
                continue
            setattr(system, key, value)
        outcome = flow_publication.reconcile_system_flow(
            db,
            system=system,
            workspace=workspace,
            flow_definition=flow,
            actor=SEED_ACTOR,
            publish_if_owned=True,
            ownership_prefix=SEED_ACTOR,
            message=f"{name} — seed reconciliation",
        )
        system.updated_at = datetime.utcnow()
    else:
        system = System(id=str(uuid4()), workspace_id=workspace.id, name=name, **payload)
        db.add(system)
        db.flush()
        flow_publication.initialize_new_system_publication_if_enabled(
            db, system=system, workspace=workspace, actor=SEED_ACTOR
        )

    if not flow_publication.flow_publication_enabled(workspace):
        baseline = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.system_id == system.id,
                SystemVersion.version_number == 1,
            )
            .first()
        )
        if baseline:
            baseline.flow_definition = flow
            baseline.message = f"{name} — baseline seed"
        else:
            db.add(
                SystemVersion(
                    id=str(uuid4()),
                    workspace_id=workspace.id,
                    system_id=system.id,
                    version_number=1,
                    flow_definition=flow,
                    message=f"{name} — baseline seed",
                    created_by=SEED_ACTOR,
                )
            )
    db.commit()
    db.refresh(system)
    # ``reconcile_system_flow`` may decline: a draft an operator left open in
    # the Builder is preserved, publication and all. That rule is right, and it
    # is also how a re-seed ends up running the *previous* graph — the one whose
    # dataset slugs the reset just retired. The engine executes
    # ``flow_definition``, so compare against that and say so, rather than
    # narrate success and let four nodes fail a minute later.
    live = flow_publication.canonical_flow_sha256(system.flow_definition)
    if live != flow_publication.canonical_flow_sha256(flow):
        draft = db.query(SystemFlowDraft).filter_by(system_id=system.id).one_or_none()
        raise SystemExit(
            f"{name}: the executable graph is not the one this seed describes "
            f"(reconciliation returned {getattr(outcome, 'status', 'created')!r}, draft held by "
            f"{getattr(draft, 'updated_by', None)!r}). Re-run with --reset, "
            "which discards the seed's own drafts, or publish the draft."
        )
    print(f"system ready: {system.name} id={system.id} status={system.status}")
    return system


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def train_inline(
    db: DBSession,
    workspace: Workspace,
    dataset: TabularDataset,
    *,
    algo: str,
    features: list[str],
    knobs: dict[str, Any] | None = None,
    description: str,
) -> MLModel:
    """Fit one version of the lineage synchronously, through the worker code.

    ``run_training`` rather than a Celery dispatch: a seed has to finish before it
    returns, and this is the same function the worker calls — same harness, same
    subprocess limits, same artifact. Nothing about the model is faked.
    """

    from app.services.tabular_ml import create_model, run_training, validate_training

    spec = validate_training(
        dataset,
        task="classification",
        target=CHURN_TARGET,
        features=features,
        algo=algo,
        knobs=knobs,
        test_size=0.25,
        cross_validation=0,
        name=MODEL_NAME,
    )
    model = create_model(
        db,
        workspace_id=workspace.id,
        spec=spec,
        description=description,
        created_by=SEED_ACTOR,
    )
    model_id = model.id
    db.commit()
    outcome = run_training(model_id)
    db.expire_all()
    fresh = db.query(MLModel).filter(MLModel.id == model_id).one()
    if outcome.get("status") != "ready":
        raise SystemExit(f"training failed for {algo}: {fresh.error}")
    primary = (fresh.metrics_json or {}).get("primary") or {}
    print(
        f"model ready: {fresh.name} v{fresh.version} algo={fresh.algo} "
        f"{primary.get('key')}={primary.get('value')} rows={fresh.row_count}"
    )
    return fresh


def _reusable_model(
    db: DBSession,
    workspace: Workspace,
    *,
    algo: str,
    features: list[str],
    dataset: TabularDataset,
) -> MLModel | None:
    """A ready version of this lineage already fitted on exactly this problem.

    Same estimator, same columns, same dataset row: re-fitting it would produce
    a byte-identical model under a new version number, pushing the Models page
    towards a list of duplicates and — because the seed promotes its baseline —
    quietly demoting whatever was promoted during the last rehearsal.
    """

    wanted = list(features)
    candidates = (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == workspace.id,
            MLModel.name == MODEL_NAME,
            MLModel.algo == algo,
            MLModel.status == "ready",
            MLModel.dataset_id == dataset.id,
        )
        .order_by(MLModel.version.asc())
        .all()
    )
    for candidate in candidates:
        if list(candidate.features or []) == wanted:
            return candidate
    return None


def seed_model_history(
    db: DBSession, workspace: Workspace, cleaned: TabularDataset
) -> list[MLModel]:
    """Two versions before the pipeline's own: the one that shipped, and a rival.

    Both fit the same cleaned base with the same 20 columns, so the only thing
    that differs between them is the estimator — which is what makes the gap
    between them attributable. Measured on this generator, held out at 25%, the
    linear baseline reaches ROC AUC 0.835 and the boosted trees 0.860.

    The gap is real and it has a named cause: churn here is genuinely
    non-additive (a ticket in the first year is not the same event as a ticket in
    the fifth), and survey non-response carries signal that the trees read as a
    missing branch while the baseline has it imputed away. See ``_churn_logit``
    in the generator.

    Returned oldest first. The caller leaves the *baseline* serving on purpose:
    an interpretable first model that nobody has replaced yet is the ordinary
    state of a real registry, and it is what gives the demo a promotion to
    perform whose delta is worth reading out loud.
    """

    base_features = [name for name in CHURN_FEATURE_COLUMNS]
    fits = (
        (
            "linear",
            {"max_iter": 1000},
            "Logistic regression on the cleaned base. The first model put in "
            "service: interpretable, and still there for want of a challenger.",
        ),
        (
            "gradient_boosting",
            {"max_iter": 220, "learning_rate": 0.08},
            "Same data, same 20 columns, gradient boosting: what the estimator "
            "alone changes. Interactions and survey non-response account for "
            "the gap.",
        ),
    )
    history: list[MLModel] = []
    for algo, knobs, description in fits:
        existing = _reusable_model(
            db, workspace, algo=algo, features=base_features, dataset=cleaned
        )
        if existing is not None:
            primary = (existing.metrics_json or {}).get("primary") or {}
            print(
                f"model kept: {existing.name} v{existing.version} algo={existing.algo} "
                f"{primary.get('key')}={primary.get('value')}"
            )
            history.append(existing)
            continue
        history.append(
            train_inline(
                db,
                workspace,
                cleaned,
                algo=algo,
                features=base_features,
                knobs=knobs,
                description=description,
            )
        )
    return history


def promote_if_nobody_has(
    db: DBSession, workspace: Workspace, model: MLModel
) -> MLModel:
    """Put ``model`` in service, unless some version of the lineage already is.

    A seed decides what serves on a *fresh* database. On a re-run it must not:
    promoting the baseline again would undo the promotion the last rehearsal
    performed on stage, which is the one piece of state a demo operator changes
    by hand and expects to survive.
    """

    from app.services.tabular_ml import set_champion

    serving = (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == workspace.id,
            MLModel.name == MODEL_NAME,
            MLModel.is_champion.is_(True),
            MLModel.status == "ready",
        )
        .first()
    )
    if serving is not None:
        print(f"champion kept: {serving.name} v{serving.version}")
        return serving
    promoted = set_champion(db, model)
    print(f"champion: {promoted.name} v{promoted.version}")
    return promoted


def published_skill_slug(envelope: Mapping[str, Any] | None) -> str:
    """The Skill slug inside what :func:`publish_and_mint` hands back.

    A named reader because the envelope carries the Skill beside the API key
    rather than being it, and a caller that reaches for ``slug`` on the outer
    dict gets ``None`` in perfect silence — which is how the desk, whose whole
    existence is conditional on finding this slug, once vanished from a seed
    that reported success.
    """

    skill = (envelope or {}).get("skill")
    if not isinstance(skill, Mapping):
        return ""
    return str(skill.get("slug") or "")


def publish_and_mint(db: DBSession, model: MLModel) -> dict[str, Any]:
    """Publish the champion as a Skill and mint one key for the cURL beat."""

    from app.models.tabular import MLModelApiKey
    from app.services.tabular_predict import list_api_keys, mint_api_key, publish_as_skill

    published = publish_as_skill(db, model=model, created_by=SEED_ACTOR)
    print(f"skill published: {published.get('slug')}")

    existing = [
        row
        for row in list_api_keys(db, model=model)
        if row.name == API_KEY_NAME and row.revoked_at is None
    ]
    if existing:
        print(f"api key kept: prefix={existing[0].key_prefix} (secret shown once only)")
        return {"skill": published, "api_key_prefix": existing[0].key_prefix, "secret": None}

    row, secret = mint_api_key(db, model=model, name=API_KEY_NAME, created_by=SEED_ACTOR)
    assert isinstance(row, MLModelApiKey)
    print(f"api key minted: prefix={row.key_prefix}")
    return {"skill": published, "api_key_prefix": row.key_prefix, "secret": secret}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def pick_at_risk(frame: Any) -> dict[str, Any]:
    """The twenty feature values of one subscriber worth phoning.

    Read out of the cleaned table rather than typed out: the model's contract is
    closed on twenty columns with declared types, and a hand-written literal is
    one integer-shaped float away from a refusal the demo would have to explain.
    A row that came out of the Parquet the model was fitted on cannot be the
    wrong shape.

    Chosen by profile, not by score — the score is what the agent is for. The
    ordering makes it the same subscriber on every re-seed, so the runbook can
    quote the answer it gets.
    """

    import polars as pl

    at_risk = frame.filter(
        (pl.col("plan") == "prepaid")
        & (pl.col("contract") == "monthly")
        & (pl.col("tenure_months") <= 6)
        & (pl.col("support_tickets") >= 3)
    ).sort("msisdn")
    if at_risk.height == 0:
        raise SystemExit(
            "the cleaned table holds no short-tenure prepaid subscriber with "
            "open tickets; the desk would be asked about nobody."
        )
    row = at_risk.head(1).to_dicts()[0]
    return {name: row[name] for name in CHURN_FEATURE_COLUMNS}


def at_risk_subscriber(dataset: TabularDataset) -> dict[str, Any]:
    """``pick_at_risk`` over the bytes a seeded dataset actually holds."""

    from app.services.tabular_datasets import read_frame

    return pick_at_risk(read_frame(dataset))


def run_system(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    input_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one seeded System through the DAG walker and report per node.

    Through the engine rather than by writing checkpoints by hand: the canvas
    badges read ``node_end`` frames produced from real output envelopes, and a
    seed that authored them itself would prove nothing about the pipeline.

    The pipelines read their inputs from the graph and need no payload; the desk
    is asked *about* something, so its subscriber arrives here.
    """

    from app.services.run_engine.dag import execute_run_dag

    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        input_ref=dict(input_ref or {}),
        status="pending",
        trigger="nawa_data_seed",
    )
    db.add(run)
    db.commit()
    run_id = run.id

    asyncio.run(execute_run_dag(run_id))

    db.expire_all()
    fresh = db.query(Run).filter(Run.id == run_id).one()
    nodes = [
        {
            "node_id": entry.get("node_id"),
            "status": entry.get("status"),
            "skill_slug": entry.get("skill_slug"),
            "latency_ms": entry.get("latency_ms"),
            "data": entry.get("data") or {},
            "error": entry.get("error"),
        }
        for entry in (fresh.checkpoints or [])
        if entry.get("kind") == "node_end"
    ]
    print(f"run {run_id}: status={fresh.status} nodes={len(nodes)}")
    for node in nodes:
        badge = node["data"]
        figure = ""
        if badge.get("rows_in") and badge.get("rows_out"):
            figure = f"{badge['rows_in']} → {badge['rows_out']} rows"
        elif badge.get("rows_out") or badge.get("rows_in"):
            figure = f"{badge.get('rows_out') or badge.get('rows_in')} rows"
        if badge.get("metric"):
            figure = f"{figure} · {badge['metric'].get('key')} {badge['metric'].get('value')}".strip(" ·")
        print(
            f"  {node['node_id']}: {node['status']} "
            f"{figure or '—'} ({node['latency_ms']} ms)"
        )
        if node["error"]:
            print(f"    error: {str(node['error'])[:200]}")
    return {"run_id": run_id, "status": fresh.status, "nodes": nodes}


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def owned_datasets(db: DBSession, workspace: Workspace) -> list[TabularDataset]:
    """Every live dataset this demo is responsible for, oldest first.

    Found by walking lineage rather than by matching names, which is what makes
    it survive a rename: the two uploads are the seed's because it stamped
    ``created_by``, and everything else the demo owns descends from them through
    ``parent_ids``. A dataset somebody else uploaded into the same workspace has
    no such ancestor and is therefore never touched.
    """

    rows = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.status != "deleted",
        )
        .order_by(TabularDataset.created_at.asc())
        .all()
    )
    owned = {row.id for row in rows if row.created_by == SEED_ACTOR}
    # One pass per generation. The chain is five deep, so bounding the loop by
    # the row count is generous rather than clever.
    for _ in range(len(rows)):
        grew = False
        for row in rows:
            if row.id in owned:
                continue
            if owned.intersection(row.parent_ids or []):
                owned.add(row.id)
                grew = True
        if not grew:
            break
    return [row for row in rows if row.id in owned]


def reset(db: DBSession, workspace: Workspace) -> dict[str, int]:
    """Retire the tables and models a previous seed left, so a re-seed replaces
    them rather than sitting beside them.

    Needed the day the seeded copy changes language: names drive slugs, and a
    seed that only ever adds would leave the old incarnation on the Data page
    next to the new one. Deliberately narrow — the demo's own dataset lineage
    and its ``Churn Radar`` versions — because ``nawa`` is a real workspace with
    other content in it.

    The Systems are **not** removed, and that is the point: ``ensure_system``
    already reconciles their graph, so a re-seed rewrites the node labels in
    place and the run history behind them survives. What has to go is what the
    seed can only ever add to.

    Their *drafts* do go. Reconciliation refuses to republish over a draft left
    open in the Builder, which is the correct rule for somebody's unsaved work
    and the wrong one here: the graph names its input by slug, the reset has
    just retired that slug, and a preserved draft means the re-seed executes a
    pipeline whose first node can no longer resolve its dataset. ``--reset``
    already says it replaces the previous incarnation and discards a champion
    promoted on stage; a draft over the seed's own System is the same kind of
    thing. Deleting the row is enough — ``initialize_publication_state``
    rebuilds a clean one from the published mirror on the next reconciliation.

    The business page is the one thing here that *is* torn down whole — the
    deployment, every release, the draft and its history, the Experience row
    and the board's binding — because a released document is immutable
    evidence and a re-seed cannot edit one. Left in place, a changed board
    would deploy the *old* release, or refuse the new one because the release
    the deployment holds was cut against a binding that no longer resolves.
    Nothing outside the seed's own slug and key is touched.

    Models go first: a version holds a foreign key to the table it was fitted
    on, and ``delete_model`` is what also clears the API key, the registry
    version and the published Skill that must not outlive it.
    """

    from app.models.experience import (
        Experience,
        ExperienceDeployment,
        ExperienceDraftHistory,
        ExperienceDraftRevision,
        ExperienceRelease,
    )
    from app.models.system_binding import SystemBinding
    from app.services.tabular_datasets import soft_delete
    from app.services.tabular_ml import delete_model

    tally = {
        "models": 0,
        "datasets": 0,
        "drafts": 0,
        "experiences": 0,
        "bindings": 0,
    }

    for system in (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.created_by == SEED_ACTOR,
            System.name.in_(
                (
                    CHURN_SYSTEM_NAME,
                    RADIO_SYSTEM_NAME,
                    DESK_SYSTEM_NAME,
                    BOARD_SYSTEM_NAME,
                )
            ),
        )
        .all()
    ):
        draft = db.query(SystemFlowDraft).filter_by(system_id=system.id).one_or_none()
        if draft is None:
            continue
        print(f"reset: draft on {system.name} (r{draft.revision} by {draft.updated_by})")
        db.delete(draft)
        tally["drafts"] += 1

    experience = (
        db.query(Experience)
        .filter(
            Experience.workspace_id == workspace.id,
            Experience.slug == BOARD_EXPERIENCE_SLUG,
        )
        .one_or_none()
    )
    if experience is not None:
        # In dependency order rather than by cascade: SQLite is a supported
        # backend for this seed and does not enforce foreign keys unless asked,
        # so the deployment's RESTRICT on its release is honoured here by
        # deleting the pointer first.
        for model_class in (
            ExperienceDeployment,
            ExperienceRelease,
            ExperienceDraftHistory,
            ExperienceDraftRevision,
        ):
            db.query(model_class).filter(
                model_class.experience_id == experience.id
            ).delete(synchronize_session=False)
        print(f"reset: experience /work/{experience.slug}")
        db.delete(experience)
        tally["experiences"] += 1

    binding = (
        db.query(SystemBinding)
        .filter(
            SystemBinding.workspace_id == workspace.id,
            SystemBinding.binding_key == BOARD_BINDING_KEY,
        )
        .one_or_none()
    )
    if binding is not None:
        print(f"reset: binding {binding.binding_key}")
        db.delete(binding)
        tally["bindings"] += 1

    for model in (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace.id, MLModel.name == MODEL_NAME)
        .order_by(MLModel.version.desc())
        .all()
    ):
        print(f"reset: model {model.name} v{model.version} ({model.algo})")
        delete_model(db, model)
        tally["models"] += 1

    for dataset in reversed(owned_datasets(db, workspace)):
        print(f"reset: dataset {dataset.name} v{dataset.version}")
        soft_delete(db, dataset)
        tally["datasets"] += 1
    db.commit()

    print(
        "reset: {models} model versions, {datasets} datasets, "
        "{drafts} Flow drafts, {experiences} business pages, "
        "{bindings} bindings".format(**tally)
    )
    return tally


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

STAGES = ("workspace", "datasets", "models", "systems", "runs", "publish")


def assert_runs_are_green(runs: dict[str, Any]) -> None:
    """Refuse to call a rehearsal successful when it left nodes red.

    A DAG whose nodes failed still reports ``completed``: the walker's job is to
    finish the graph, not to judge it. The seed's job is the opposite — it exists
    so that somebody can open the demo cold — and the failure it has to catch is
    precisely the quiet one, where every dataset and model looks right on the
    Data and Models pages and the Flow behind them opens on four red nodes.

    Every run is executed and printed before this fires: when one pipeline
    breaks, the state of the other is the first thing worth knowing.
    """

    broken = [
        f"{key}.{node['node_id']}: {str(node['error'])[:160]}"
        for key, value in runs.items()
        for node in value.get("nodes", [])
        if node.get("status") == "failed"
    ]
    if broken:
        raise SystemExit(
            "seeded runs left failed nodes; the demo would open on red:\n  "
            + "\n  ".join(broken)
        )


def seed(
    db: DBSession,
    *,
    workspace_slug: str = DEFAULT_WORKSPACE_SLUG,
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
    seed_value: int = 20260825,
    skip_runs: bool = False,
    skip_radio: bool = False,
    refresh: bool = False,
    reset_first: bool = False,
) -> dict[str, Any]:
    """The whole demo, in the order the story needs it to exist.

    Ordering matters. The two inline versions come before the Flow run so that
    the version the pipeline produces is the *third*, with two ancestors to be
    compared against; and the champion is left on **v1**, the interpretable
    baseline, so the demo has a promotion to perform whose delta is real —
    +0.024 ROC AUC, measured, not staged.
    """

    seed_skills_and_capabilities(db)
    workspace = ensure_workspace(db, workspace_slug, workspace_name)
    if reset_first:
        reset(db, workspace)

    datasets = ensure_datasets(db, workspace, seed=seed_value, refresh=refresh)
    history = seed_model_history(db, workspace, datasets["cleaned"])
    # The baseline serves. Promoting the boosted version is a demo beat, not a
    # seeding step: see ``seed_model_history``.
    champion = promote_if_nobody_has(db, workspace, history[0])

    features = [*CHURN_FEATURE_COLUMNS, *ENGINEERED_COLUMNS]
    churn_capability = ensure_capability(
        db,
        workspace,
        slug=CHURN_CAPABILITY_SLUG,
        name="Churn Radar",
        description=(
            "Cleans the subscriber master, derives the retention features, fits "
            "and evaluates a churn model, scores the base and briefs the "
            "segments at risk."
        ),
        skill_slugs=CHURN_SKILL_SLUGS,
        input_unit="subscriber_base",
        output_unit="retention_brief",
        value_per_outcome=42.0,
    )
    radio_capability = ensure_capability(
        db,
        workspace,
        slug=RADIO_CAPABILITY_SLUG,
        name="Radio Watch",
        description=(
            "Aggregates the hourly radio KPIs into a list of cells at risk of "
            "congestion, with a 7-day delta and blocking data tests."
        ),
        skill_slugs=RADIO_SKILL_SLUGS,
        input_unit="cell_kpi_series",
        output_unit="cell_watchlist",
        value_per_outcome=18.0,
    )

    churn_system = ensure_system(
        db,
        workspace,
        churn_capability,
        name=CHURN_SYSTEM_NAME,
        objective=(
            "Produce, every month, the list of subscribers at risk of leaving "
            "and the retention brief that goes with it."
        ),
        flow=churn_flow(
            raw_slug=datasets["raw"].slug,
            model_slug=champion.slug,
            features=features,
        ),
        system_type="churn_pipeline",
    )
    radio_system = ensure_system(
        db,
        workspace,
        radio_capability,
        name=RADIO_SYSTEM_NAME,
        objective=(
            "Publish the watchlist of radio cells congested at busy hour, with "
            "the data tests to back it."
        ),
        flow=radio_flow(network_slug=datasets["network"].slug),
        system_type="radio_watch",
    )

    runs: dict[str, Any] = {}
    if not skip_runs:
        runs["churn"] = run_system(db, workspace, churn_system)
        if not skip_radio:
            runs["radio"] = run_system(db, workspace, radio_system)
    assert_runs_are_green(runs)

    db.expire_all()
    versions = (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace.id, MLModel.slug == champion.slug)
        .order_by(MLModel.version.asc())
        .all()
    )
    serving = next((row for row in versions if row.is_champion), None)
    published = publish_and_mint(db, serving) if serving else {}

    # The desk comes last because it can only exist once the model has a Skill
    # slug: its AgentLoop names that slug in an allowlist, and an allowlist entry
    # the System has not bound is a graph the walker refuses.
    desk_system = None
    desk_slug = published_skill_slug(published)
    desk_skill = (
        db.query(Skill)
        .filter(Skill.slug == desk_slug, Skill.workspace_id == workspace.id)
        .first()
        if desk_slug
        else None
    )
    if serving is not None and desk_skill is None:
        # Silence here is how the desk went missing once already: the publish
        # returns the Skill nested under its key, so reading a slug off the
        # envelope yielded None, the branch below never opened, and a seed that
        # printed nothing but success left the demo a beat short.
        raise SystemExit(
            "the champion published no Skill the desk can call "
            f"(slug={desk_slug!r}) — the sixth beat would be missing"
        )
    if desk_skill is not None:
        desk_capability = ensure_capability(
            db,
            workspace,
            slug=DESK_CAPABILITY_SLUG,
            name="Churn Desk",
            description=(
                "Answers a retention question about one subscriber by scoring "
                "them with the published churn model and writing the verdict."
            ),
            skill_slugs=DESK_SKILL_SLUGS,
            input_unit="subscriber_question",
            output_unit="retention_verdict",
            value_per_outcome=6.0,
        )
        desk_system = ensure_system(
            db,
            workspace,
            desk_capability,
            name=DESK_SYSTEM_NAME,
            objective=(
                "Answer, for one subscriber at a time, whether retention should "
                "call them — with the model's number behind the advice."
            ),
            flow=desk_flow(predict_slug=desk_skill.slug),
            system_type="churn_desk",
            execution_mode="real_time_decision",
            extra_skill_ids=(desk_skill.id,),
        )
        if not skip_runs:
            runs["desk"] = run_system(
                db,
                workspace,
                desk_system,
                input_ref={"rows": [at_risk_subscriber(datasets["cleaned"])]},
            )
            assert_runs_are_green(runs)

    # The business page, last: it reads the scored table and the brief, so
    # everything it reads has to exist first. It is not run here — a board is
    # refreshed by the person looking at it, and a seeded run of it would put a
    # figure on the page that is one rehearsal old the moment anyone opens it.
    board_capability = ensure_capability(
        db,
        workspace,
        slug=BOARD_CAPABILITY_SLUG,
        name=BOARD_SYSTEM_NAME,
        description=(
            "Reads the scored subscriber base and the pipeline's last "
            "retention brief, and returns the counts, rates and revenue the "
            "business page shows."
        ),
        skill_slugs=BOARD_SKILL_SLUGS,
        input_unit="scored_base",
        output_unit="retention_board",
        value_per_outcome=0.0,
    )
    board_system = ensure_system(
        db,
        workspace,
        board_capability,
        name=BOARD_SYSTEM_NAME,
        objective=(
            "Answer, in one read, who is about to leave, what that is worth "
            "this month, and what the pipeline concluded about it."
        ),
        flow=board_flow(scored_slug=scored_slug()),
        system_type="retention_board",
        execution_mode="real_time_decision",
    )
    ensure_board_binding(db, workspace, board_system)
    board_experience = ensure_board_experience(db, workspace)

    return {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "datasets": {
            key: {"id": row.id, "slug": row.slug, "rows": row.row_count}
            for key, row in datasets.items()
        },
        "models": [
            {
                "id": row.id,
                "version": row.version,
                "algo": row.algo,
                "status": row.status,
                "champion": bool(row.is_champion),
                "metric": (row.metrics_json or {}).get("primary"),
            }
            for row in versions
        ],
        "systems": {
            "churn": churn_system.id,
            "radio": radio_system.id,
            "board": board_system.id,
            **({"desk": desk_system.id} if desk_system is not None else {}),
        },
        "runs": {key: value["status"] for key, value in runs.items()},
        "published": published,
        "work": {
            "slug": board_experience.slug,
            "binding_key": BOARD_BINDING_KEY,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default=DEFAULT_WORKSPACE_SLUG)
    parser.add_argument("--workspace-name", default=DEFAULT_WORKSPACE_NAME)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument(
        "--skip-runs",
        action="store_true",
        help="Seed the graphs without executing them (no run history, no badges).",
    )
    parser.add_argument(
        "--skip-radio",
        action="store_true",
        help="Skip the dbt run only; its first build pays for a dbt-duckdb venv.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Re-ingest and re-fit even when an identical dataset version and "
            "model version already exist, adding versions instead of reusing "
            "them. Off by default so a second rehearsal finds the state the "
            "first one left."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Remove the demo's own datasets and model versions, tear down the "
            "Retention Board page and its binding, and discard the Flow drafts "
            "on its own Systems, before seeding — so a re-seed replaces the "
            "previous incarnation instead of sitting beside it. Use it when "
            "the seeded copy has changed; it discards the champion promoted on "
            "stage and any graph edit left open in the Builder."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        summary = seed(
            db,
            workspace_slug=args.workspace_slug,
            workspace_name=args.workspace_name,
            seed_value=args.seed,
            skip_runs=args.skip_runs,
            skip_radio=args.skip_radio,
            refresh=args.refresh,
            reset_first=args.reset,
        )
    finally:
        db.close()

    print("")
    print(f"Nawa data demo ready on workspace {summary['workspace_slug']}")
    for row in summary["models"]:
        metric = row["metric"] or {}
        flag = " ← champion" if row["champion"] else ""
        print(
            f"  {MODEL_NAME} v{row['version']} ({row['algo']}): "
            f"{metric.get('key')}={metric.get('value')}{flag}"
        )
    secret = (summary.get("published") or {}).get("secret")
    if secret:
        print("")
        print("API key (shown once — copy it into the demo terminal now):")
        print(f"  {secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
