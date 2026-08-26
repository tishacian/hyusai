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
CHURN_CAPABILITY_SLUG = "nawa_churn_radar"
RADIO_CAPABILITY_SLUG = "nawa_radio_watch"
API_KEY_NAME = "Nawa demo"

CHURN_SKILL_SLUGS = [
    "sql_transform_v1",
    "polars_transform_v1",
    "ml_train_sklearn_v1",
    "ml_batch_score_v1",
    "ml_predict_v1",
    "azure_llm_v1",
]
RADIO_SKILL_SLUGS = ["dbt_transform_v1"]

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
    "prediction, confidence, score_churn), write an English brief of at most "
    "8 lines for the retention committee: the three segments most at risk, the "
    "estimated monthly revenue at stake, and one retention action per segment. "
    "Quote figures, not generalities."
)


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
    for slug_ in (*CHURN_SKILL_SLUGS, *RADIO_SKILL_SLUGS):
        if slug_ not in enabled:
            enabled.append(slug_)
    catalog["enabled_skills"] = enabled
    settings["catalog"] = catalog
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
) -> System:
    """Upsert one System by name and reconcile its published Flow."""

    payload = {
        "objective": objective,
        "capability_id": capability.id,
        "skill_ids": list(capability.skill_ids or []),
        "flow_definition": flow,
        "settings": {
            "nawa_data_demo": True,
            "surface": "system",
            "system_type": system_type,
            "brand": "Nawa",
        },
        # Canonical vocabulary, enforced by ``ck_systems_execution_mode``: these
        # pipelines run over a whole subscriber base on a schedule, not per
        # request.
        "execution_mode": "batch_processing",
        "execution_profile": {"nawa_data_demo": True, "persona": "data_scientist"},
        "coordination_pattern": "graph",
        "status": "active",
        "created_by": SEED_ACTOR,
        "default_prompt_type": "factual",
        "default_model": "gpt-4o-mini",
        "retrieval_mode_default": "hybrid",
    }
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
        flow_publication.reconcile_system_flow(
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


def run_system(db: DBSession, workspace: Workspace, system: System) -> dict[str, Any]:
    """Execute one seeded System through the DAG walker and report per node.

    Through the engine rather than by writing checkpoints by hand: the canvas
    badges read ``node_end`` frames produced from real output envelopes, and a
    seed that authored them itself would prove nothing about the pipeline.
    """

    from app.services.run_engine.dag import execute_run_dag

    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        input_ref={},
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

    The two Systems are **not** removed, and that is the point: ``ensure_system``
    already reconciles their graph, so a re-seed rewrites the node labels in
    place and the run history behind them survives. What has to go is what the
    seed can only ever add to.

    Models go first: a version holds a foreign key to the table it was fitted
    on, and ``delete_model`` is what also clears the API key, the registry
    version and the published Skill that must not outlive it.
    """

    from app.services.tabular_datasets import soft_delete
    from app.services.tabular_ml import delete_model

    tally = {"models": 0, "datasets": 0}

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

    print("reset: {models} model versions, {datasets} datasets".format(**tally))
    return tally


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

STAGES = ("workspace", "datasets", "models", "systems", "runs", "publish")


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

    db.expire_all()
    versions = (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace.id, MLModel.slug == champion.slug)
        .order_by(MLModel.version.asc())
        .all()
    )
    serving = next((row for row in versions if row.is_champion), None)
    published = publish_and_mint(db, serving) if serving else {}

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
        "systems": {"churn": churn_system.id, "radio": radio_system.id},
        "runs": {key: value["status"] for key, value in runs.items()},
        "published": published,
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
            "Remove the demo's own datasets, model versions, Systems and runs "
            "before seeding, so a re-seed replaces the previous incarnation "
            "instead of sitting beside it. Use it when the seeded copy has "
            "changed; it discards the champion promoted on stage."
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
