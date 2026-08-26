"""The Nawa demo generator and seed, pinned where the demo makes claims.

A demo that is rehearsed is a demo whose numbers are quoted out loud, so the
tests here are less about "does it run" than about the three properties the
rehearsal actually depends on:

* the data is a pure function of its seed, byte for byte, on any machine;
* the row counts the badges show (8 412 → 6 903) are arithmetic, not sampling;
* the model ranking the story tells is a fact about the data, not a decision the
  seed made about which fit to run last.

The last one is the reason the slow fit below is worth its runtime: "the boosted
trees beat the baseline" is a sentence said to a customer, and if a refactor of
the label ever quietly reverses it, the demo starts teaching the opposite lesson
with full confidence.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services.run_engine.execution_contract import resolve_flow_execution

from scripts.gen_nawa_telecom_data import (
    ARPU_SENTINEL,
    CELLS,
    CHURN_FEATURE_COLUMNS,
    CHURN_TARGET,
    CLEAN_ROWS,
    DEGRADING_CELLS,
    DUPLICATE_ROWS,
    NETWORK_ROWS,
    PRB_CEILING,
    RAW_ROWS,
    RECOVERING_CELLS,
    REGIONS,
    churn_raw_frame,
    clean_churn_frame,
    clean_churn_sql,
    describe,
    network_cell_frame,
)
from scripts.seed_nawa_data_demo import (
    CLEAN_DATASET_NAME,
    ENGINEERED_COLUMNS,
    MODEL_NAME,
    _reusable_dataset,
    _reusable_model,
    churn_flow,
    promote_if_nobody_has,
    radio_flow,
)

pl = pytest.importorskip("polars")
pytest.importorskip("duckdb")


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def raw():
    return churn_raw_frame()


@pytest.fixture(scope="module")
def cleaned(raw):
    return clean_churn_frame(raw)


def test_the_same_seed_gives_the_same_bytes(raw):
    """Rehearsability, stated as a property.

    Everything else the demo promises — that a badge reads 6 903, that the
    champion scores 0.835 — is downstream of this. Both frames, because the
    radio table is generated from a different offset of the same seed and a
    shared RNG is exactly the kind of thing that couples them by accident.
    """

    assert churn_raw_frame().equals(raw)
    assert network_cell_frame().equals(network_cell_frame())


def test_the_row_counts_the_badges_show_are_arithmetic(raw, cleaned):
    """8 412 → 6 903, and the drop is accounted for line by line.

    The three defect blocks are carved from one permutation so they cannot
    overlap; if they ever did, the cleaned count would drift and the number on
    the SQL node's badge would quietly become approximate.
    """

    assert raw.height == RAW_ROWS == 8_412
    assert cleaned.height == CLEAN_ROWS == 6_903
    assert network_cell_frame().height == NETWORK_ROWS == 24_192

    described = describe()
    assert described["churn_raw_rows"] == RAW_ROWS
    assert described["churn_clean_rows"] == CLEAN_ROWS
    # Every dropped row has exactly one named reason.
    dropped = RAW_ROWS - CLEAN_ROWS
    assert dropped == (
        described["churn_duplicates"]
        + described["churn_suspended"]
        + described["churn_missing_arpu"]
        + described["churn_sentinel_arpu"]
    )


def test_the_export_arrives_dirty_and_leaves_clean(raw, cleaned):
    """The cleaning node has to be earning its place on the canvas.

    Each assertion is one thing the demo says while pointing at the SQL: the
    regions were spelled four ways, the revenue column had holes and a ``-1``
    sentinel, and the same subscriber appeared twice with different snapshots.
    """

    # Dirty on the way in: more spellings than there are regions.
    assert raw["region"].n_unique() > len(REGIONS)
    assert raw["arpu_mad"].null_count() > 0
    assert raw["arpu_mad"].min() == ARPU_SENTINEL
    assert raw["msisdn"].n_unique() == RAW_ROWS - DUPLICATE_ROWS

    # Canonical on the way out.
    assert cleaned["region"].n_unique() == len(REGIONS)
    assert cleaned["region"].to_list() == [
        value.strip().lower() for value in cleaned["region"].to_list()
    ]
    assert cleaned["arpu_mad"].null_count() == 0
    assert cleaned["arpu_mad"].min() >= 0
    # One row per subscriber, and it is the most recent snapshot that survived.
    assert cleaned["msisdn"].n_unique() == cleaned.height
    assert "line_status" not in cleaned.columns

    # A hole the model must tolerate, not a defect the cleaning removes: the
    # two are different, and conflating them is how a pipeline silently drops
    # a fifth of its rows.
    assert cleaned["nps"].null_count() > 0


def test_the_target_is_a_plausible_churn_rate(cleaned):
    rate = float(cleaned[CHURN_TARGET].mean())
    assert 0.20 <= rate <= 0.24, rate
    assert set(cleaned[CHURN_TARGET].unique().to_list()) == {0, 1}


def test_survey_non_response_carries_signal(cleaned):
    """The hole is not random, and the demo's model families differ on it.

    A subscriber on the way out is the one who stops answering surveys. This is
    the mechanism the boosted trees can read (a missing value is a branch) and
    the linear baseline cannot (it is imputed away before the fit sees it), so
    it is load-bearing for the ranking below rather than colour.
    """

    silent = cleaned.filter(pl.col("nps").is_null())
    answered = cleaned.filter(pl.col("nps").is_not_null())
    assert silent.height > 500
    assert float(silent[CHURN_TARGET].mean()) > float(answered[CHURN_TARGET].mean()) + 0.10


def test_the_cleaning_statement_is_the_one_the_node_carries():
    """One statement, two callers. Two copies would drift on the first edit.

    The exact-count claim is a property of *this* SQL over *that* generator, so
    the seeded node's parameters and the frame these tests clean have to come
    from the same function.
    """

    statement = clean_churn_sql("clients")
    node = next(
        item
        for item in churn_flow(raw_slug="raw", model_slug="m", features=["a"])["nodes"]
        if item["id"] == "task.clean"
    )
    assert node["config"]["params"]["sql"] == statement
    # Ordered, because duckdb is parallel: without it the same seed trains on a
    # different sample every run and the quoted metrics stop being reproducible.
    assert "ORDER BY msisdn" in statement


def test_the_radio_table_has_a_busy_hour_and_cells_that_degrade():
    """What gives the dbt node something true to assert.

    A watchlist model over a flat table would be arithmetic with no answer in
    it: the mart buckets a busy hour and compares two weeks, so both have to
    exist in the data before the node means anything.
    """

    frame = network_cell_frame()
    assert frame.height == NETWORK_ROWS
    assert frame["cell_id"].n_unique() == CELLS

    by_hour = (
        frame.with_columns(pl.col("ts").dt.hour().alias("hour"))
        .group_by("hour")
        .agg(pl.col("prb_utilization_pct").mean().alias("prb"))
        .sort("prb", descending=True)
    )
    # The evening streaming peak is the busy hour the mart filters on (19h–23h).
    assert by_hour["hour"][0] in range(19, 24)

    # A congested tail: the mart's 'critical' band has to have members.
    busy = frame.filter(pl.col("ts").dt.hour().is_between(19, 23))
    per_cell = busy.group_by("cell_id").agg(
        pl.col("prb_utilization_pct").mean().alias("prb")
    )
    assert per_cell.filter(pl.col("prb") >= 85).height >= 1
    # And saturation has to cost something, or the KPIs are decoration.
    hot = busy.filter(pl.col("prb_utilization_pct") >= 85)
    calm = busy.filter(pl.col("prb_utilization_pct") <= 40)
    assert float(hot["latency_ms"].mean()) > float(calm["latency_ms"].mean())
    assert float(hot["drop_call_rate_pct"].mean()) > float(calm["drop_call_rate_pct"].mean())


def test_utilisation_saturates_instead_of_piling_up_on_the_ceiling():
    """No cell-hour reports exactly 100%, and that is load-bearing.

    A clipped counter parks a large share of the busy hours on the ceiling, and
    a week-over-week delta over a constant is zero — so the cells moving fastest
    are the ones the trend column goes blind to. The whole point of the radio
    node is that it sees them, so "nothing touches the ceiling" is a property of
    the data the demo depends on, not a cosmetic bound.
    """

    prb = network_cell_frame()["prb_utilization_pct"]
    assert float(prb.max()) < PRB_CEILING
    assert prb.filter(prb >= PRB_CEILING - 0.05).len() == 0
    # Still reaching well into congestion, or there would be nothing to flag.
    assert 88.0 <= float(prb.max()) < 99.0, float(prb.max())

    # The counters a base station reports are bounded by what it serves, so no
    # cell-hour claims a thousand sessions or a small factory's worth of power.
    frame = network_cell_frame()
    assert int(frame["active_users"].max()) < 1_000
    assert float(frame["energy_kwh"].max()) < 5.0
    assert float(frame["handover_success_pct"].min()) > 90.0


def _watchlist():
    """The Radio Watch mart, run over the generator with duckdb.

    The seeded node's SQL rather than a paraphrase of it: the claims below are
    about the table the demo puts on screen, and a second copy of this logic in
    the tests would agree with the node only until the first edit. Rendering the
    two dbt refs by hand is the whole of what the adapter would do here, and it
    buys the statement being checked as valid duckdb on every run — which is
    otherwise only true once a recipe worker has executed the node.
    """

    import duckdb

    from scripts.seed_nawa_data_demo import RADIO_MODELS

    staging, mart = RADIO_MODELS
    assert (staging["name"], mart["name"]) == ("stg_cell_hourly", "mart_cell_risk")

    connection = duckdb.connect()
    try:
        connection.register("input", network_cell_frame().to_arrow())
        connection.execute(
            "create view stg_cell_hourly as "
            + staging["sql"].replace("{{ source('inputs', 'input') }}", "input")
        )
        return connection.execute(
            mart["sql"].replace("{{ ref('stg_cell_hourly') }}", "stg_cell_hourly")
        ).pl()
    finally:
        connection.close()


def test_the_watchlist_separates_standing_problems_from_new_ones():
    """The table the demo reads out loud, asserted as the demo reads it.

    Two claims, and they are the argument for the node existing. First, the
    ``critical`` band is a shortlist an engineer could actually work — a
    watchlist naming a third of the fleet is a report nobody opens. Second, the
    delta column separates the cells that just broke from the ones that have
    been broken for months, by a margin wide enough to point at on stage.
    """

    watchlist = _watchlist()
    assert watchlist.height == CELLS
    assert watchlist["cell_id"].n_unique() == CELLS  # the mart's `unique` test
    assert set(watchlist["risk_band"].unique()) <= {"critical", "watch", "healthy"}

    critical = watchlist.filter(pl.col("risk_band") == "critical")
    assert DEGRADING_CELLS < critical.height <= CELLS // 6, critical.height
    assert watchlist.filter(pl.col("risk_band") == "healthy").height > CELLS // 2

    # The movers, and the gap between them and the noise floor of the column.
    climbing = watchlist.sort("prb_pct_delta", descending=True)
    moved = climbing["prb_pct_delta"].to_list()
    assert all(value > 12.0 for value in moved[:DEGRADING_CELLS]), moved[:5]
    assert moved[DEGRADING_CELLS] < 5.0, moved[: DEGRADING_CELLS + 1]

    # Each of them was inside the healthy band a fortnight ago, which is what
    # makes the trend worth reading rather than a restatement of the level.
    for row in climbing.head(DEGRADING_CELLS).iter_rows(named=True):
        assert row["prb_pct"] - row["prb_pct_delta"] < 70.0, row
        # And the congestion cost the subscriber something, or it is arithmetic.
        assert row["drop_pct_delta"] > 0.4, row

    # It reads in both directions: the relieved cells are why an operator
    # believes the column at all.
    assert climbing["prb_pct_delta"].to_list()[-RECOVERING_CELLS] < -8.0

    # Nothing is stuck: a ceiling would show up here as a run of flat deltas.
    flat = watchlist.filter(pl.col("prb_pct_delta").abs() < 0.01).height
    assert flat <= 4, flat


@pytest.mark.slow
def test_the_boosted_trees_beat_the_baseline_because_the_world_is_not_additive(cleaned):
    """The demo's promotion beat, as a measured fact.

    "We promoted the boosted version and the metric moved" is a sentence said to
    a customer. It is true here because churn is generated with interactions and
    informative non-response, neither of which a logistic regression can
    represent — not because the boosted fit was given more columns or run last.
    Same 20 columns, same split, same seed; only the estimator differs.

    The band is deliberately wide: this pins the *ordering* and the rough size
    of the gap, not a metric to six decimals, so an sklearn upgrade that shifts
    a fit slightly does not fail the suite for the wrong reason.
    """

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from skrub import TableVectorizer

    frame = cleaned.to_pandas()
    features = frame[list(CHURN_FEATURE_COLUMNS)]
    target = frame[CHURN_TARGET]
    x_train, x_test, y_train, y_test = train_test_split(
        features, target, test_size=0.25, random_state=42, stratify=target
    )

    def auc(*steps) -> float:
        pipeline = make_pipeline(*steps)
        pipeline.fit(x_train, y_train)
        return float(roc_auc_score(y_test, pipeline.predict_proba(x_test)[:, 1]))

    baseline = auc(
        TableVectorizer(),
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(max_iter=1000, random_state=42),
    )
    boosted = auc(
        TableVectorizer(),
        HistGradientBoostingClassifier(
            max_iter=220, learning_rate=0.08, random_state=42
        ),
    )

    # Worth showing, and not so good that the room suspects a leak.
    assert 0.80 <= baseline <= 0.88, baseline
    assert 0.82 <= boosted <= 0.90, boosted
    # The gap the demo reads out loud, in the direction it reads it.
    assert boosted > baseline + 0.010, (baseline, boosted)


# ---------------------------------------------------------------------------
# The seeded Flow graphs
# ---------------------------------------------------------------------------


def test_the_seeded_flows_route_to_a_walker_that_can_configure_them():
    """A data-plane Flow has exactly one walker that can run it.

    The statement, the script, the training spec and the model reference are all
    graph-owned configuration, injected only by the DAG walker. Routed to the
    sequential one, every node in both of these graphs would refuse for want of
    configuration the graph was holding all along — so this is the difference
    between a demo that runs and a canvas of red nodes.
    """

    churn = churn_flow(raw_slug="raw-slug", model_slug="model-slug", features=["arpu_mad"])
    radio = radio_flow(network_slug="net-slug")
    for flow in (churn, radio):
        resolution = resolve_flow_execution(flow)
        assert resolution.runtime_mode == "dag_overlay", resolution
        assert resolution.reason == "graph_owned_config_requires_compatibility_dag"


def test_the_scoring_node_is_fed_by_both_the_fit_and_the_feature_table():
    """The diamond is deliberate: a model reference carries no rows.

    The fit upstream is what makes the scoring node wait for a model; the
    feature table beside it is what actually gets scored. Drop either edge and
    the node either scores nothing or scores the wrong table.
    """

    flow = churn_flow(raw_slug="raw", model_slug="m", features=["arpu_mad"])
    into_score = {edge["from"] for edge in flow["edges"] if edge["to"] == "task.score"}
    assert into_score == {"task.train", "task.features"}

    # And the chain before it is the one the demo narrates, in order.
    edges = {(edge["from"], edge["to"]) for edge in flow["edges"]}
    assert {
        ("src", "task.clean"),
        ("task.clean", "task.features"),
        ("task.features", "task.train"),
        ("task.score", "task.brief"),
        ("task.brief", "sink"),
    } <= edges


def test_the_training_node_asks_for_the_columns_the_feature_node_derives():
    """The two are written apart and have to agree.

    The Polars script adds columns; the training node lists its features
    explicitly rather than discovering them. A column renamed on one side and
    not the other fails the run with ``ML_FEATURE_UNKNOWN`` — which is exactly
    how this was found the first time.
    """

    from scripts.seed_nawa_data_demo import FEATURE_CODE

    for column in ENGINEERED_COLUMNS:
        assert f'alias("{column}")' in FEATURE_CODE, column

    features = [*CHURN_FEATURE_COLUMNS, *ENGINEERED_COLUMNS]
    node = next(
        item
        for item in churn_flow(raw_slug="r", model_slug="m", features=features)["nodes"]
        if item["id"] == "task.train"
    )
    assert node["config"]["params"]["features"] == features
    assert node["config"]["params"]["target"] == CHURN_TARGET


# ---------------------------------------------------------------------------
# The specification a manual rebuild is checked against
# ---------------------------------------------------------------------------


def test_the_rebuild_specification_quotes_the_figures_the_data_actually_has():
    """``PAPAI-MIRROR.md`` is a contract, and this is what keeps it one.

    That note tells an operator how to rebuild this use case by hand on another
    platform and which numbers to land on. Prose cannot be trusted to follow the
    generator, so the note quotes ``scripts.papai_mirror_facts`` and this test
    pins what that script reports — every figure in the note's acceptance
    checklist that does not require a fit.

    The fits themselves are pinned by
    ``test_the_boosted_trees_beat_the_baseline_because_the_world_is_not_additive``,
    on the ordering rather than the decimals, for the reason given there.
    """

    from scripts.papai_mirror_facts import facts

    body = facts()

    assert body["raw_export"] == {
        "rows": 8_412,
        "columns": 24,
        "distinct_subscribers": 8_000,
        "duplicate_rows": 412,
        # Seven regions, four spellings each; three plans, upper- and lower-cased.
        "region_spellings": 28,
        "plan_spellings": 6,
        # Higher than the defect blocks carved out of the 8 000 canonical rows,
        # because the 412 stale re-exports inherit their original's defects. The
        # dedup takes them first, which is why the cleaned count is still exact.
        "suspended_rows": 677,
        "arpu_null_rows": 310,
        "arpu_sentinel_rows": 170,
        "nps_null_rows": 1_383,
        "churn_rate": 0.2218,
    }
    assert body["cleaned_base"] == {
        "rows": 6_903,
        "columns": 22,
        "regions": 7,
        "plans": 3,
        "churn_rate": 0.2216,
        "churn_positives": 1_530,
        # The hole the model has to tolerate: 16.6% of the base, and the note
        # warns twice against cleaning it away.
        "nps_null_rows": 1_144,
    }
    assert body["feature_table"]["rows"] == 6_903
    assert body["feature_table"]["columns"] == 31
    assert body["feature_table"]["training_columns"] == 29
    assert body["feature_table"]["tenure_bands"] == {
        "established": 1_291,
        "loyal": 5_183,
        "new": 429,
    }
    assert body["radio_kpis"]["rows"] == 24_192
    assert body["radio_kpis"]["cells"] == 72
    # A clipped counter would put a wall of busy hours on exactly 100.0 and zero
    # the delta of the cells the watchlist exists to surface.
    assert body["radio_kpis"]["hours_at_the_ceiling"] == 0
    assert body["watchlist"]["rows"] == 72
    assert body["watchlist"]["columns"] == 13
    assert body["watchlist"]["bands"] == {"critical": 9, "healthy": 55, "watch": 8}
    assert body["watchlist"]["climbers_above_20_points"] == DEGRADING_CELLS == 3
    assert body["watchlist"]["fallers_below_minus_10_points"] == RECOVERING_CELLS == 2
    # The split every quoted metric was measured on.
    assert body["split"] == {"test_size": 0.25, "random_state": 42}


def test_the_rebuild_specification_reads_the_pipeline_the_demo_runs():
    """The note's helpers must be the pipeline's own code, not a copy of it.

    The whole claim of ``papai_mirror_facts`` is that it cannot disagree with
    what the Flow executes: it runs the node's Polars script and the node's dbt
    SQL. So the frames it hands back have to carry the columns those two
    produce — which is what a re-implementation would quietly stop doing.
    """

    from scripts.papai_mirror_facts import feature_frame, watchlist_frame

    features = feature_frame(clean_churn_frame())
    for column in ENGINEERED_COLUMNS:
        assert column in features.columns, column

    watchlist = watchlist_frame(network_cell_frame())
    assert {"prb_pct", "prb_pct_delta", "drop_pct_delta", "risk_band"} <= set(
        watchlist.columns
    )
    # One row per cell: the mart's own uniqueness test, asserted here too because
    # the note tells the operator to reproduce it.
    assert watchlist["cell_id"].n_unique() == watchlist.height == CELLS


# ---------------------------------------------------------------------------
# Re-running the seed
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Nawa",
        slug=f"nawa-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


def _dataset(db_session, workspace, *, name, version, rows, status="ready"):
    row = TabularDataset(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=name,
        slug="subscriber-base-cleaned",
        version=version,
        status=status,
        row_count=rows,
        column_count=20,
        source="upload",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _model(db_session, workspace, *, version, algo, features, dataset, status="ready"):
    row = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=MODEL_NAME,
        slug="churn-radar",
        version=version,
        task="classification",
        algo=algo,
        target=CHURN_TARGET,
        features=list(features),
        status=status,
        dataset_id=dataset.id,
        dataset_slug=dataset.slug,
        row_count=dataset.row_count,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_a_rerun_anchors_on_the_version_the_seed_itself_created(db_session, workspace):
    """The Flow cleans the base too, so "latest" is the wrong anchor.

    After one run there are two ready ``Subscriber base — cleaned`` versions with
    identical row counts: the seed's, and the Churn Radar Flow's. Reaching for
    the newest moved the anchor onto the Flow's output, whose id no longer
    matched the dataset the seeded models were fitted against — so the models
    looked absent, were retrained, and a second rehearsal opened on a Models
    page of duplicates with a freshly demoted champion.
    """

    mine = _dataset(db_session, workspace, name=CLEAN_DATASET_NAME, version=1, rows=CLEAN_ROWS)
    _dataset(db_session, workspace, name=CLEAN_DATASET_NAME, version=2, rows=CLEAN_ROWS)

    found = _reusable_dataset(
        db_session, workspace, name=CLEAN_DATASET_NAME, rows=CLEAN_ROWS
    )
    assert found is not None and found.id == mine.id

    # A different shape is a different dataset: a changed generator has to mint
    # a new version rather than silently reuse the old one.
    assert (
        _reusable_dataset(db_session, workspace, name=CLEAN_DATASET_NAME, rows=999)
        is None
    )
    # And an unfinished ingest is not a reusable one.
    assert _reusable_dataset(db_session, workspace, name="absent", rows=None) is None


def test_a_rerun_reuses_a_fit_of_the_same_estimator_over_the_same_columns(
    db_session, workspace
):
    """Refitting would mint a byte-identical model under a new version number.

    Matched on the estimator, the column list and the dataset row together,
    because all three are what make a fit the same fit. A pending or failed row
    is not a reusable one — it has no artifact behind it.
    """

    dataset = _dataset(
        db_session, workspace, name=CLEAN_DATASET_NAME, version=1, rows=CLEAN_ROWS
    )
    base = list(CHURN_FEATURE_COLUMNS)
    fitted = _model(
        db_session, workspace, version=1, algo="linear", features=base, dataset=dataset
    )

    assert (
        _reusable_model(
            db_session, workspace, algo="linear", features=base, dataset=dataset
        ).id
        == fitted.id
    )
    # A different estimator, or a different feature list, is a different model.
    assert (
        _reusable_model(
            db_session,
            workspace,
            algo="gradient_boosting",
            features=base,
            dataset=dataset,
        )
        is None
    )
    assert (
        _reusable_model(
            db_session,
            workspace,
            algo="linear",
            features=[*base, *ENGINEERED_COLUMNS],
            dataset=dataset,
        )
        is None
    )

    failed_dataset = _dataset(
        db_session, workspace, name=CLEAN_DATASET_NAME, version=2, rows=CLEAN_ROWS
    )
    _model(
        db_session,
        workspace,
        version=2,
        algo="linear",
        features=base,
        dataset=failed_dataset,
        status="failed",
    )
    assert (
        _reusable_model(
            db_session, workspace, algo="linear", features=base, dataset=failed_dataset
        )
        is None
    )


def test_a_rerun_leaves_the_promotion_the_rehearsal_performed(db_session, workspace):
    """The one piece of demo state an operator changes by hand.

    Promoting the challenger is a beat of the demo. A seed that re-promoted its
    own baseline would undo it, so the seed decides what serves only when
    nothing does.
    """

    dataset = _dataset(
        db_session, workspace, name=CLEAN_DATASET_NAME, version=1, rows=CLEAN_ROWS
    )
    base = list(CHURN_FEATURE_COLUMNS)
    baseline = _model(
        db_session, workspace, version=1, algo="linear", features=base, dataset=dataset
    )
    challenger = _model(
        db_session,
        workspace,
        version=2,
        algo="gradient_boosting",
        features=base,
        dataset=dataset,
    )

    # Nothing serves yet: the seed puts its baseline in.
    assert promote_if_nobody_has(db_session, workspace, baseline).id == baseline.id
    db_session.refresh(baseline)
    assert baseline.is_champion is True

    # The rehearsal promotes the challenger by hand...
    baseline.is_champion = False
    challenger.is_champion = True
    db_session.commit()

    # ...and the next seed leaves it alone.
    assert promote_if_nobody_has(db_session, workspace, baseline).id == challenger.id
    db_session.refresh(baseline)
    assert baseline.is_champion is False
