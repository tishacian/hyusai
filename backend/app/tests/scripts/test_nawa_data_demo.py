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

The Retention Board sections at the foot of the file are the same discipline
applied to the business page. Every figure it shows is a claim somebody in the
room will challenge, so they are tested as arithmetic over a frame built by
hand — and the page itself is tested as a document, because a tile bound to a
path the System does not produce renders blank rather than failing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.capability import Capability
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services.systems import flow_publication
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
    BOARD_ACCESS_POLICY,
    BOARD_ACTION_ID,
    BOARD_BINDING_KEY,
    BOARD_CAPABILITY_SLUG,
    BOARD_CODE,
    BOARD_COLUMNS,
    BOARD_EXPERIENCE_NAME,
    BOARD_EXPERIENCE_SLUG,
    BOARD_I18N,
    BOARD_OUTPUT_SCHEMA,
    BOARD_SKILL_SLUGS,
    BOARD_SYSTEM_NAME,
    CHURN_SYSTEM_NAME,
    CLEAN_DATASET_NAME,
    ENGINEERED_COLUMNS,
    MODEL_NAME,
    SEED_ACTOR,
    DESK_SYSTEM_NAME,
    _reusable_dataset,
    _reusable_model,
    assert_runs_are_green,
    board_document,
    board_flow,
    board_main,
    churn_flow,
    desk_flow,
    ensure_board_binding,
    ensure_board_experience,
    ensure_capability,
    ensure_system,
    ensure_workspace,
    pick_at_risk,
    promote_if_nobody_has,
    published_skill_slug,
    radio_flow,
    reset,
    scored_slug,
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


def test_the_desk_can_reach_the_published_model_and_nothing_else():
    """The agentic half of the demo, and the reason it is not decoration.

    The catalog the planner sees is the node's allowlist, and the walker refuses
    any slug on it the System has not bound. So the two things worth pinning are
    that the published Skill is *on* the list — otherwise the agent has no way
    to reach the model and the beat is a mock — and that the list stops there.
    """

    slug = "ws.7f3a.predict_churn_radar"
    flow = desk_flow(predict_slug=slug)
    loop = next(node for node in flow["nodes"] if node["kind"] == "agent_loop")

    assert loop["config"]["skill_allowlist"] == [slug, "azure_llm_v1"]
    # Read-only: neither skill writes, so nothing pauses on a human gate mid-demo.
    assert loop["config"]["privilege_tier"] == "recommend"
    # And the loop is not finished until the model has actually answered.
    assert loop["config"]["goal"]["done_when"] == [slug]
    assert loop["config"]["budget"]["max_turns"] <= 4

    edges = {(edge["from"], edge["to"]) for edge in flow["edges"]}
    assert edges == {("src", "loop.desk"), ("loop.desk", "sink")}


def test_the_desk_is_walked_by_the_engine_that_knows_agent_loops():
    """Routed to the sequential runtime, the loop node would never turn."""

    resolution = resolve_flow_execution(desk_flow(predict_slug="ws.a.predict_x"))
    assert resolution.runtime_mode == "dag_overlay", resolution


def test_the_desk_finds_the_slug_where_the_publish_actually_puts_it():
    """The seam the desk hangs off, and the one that already gave way once.

    ``publish_and_mint`` returns the Skill *beside* the API key rather than
    being it, so a caller reaching for ``slug`` on the envelope reads ``None``
    and the desk — conditional on that lookup — is skipped in silence by a run
    that otherwise reports success. Nothing about the desk's own shape catches
    this, which is why the reader is a named function with a test rather than a
    subscript at the call site.
    """

    envelope = {
        "skill": {"slug": "ws.7f3a.predict_churn_radar", "name": "Predict · Churn Radar"},
        "api_key_prefix": "ak_live_1234",
        "secret": None,
    }
    assert published_skill_slug(envelope) == "ws.7f3a.predict_churn_radar"

    # The shapes a caller must not mistake for an answer. Each one used to be,
    # or would be, an empty string — never an exception the seed cannot explain.
    assert published_skill_slug({"slug": "ws.7f3a.predict_churn_radar"}) == ""
    assert published_skill_slug({"skill": None}) == ""
    assert published_skill_slug({"skill": {}}) == ""
    assert published_skill_slug({}) == ""
    assert published_skill_slug(None) == ""


def test_the_desk_is_asked_about_a_subscriber_the_model_will_accept(cleaned):
    """The row rides in on the run input, and the contract is closed.

    An AgentLoop hands the skill it picked the envelope it already has, so the
    model's twenty columns have to be *there* — the planner is choosing a tool,
    not inventing feature values. Reading the row out of the cleaned table is
    what makes that true by construction rather than by careful typing.
    """

    asked = pick_at_risk(cleaned)

    assert set(asked) == set(CHURN_FEATURE_COLUMNS)
    # JSON is what ``Run.input_ref`` is, so nothing exotic may ride in it.
    for name, value in asked.items():
        assert value is None or isinstance(value, (str, int, float, bool)), (name, value)
    # And it is a subscriber the demo can tell a story about, every re-seed.
    assert asked["plan"] == "prepaid"
    assert asked["support_tickets"] >= 3
    assert pick_at_risk(cleaned) == asked


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


@pytest.mark.slow
def test_the_rebuild_specification_quotes_a_metric_table_this_split_can_produce():
    """The note's §A4.3 table, checked against the split it claims to come from.

    A metric table is the easiest thing in a specification to get wrong, because
    a stale figure is still a plausible figure: nothing about ``0.448485`` looks
    false. But the test split holds 383 positives, so every recall it can
    produce is a multiple of 1/383 — and that one arithmetic fact is enough to
    reject a number copied from a run over other bytes, which is exactly the
    defect this test was written after finding.

    Decimals are pinned loosely, for the reason given in
    ``test_the_boosted_trees_beat_the_baseline_because_the_world_is_not_additive``:
    an sklearn upgrade may move a fit, and the ordering is the claim. The
    *widths* and the *counts* are pinned exactly, because those are properties
    of the pipeline's shape rather than of its arithmetic.
    """

    from scripts.papai_mirror_facts import facts

    body = facts(with_fits=True)["fits"]
    v1 = body["v1_linear_20_columns"]
    v2 = body["v2_gradient_boosting_20_columns"]
    v3 = body["v3_gradient_boosting_29_columns"]

    for version in (v1, v2, v3):
        assert version["train_rows"] == 5_177
        assert version["test_rows"] == 1_726
        assert version["test_positives"] == 383
        # The check that catches a figure measured somewhere else.
        assert (version["recall"] * 383) == pytest.approx(
            round(version["recall"] * 383), abs=1e-3
        ), version["recall"]

    # The linear path one-hots and then appends the imputer's missingness
    # indicator; the trees do neither, and keep the columns they were given.
    assert (v1["input_columns"], v1["encoded_columns"], v1["fitted_columns"]) == (
        20,
        32,
        33,
    )
    assert (v2["input_columns"], v2["encoded_columns"], v2["fitted_columns"]) == (
        20,
        20,
        20,
    )
    assert (v3["input_columns"], v3["encoded_columns"], v3["fitted_columns"]) == (
        29,
        29,
        29,
    )

    # The promotion beat: the boosted trees rank better and are better
    # calibrated, which is the pair of facts the demo reads out loud.
    assert v2["roc_auc"] > v3["roc_auc"] > v1["roc_auc"]
    for metric in ("roc_auc", "accuracy", "precision", "recall"):
        assert v2[metric] > v1[metric], metric
    for metric in ("log_loss", "brier_score"):
        assert v2[metric] < v1[metric], metric

    documented = {
        "v1_linear_20_columns": {
            "roc_auc": 0.836610,
            "accuracy": 0.833720,
            "precision": 0.698347,
            "recall": 0.441253,
            "log_loss": 0.389011,
            "brier_score": 0.121770,
        },
        "v2_gradient_boosting_20_columns": {
            "roc_auc": 0.864133,
            "accuracy": 0.852260,
            "precision": 0.766667,
            "recall": 0.480418,
            "log_loss": 0.367198,
            "brier_score": 0.109443,
        },
        "v3_gradient_boosting_29_columns": {
            "roc_auc": 0.853761,
            "accuracy": 0.853998,
            "precision": 0.763052,
            "recall": 0.496084,
            "log_loss": 0.375591,
            "brier_score": 0.111910,
        },
    }
    for version, table in documented.items():
        for metric, value in table.items():
            assert body[version][metric] == pytest.approx(value, abs=0.002), (
                version,
                metric,
            )

    score = body["batch_score_with_v1_serving"]
    assert score["rows"] == 6_903
    assert score["columns_after_scoring"] == 34
    assert score["appended"] == ["prediction", "confidence", "score_1"]
    assert score["riskiest_decile_rows"] == 690
    # Read off a threshold and a decile edge, so the note calls them
    # approximate and so does this.
    assert 950 <= score["flagged"] <= 1_050, score["flagged"]
    assert score["lift_over_base_rate"] == pytest.approx(3.5, abs=0.2)


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


# ---------------------------------------------------------------------------
# A re-seed that changes the graph
# ---------------------------------------------------------------------------


def _system(db_session, workspace, *, name, flow, created_by=SEED_ACTOR):
    row = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=name,
        objective="seeded",
        flow_definition=flow,
        status="active",
        created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _draft(db_session, system, *, updated_by):
    row = SystemFlowDraft(
        system_id=system.id,
        workspace_id=system.workspace_id,
        flow_definition=system.flow_definition,
        revision=2,
        flow_sha256="0" * 64,
        updated_by=updated_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_a_reset_discards_the_draft_that_would_pin_the_retired_slugs(
    db_session, workspace
):
    """The draft is why a re-seed can run the graph the reset just invalidated.

    Reconciliation preserves a draft left open in the Builder, and the graph
    names its input by slug. Reset the datasets without resetting the draft and
    the next run resolves a slug that no longer exists. ``--reset`` owns the
    seed's own Systems; it owns nobody else's.
    """

    mine = _system(db_session, workspace, name=CHURN_SYSTEM_NAME, flow={"nodes": []})
    # The desk names the published Skill in its allowlist, and the reset revokes
    # that Skill with the model it belonged to — so a preserved draft here is the
    # same trap as on the pipelines, pointing at a slug that no longer resolves.
    desk = _system(db_session, workspace, name=DESK_SYSTEM_NAME, flow={"nodes": []})
    theirs = _system(
        db_session,
        workspace,
        name="Somebody else's pipeline",
        flow={"nodes": []},
        created_by="alice@acme.test",
    )
    _draft(db_session, mine, updated_by="thibaud@datategy.net")
    _draft(db_session, desk, updated_by="thibaud@datategy.net")
    _draft(db_session, theirs, updated_by="alice@acme.test")

    tally = reset(db_session, workspace)

    assert tally["drafts"] == 2
    assert (
        db_session.query(SystemFlowDraft).filter_by(system_id=mine.id).one_or_none()
        is None
    )
    assert (
        db_session.query(SystemFlowDraft).filter_by(system_id=desk.id).one_or_none()
        is None
    )
    assert (
        db_session.query(SystemFlowDraft).filter_by(system_id=theirs.id).one_or_none()
        is not None
    )


def test_the_seed_refuses_to_narrate_a_graph_the_engine_will_not_run(
    db_session, workspace, monkeypatch
):
    """The failure this replaces was silent, which is what made it expensive.

    ``reconcile_system_flow`` declining is a legitimate outcome — somebody's
    unsaved work outranks a re-seed. What is not legitimate is printing
    "system ready" afterwards, because the engine runs ``flow_definition`` and
    that is still the previous graph.
    """

    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug="churn-radar",
        name="Churn Radar",
        skill_ids=[],
    )
    db_session.add(capability)
    db_session.commit()

    stale = churn_flow(raw_slug="base-clients-export-brut", model_slug="c", features=[])
    system = _system(db_session, workspace, name=CHURN_SYSTEM_NAME, flow=stale)
    _draft(db_session, system, updated_by="thibaud@datategy.net")

    # Exactly what the VM did: the reconciler preserves the operator draft and
    # leaves the published mirror where it was.
    monkeypatch.setattr(
        flow_publication,
        "reconcile_system_flow",
        lambda *a, **k: flow_publication.FlowReconcileResult(
            status="operator_draft_preserved"
        ),
    )

    with pytest.raises(SystemExit) as raised:
        ensure_system(
            db_session,
            workspace,
            capability,
            name=CHURN_SYSTEM_NAME,
            objective="anything",
            flow=churn_flow(
                raw_slug="subscriber-base-raw-export", model_slug="c", features=[]
            ),
            system_type="churn_pipeline",
        )

    message = str(raised.value)
    assert "operator_draft_preserved" in message
    assert "thibaud@datategy.net" in message


def test_a_completed_run_with_a_failed_node_is_not_a_seeded_demo():
    """``completed`` is the walker's verdict on the graph, not on the demo."""

    green = {"churn": {"nodes": [{"node_id": "task.clean", "status": "completed"}]}}
    assert assert_runs_are_green(green) is None

    with pytest.raises(SystemExit) as raised:
        assert_runs_are_green(
            {
                "churn": {
                    "nodes": [
                        {"node_id": "task.clean", "status": "completed"},
                        {
                            "node_id": "task.features",
                            "status": "failed",
                            "error": "TRANSFORM_NO_INPUT",
                        },
                    ]
                }
            }
        )

    assert "task.features" in str(raised.value)
    assert "TRANSFORM_NO_INPUT" in str(raised.value)


# ---------------------------------------------------------------------------
# The Retention Board's payload
# ---------------------------------------------------------------------------


def _scored_rows(*, size: int = 40, arpu: float = 100.0) -> list[dict[str, object]]:
    """A scored base small enough to reason about by hand.

    Shaped the way ``ml_batch_score_v1`` shapes one — a ``score_1`` column, a
    ``prediction`` carrying the class label as text, and the ground-truth
    ``churn`` beside them — because the recipe reads the scoring node's output
    conventions, not a shape invented for the test.

    The msisdn is an integer here for the same reason it is one in the base:
    the generator writes it as digits, the CSV round-trip has nothing to infer
    from but digits, and the column comes back numeric. A fixture that quoted
    it would be testing a table the pipeline never produces.

    Scores descend with the index and churn is concentrated at the top, so the
    riskiest decile is a rate a reader can verify without running anything.
    """

    rows: list[dict[str, object]] = []
    for index in range(size):
        score = 1.0 - (index + 0.5) / size
        rows.append(
            {
                "msisdn": int(f"2126{index % 10}{index:06d}"),
                "region": "casablanca",
                "plan": "prepaid",
                "tenure_months": 6 + index,
                "arpu_mad": arpu + index,
                "churn": 1 if index < size // 5 else 0,
                "prediction": "1" if score >= 0.5 else "0",
                "score_1": score,
            }
        )
    return rows


def _board(rows, *, brief: str = "The pipeline's own words.") -> dict:
    return board_main()(
        {
            "scored": {
                "rows": rows,
                "model": {
                    "name": MODEL_NAME,
                    "version": 1,
                    "metric_key": "roc_auc",
                    "metric_value": 0.835,
                },
            },
            "system_run": {"found": True, "output": {"completion": brief}},
        }
    )


def test_the_board_counts_flagged_subscribers_the_way_the_model_flagged_them():
    """``subscribers_at_risk`` is the model's verdict, not the board's.

    The recipe never picks a threshold: it compares ``prediction`` against the
    class the score column is named for, which is how the scoring node itself
    decided. A board that re-thresholded would report a different population
    from the one the Models page and the watchlist agree on, and the first
    person to cross-check two pages would find the demo disagreeing with
    itself.
    """

    rows = _scored_rows(size=40)
    summary = _board(rows)["summary"]

    assert summary["base_size"] == 40
    assert summary["subscribers_at_risk"] == sum(
        1 for row in rows if row["prediction"] == "1"
    ) == 20
    # The class comes off the column name, so a base scored for another class
    # is read for that class rather than silently reported as nobody at risk.
    other = []
    for row in _scored_rows():
        swapped = dict(row)
        swapped["score_0"] = swapped.pop("score_1")
        swapped["prediction"] = "0"
        other.append(swapped)
    assert _board(other)["summary"]["subscribers_at_risk"] == 40


def test_the_board_shows_the_riskiest_decile_against_the_base_it_came_from():
    """Both rates, measured, and computed over the same base.

    The decile rate alone is the number a slide would quote and a sceptic would
    reject: without the base rate beside it, "31% of them churn" says nothing
    about whether the model found them or whether they were simply there. Both
    are observed outcomes from the ``churn`` column rather than predictions, so
    the gap between them is the model's ranking being right, not the model
    agreeing with itself.
    """

    rows = _scored_rows(size=40)
    summary = _board(rows)["summary"]

    # Eight of forty churned, all of them in the top eight by score, so the
    # riskiest four (a tenth of forty) are all churners.
    assert summary["base_churn_pct"] == 20.0
    assert summary["riskiest_decile_churn_pct"] == 100.0
    assert summary["riskiest_decile_churn_pct"] > summary["base_churn_pct"]

    # A base whose churn is unrelated to the ranking reports no lift, which is
    # the honest reading and the one a broken model would produce.
    flat = [{**row, "churn": index % 2} for index, row in enumerate(rows)]
    flat_summary = _board(flat)["summary"]
    assert flat_summary["riskiest_decile_churn_pct"] == flat_summary["base_churn_pct"]


def test_the_revenue_at_stake_is_arpu_weighted_by_the_predicted_probability():
    """The one figure on the page a committee will argue about.

    Recomputed here from the same rows rather than compared with a constant,
    because the point of the assertion is that the board's number *is* the
    arithmetic and not a figure someone typed. The label travels with it and
    has to say both halves out loud — measured revenue, modelled weighting —
    or the number reads as a booked loss.
    """

    rows = _scored_rows(size=40)
    board = _board(rows)
    expected = sum(
        round(row["arpu_mad"] * row["score_1"], 2)
        for row in rows
        if row["prediction"] == "1"
    )

    assert board["summary"]["revenue_at_stake_mad"] == pytest.approx(expected, abs=0.01)

    label = board["summary"]["revenue_at_stake_label"].lower()
    for phrase in ("one month", "arpu", "probability", "measured", "modelled"):
        assert phrase in label, phrase

    # Double every subscriber's revenue and the figure doubles: nothing about
    # it is carried in from the document or the docs.
    richer = _board(_scored_rows(size=40, arpu=200.0))
    assert richer["summary"]["revenue_at_stake_mad"] > board["summary"][
        "revenue_at_stake_mad"
    ]


def test_the_call_list_is_ordered_by_what_a_departure_would_cost():
    """Priority is money, not probability, and ties break the same way twice.

    A near-certain departure on a 40 MAD line is not the first call to make,
    so the table is sorted by revenue at stake. The msisdn breaks ties because
    a call list that reorders between two refreshes of the same table is one an
    operator stops trusting.
    """

    rows = _scored_rows(size=40)
    at_risk = _board(rows)["at_risk"]

    stakes = [entry["revenue_at_stake_mad"] for entry in at_risk]
    assert stakes == sorted(stakes, reverse=True)
    for entry in at_risk:
        assert entry["revenue_at_stake_mad"] == pytest.approx(
            round(entry["arpu_mad"] * entry["score"], 2), abs=0.01
        )
    # Capped: beyond a screenful the table stops being a call list.
    assert len(at_risk) == 20
    assert _board(rows)["at_risk"] == at_risk

    tied = [{**row, "arpu_mad": 100.0, "score_1": 0.9, "prediction": "1"} for row in rows]
    listed = [entry["msisdn"] for entry in _board(tied)["at_risk"]]
    assert listed == sorted(listed)


def test_the_bands_count_every_subscriber_exactly_once():
    """The chart is a partition of the base, or it is a misleading picture.

    Overlapping edges would double-count and a gap would lose subscribers; both
    render as a plausible bar chart. The labels are probability ranges rather
    than adjectives because they are run output, which travels unlocalised —
    "50-75%" reads the same in French, and "Critical" would not.
    """

    rows = _scored_rows(size=40)
    bands = _board(rows)["bands"]

    assert [band["label"] for band in bands] == ["0-25%", "25-50%", "50-75%", "75-100%"]
    assert sum(band["value"] for band in bands) == len(rows)
    assert all(band["value"] == 10 for band in bands)


def test_the_board_quotes_the_brief_and_says_so_when_there_is_none():
    """The brief is read, never regenerated.

    The whole claim of the block is that the page shows what the pipeline
    concluded. When the pipeline has concluded nothing — no run yet, or an LLM
    node that degraded without a key — the honest answer is to say so, because
    a board that invents a paragraph under the heading "what the pipeline
    concluded" is worse than a board with an empty one.
    """

    rows = _scored_rows(size=40)
    assert _board(rows, brief="Casablanca prepaid is the segment.")["brief"] == (
        "Casablanca prepaid is the segment."
    )

    empty = board_main()({"scored": {"rows": rows, "model": {}}, "system_run": {}})
    assert "has not produced one yet" in empty["brief"]
    # And the arithmetic still stands without it.
    assert empty["summary"]["base_size"] == 40


def test_the_board_refuses_a_table_it_was_not_written_against():
    """A silent zero is the failure mode worth spending an exception on.

    Rename the score column and every count on the page becomes a confident
    nought. Nothing about that looks broken from the outside, so the recipe
    fails the read instead — and an empty base is refused for the same reason.
    """

    with pytest.raises(ValueError, match="score_"):
        _board([{"msisdn": "0600", "arpu_mad": 10.0, "churn": 0, "prediction": "1"}])
    with pytest.raises(ValueError, match="empty"):
        _board([])


def test_the_board_returns_the_shape_its_own_contract_advertises():
    """The published contract has to describe the payload, not resemble it.

    The board's flow is walked in overlay mode, where the sink's schema is
    observed rather than enforced — a payload that contradicts it still
    completes the run. So the contract's only real enforcement is here: the
    release validates the document's selectors against this schema, and a
    schema that drifts from the recipe would clear a tile the runtime then
    leaves blank.

    The subscriber number is the case that bites. It leaves the generator as
    digits, comes back from the CSV as an integer, and a table renderer handed
    an integer is entitled to group it — so the recipe hands over text, and
    this is where that stays true.
    """

    from jsonschema import Draft202012Validator

    board = _board(_scored_rows(size=40))
    errors = sorted(
        Draft202012Validator(BOARD_OUTPUT_SCHEMA).iter_errors(board),
        key=lambda error: list(error.path),
    )
    assert not errors, [
        (list(error.path), error.message) for error in errors
    ]

    assert all(isinstance(entry["msisdn"], str) for entry in board["at_risk"])
    # Dialable: the digits survive the trip, they are simply no longer a number.
    assert board["at_risk"][0]["msisdn"].isdigit()


def test_no_figure_the_documentation_quotes_is_written_into_the_board():
    """Every number on the page has to be arithmetic performed at read time.

    The demo's own notes quote 6 903 subscribers, roughly 1 000 flagged, a
    0.835 ROC AUC and a 3.5× lift. Those are the figures a hurried author would
    paste into a KPI's copy or a fallback, and a pasted figure survives a
    changed generator, a re-fit and a re-score without ever looking wrong.
    """

    quoted = ("6903", "6 903", "1 000", "1,000", "0.835", "0.860", "3.5", "3,5")
    copy_strings = [
        value for dictionary in BOARD_I18N.values() for value in dictionary.values()
    ]
    for text in [*copy_strings, BOARD_CODE]:
        for figure in quoted:
            assert figure not in text, (figure, text[:80])

    # And the summary is a function of its input: two different bases cannot
    # produce the same numbers.
    small = _board(_scored_rows(size=40))["summary"]
    large = _board(_scored_rows(size=80))["summary"]
    for key in ("subscribers_at_risk", "base_size", "revenue_at_stake_mad"):
        assert small[key] != large[key], key


# ---------------------------------------------------------------------------
# The Retention Board's document
# ---------------------------------------------------------------------------

CERTIFIED_BLOCKS = {
    "header",
    "section",
    "kpi",
    "chart",
    "table",
    "callout",
    "result",
    "action_button",
    "runtime_status",
}


def _components(document) -> list[dict]:
    return [
        component for page in document["pages"] for component in page["components"]
    ]


def _bound_selectors(document) -> list[tuple[str, str]]:
    return [
        (component["id"], component["props"]["dataBinding"]["selector"])
        for component in _components(document)
        if isinstance(component.get("props", {}).get("dataBinding"), dict)
    ]


def _schema_at(schema: dict, selector: str):
    """Walk a dot path through a JSON Schema, or fail the way a reader would."""

    current = schema
    for segment in selector.split("."):
        properties = current.get("properties")
        assert isinstance(properties, dict), (selector, segment)
        assert segment in properties, (selector, segment)
        current = properties[segment]
    return current


def test_the_board_document_is_built_only_from_certified_blocks():
    """An uncertified type degrades to a fallback renderer, silently.

    Which is the right behaviour for a runtime and the wrong one for a seed:
    the page would deploy, the release would pass, and a stakeholder would
    find a grey box where the risk chart should be. The list here is written
    out rather than imported so that a type quietly added to the platform's
    frozenset does not quietly become part of this page.
    """

    document = board_document()
    used = {component["type"] for component in _components(document)}

    assert used <= CERTIFIED_BLOCKS, used - CERTIFIED_BLOCKS
    # The spine the page was designed around, all of it present.
    assert {"header", "kpi", "chart", "table", "result", "action_button"} <= used

    ids = [component["id"] for component in _components(document)]
    assert len(ids) == len(set(ids))


def test_every_tile_reads_the_one_run_the_board_button_produced():
    """Display blocks do not fetch, and this is what that means in a document.

    Each tile names the action component it reads from; that component carries
    the binding key and is the only thing on the page that invokes anything. A
    tile pointing at a component that does not exist renders blank, and a page
    where each tile fetched for itself could show a revenue figure and a
    subscriber count from two different refreshes.
    """

    document = board_document()
    by_id = {component["id"]: component for component in _components(document)}

    actions = [
        component
        for component in _components(document)
        if component["type"] in {"form", "action_button"}
    ]
    assert [component["id"] for component in actions] == [BOARD_ACTION_ID]
    assert actions[0]["props"]["bindingKey"] == BOARD_BINDING_KEY
    # No arguments: the ingress is closed, so the button posts an empty object.
    assert actions[0]["props"]["input"] == {}

    bound = _bound_selectors(document)
    assert bound, "a dashboard with no bound tile has nothing to show"
    for component_id, _selector in bound:
        source_id = by_id[component_id]["props"]["dataBinding"]["componentId"]
        assert source_id in by_id, (component_id, source_id)
        assert by_id[source_id]["props"].get("bindingKey") == BOARD_BINDING_KEY
        assert by_id[component_id]["props"]["dataBinding"]["source"] == "run-output"

    # Nothing on the page queries a System for itself.
    assert not [
        component
        for component in _components(document)
        if "queryBinding" in component.get("props", {})
    ]


def test_the_page_says_whether_the_refresh_worked_and_not_only_what_it_found():
    """A board of empty tiles has two causes and the viewer must be told which.

    The walker's verdict on this graph is ``completed`` even when a node inside
    it failed — the seed's own ``assert_runs_are_green`` exists because of it.
    So a scored table that is missing, because the pipeline has not run yet,
    produces a finished run carrying no summary at all: every tile renders
    blank, exactly as they do during the two seconds the recipe is working.

    The status block is the only thing on the page that distinguishes the two.
    It reads the run's own lifecycle rather than a payload field, which is why
    it carries no data binding, and it has to follow the button it reports on.
    """

    components = _components(board_document())
    types = [component["type"] for component in components]

    assert "runtime_status" in types
    status = components[types.index("runtime_status")]
    assert "dataBinding" not in status.get("props", {})

    # The runtime resolves an unbound status block against the nearest action
    # above it, so a status placed before the button would report nothing.
    assert types.index("runtime_status") > types.index("action_button")


def test_every_selector_the_document_reads_is_one_the_board_produces():
    """Checked twice: against the declared contract and against real output.

    The sink's schema is what the release validates a selector against, so a
    path absent from it is caught before deployment. But the schema is authored
    and the payload is computed, and the failure that matters is the two
    drifting apart — a tile bound to a path the schema promises and the recipe
    never writes renders blank on stage with every check green.
    """

    document = board_document()
    payload = _board(_scored_rows(size=40))

    for component_id, selector in _bound_selectors(document):
        assert _schema_at(BOARD_OUTPUT_SCHEMA, selector) is not None, component_id
        current = payload
        for segment in selector.split("."):
            assert isinstance(current, dict) and segment in current, (
                component_id,
                selector,
            )
            current = current[segment]

    # The reverse direction for the fields the task's contract names: every one
    # of them is produced, whether or not a tile happens to read it today.
    summary = payload["summary"]
    assert set(summary) == {
        "subscribers_at_risk",
        "base_size",
        "revenue_at_stake_mad",
        "revenue_at_stake_label",
        "riskiest_decile_churn_pct",
        "base_churn_pct",
        "model_name",
        "model_version",
        "model_metric_key",
        "model_metric_value",
    }
    assert set(payload) == {"summary", "at_risk", "bands", "brief"}
    assert set(payload["at_risk"][0]) == {
        "msisdn",
        "region",
        "plan",
        "tenure_months",
        "arpu_mad",
        "score",
        "revenue_at_stake_mad",
    }
    assert set(payload["bands"][0]) == {"label", "value"}


def test_the_table_and_chart_read_keys_their_rows_actually_carry():
    """Column keys are not validated by the contract, only by a reader's eyes.

    A selector is checked against the published output schema; the ``key`` on a
    column and the ``labelKey``/``valueKey`` on the chart are not. Get one
    wrong and the block renders its header row over a column of blanks.
    """

    document = board_document()
    payload = _board(_scored_rows(size=40))
    by_id = {component["id"]: component for component in _components(document)}

    chart = by_id["risk-bands"]["props"]
    assert chart["kind"] == "bar"
    assert chart["labelKey"] in payload["bands"][0]
    assert chart["valueKey"] in payload["bands"][0]

    for table_id, sample in (
        ("at-risk-table", payload["at_risk"][0]),
        ("board-provenance", payload["summary"]),
    ):
        for column in by_id[table_id]["props"]["columns"]:
            assert column["key"] in sample, (table_id, column["key"])


def test_the_page_reads_in_french_and_in_english_with_no_key_missing():
    """Two dictionaries, one key set, and every visible string a reference.

    The ready-check refuses a release whose ``$i18n`` reference is missing from
    a declared language, so a gap here is a page that cannot ship. The stricter
    half is the other direction: a literal string left in ``props`` is copy no
    dictionary can reach, and it renders in English to a French reader with
    nothing to indicate anything went wrong.
    """

    assert set(BOARD_I18N) == {"en", "fr"}
    assert set(BOARD_I18N["en"]) == set(BOARD_I18N["fr"])
    assert all(value.strip() for value in BOARD_I18N["fr"].values())
    # Actually translated, not the English pasted across. Only the sentences
    # are held to it: "Version" and "ARPU (MAD)" are the same string in both
    # languages, and inventing a difference would be worse French.
    untranslated = [
        key
        for key, english in BOARD_I18N["en"].items()
        if len(english) > 24 and english == BOARD_I18N["fr"][key]
    ]
    assert not untranslated, untranslated

    document = board_document()
    referenced: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            if "$i18n" in value:
                referenced.add(value["$i18n"])
                assert value.get("fallback") == BOARD_I18N["en"][value["$i18n"]]
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document["pages"])
    assert referenced == set(BOARD_I18N["en"])


def test_the_board_flow_reads_and_writes_nothing():
    """A stakeholder pressing Refresh must not retrain, re-score or mint a table.

    Two properties, and both are about cost. The skills are the two read-only
    ones, so nothing here fits a model or publishes a dataset version — five
    refreshes cannot leave five copies of a table on the Data page. And the
    recipe's rows arrive projected to the columns the arithmetic uses, because
    every column crosses into the sandbox as JSON on each press.
    """

    flow = board_flow(scored_slug="subscriber-base-scored")
    nodes = {node["id"]: node for node in flow["nodes"]}
    slugs = {
        node["config"]["skill_slug"] for node in flow["nodes"] if node["kind"] == "task"
    }

    assert slugs == set(BOARD_SKILL_SLUGS)
    assert not slugs & {
        "ml_train_sklearn_v1",
        "ml_batch_score_v1",
        "sql_transform_v1",
        "polars_transform_v1",
        "dbt_transform_v1",
    }

    board = nodes["task.board"]["config"]["params"]
    assert board["code"] == BOARD_CODE
    assert board["sources"] == [
        {
            "dataset_slug": "subscriber-base-scored",
            "view": "scored",
            "columns": list(BOARD_COLUMNS),
        }
    ]
    # No ``output_name`` anywhere: that is the parameter that turns a node into
    # a writer.
    for node in flow["nodes"]:
        assert "output_name" not in (node.get("config") or {}).get("params", {})

    # The pin follows the lineage rather than one version of it.
    assert scored_slug() == "subscriber-base-scored"
    assert nodes["src"]["config"]["input_schema"]["additionalProperties"] is False
    assert nodes["sink"]["config"]["output_schema"] == BOARD_OUTPUT_SCHEMA


def test_the_board_flow_is_walked_by_the_engine_that_configures_recipes():
    """The script is graph-owned configuration only the DAG walker injects.

    Routed to the sequential runtime the recipe node would run with no code at
    all, and the page would refresh into an error a stakeholder cannot read.
    """

    resolution = resolve_flow_execution(board_flow(scored_slug="s"))
    assert resolution.runtime_mode == "dag_overlay", resolution
    assert resolution.reason == "graph_owned_config_requires_compatibility_dag"


# ---------------------------------------------------------------------------
# Seeding the Retention Board
# ---------------------------------------------------------------------------


@pytest.fixture()
def board(db_session):
    """The board seeded exactly as ``seed()`` seeds it, minus the pipeline.

    The datasets and the run are not needed to certify the page: the recipe
    resolves its table by slug at run time, and the ready-check reads the
    published contract rather than any data behind it. Leaving them out keeps
    the fixture to the lifecycle these tests are about.
    """

    from app.services.skills_registry import seed_skills_and_capabilities

    seed_skills_and_capabilities(db_session)
    workspace = ensure_workspace(db_session, "nawa", "Nawa")
    capability = ensure_capability(
        db_session,
        workspace,
        slug=BOARD_CAPABILITY_SLUG,
        name=BOARD_SYSTEM_NAME,
        description="seeded",
        skill_slugs=BOARD_SKILL_SLUGS,
        input_unit="scored_base",
        output_unit="retention_board",
        value_per_outcome=0.0,
    )
    system = ensure_system(
        db_session,
        workspace,
        capability,
        name=BOARD_SYSTEM_NAME,
        objective="seeded",
        flow=board_flow(scored_slug=scored_slug()),
        system_type="retention_board",
        execution_mode="real_time_decision",
    )
    binding = ensure_board_binding(db_session, workspace, system)
    experience = ensure_board_experience(db_session, workspace)
    return {
        "workspace": workspace,
        "system": system,
        "binding": binding,
        "experience": experience,
    }


def test_the_seed_turns_on_the_surface_the_board_is_rendered_by(db_session):
    """``/work`` is an explicit opt-in, and a released page behind it 404s.

    The flag is not graduated: a workspace that never asked for it has no work
    surface at all, so the seed that creates the business page is the thing
    that has to ask. The catalog entries beside it are the other half — a skill
    the workspace has not enabled cannot be bound by the System that names it.
    """

    workspace = ensure_workspace(db_session, "nawa", "Nawa")

    assert workspace.settings["features"]["experience_v1"] is True
    enabled = workspace.settings["catalog"]["enabled_skills"]
    for slug in BOARD_SKILL_SLUGS:
        assert slug in enabled, slug


def test_the_board_binding_points_at_the_published_graph(db_session, board):
    """A page names a key; the key is what has to resolve.

    ``/work`` invokes a binding, not a System, and a binding locked to a Flow
    version the System no longer publishes resolves to ``drift`` — which the
    runtime renders as an unavailable action. So the two things worth pinning
    are that the lock is on the *current* publication and that the resolver
    agrees.
    """

    from app.services.experience import bindings as binding_service

    system = board["system"]
    binding = board["binding"]

    assert binding.binding_key == BOARD_BINDING_KEY
    assert binding.system_id == system.id
    assert system.published_flow_version_id
    assert binding.published_flow_version_id == system.published_flow_version_id
    assert binding.ingress_id == "src"
    # A read behind a confirmation dialog teaches people to click through them.
    assert binding.confirmation_policy == "direct-safe"

    resolved = binding_service.resolve_binding(
        db_session, workspace=board["workspace"], binding_key=BOARD_BINDING_KEY
    )
    assert resolved["status"] == "ok", resolved
    # The contract the document's selectors were certified against.
    assert resolved["output_schema"] == BOARD_OUTPUT_SCHEMA
    assert resolved["input_schema"]["additionalProperties"] is False


def test_the_board_is_released_and_live_for_everyone_in_the_workspace(
    db_session, board
):
    """Released is not deployed, and deployed to a channel is not visible.

    Three separate facts, and a page missing any one of them is a page that
    does not appear at ``/work``. The audience matters as much: this surface
    exists for the roles that are *not* engineers, so a viewer with no Builder
    access has to be inside the release's access snapshot — which is what the
    live deployment freezes.
    """

    from app.models.experience import ExperienceDeployment, ExperienceRelease
    from app.services.experience import lifecycle

    experience = board["experience"]
    assert experience.slug == BOARD_EXPERIENCE_SLUG
    assert experience.name == BOARD_EXPERIENCE_NAME
    assert experience.pattern == "dashboard"
    assert sorted(experience.languages) == ["en", "fr"]
    # The work shell redirects off ``/work/<slug>`` when this is set, which for
    # this page would redirect away from the point of it.
    assert "live_href" not in (experience.theme or {})
    assert experience.access_policy == {"roles": BOARD_ACCESS_POLICY["role_templates"]}

    release = (
        db_session.query(ExperienceRelease)
        .filter(ExperienceRelease.experience_id == experience.id)
        .one()
    )
    deployment = (
        db_session.query(ExperienceDeployment)
        .filter(ExperienceDeployment.experience_id == experience.id)
        .one()
    )
    assert deployment.channel == "live"
    assert deployment.release_id == release.id
    assert [item["binding_key"] for item in release.bindings_snapshot] == [
        BOARD_BINDING_KEY
    ]

    for role in BOARD_ACCESS_POLICY["role_templates"]:
        assert lifecycle.audience_allows(deployment.audience, role)
        assert lifecycle.audience_allows(release.access_snapshot, role)
    assert not lifecycle.audience_allows(deployment.audience, "outsider")

    # What ``GET /work/<slug>`` resolves for a stakeholder with no Builder
    # access: the page, its live channel, and the release behind it.
    _row, chosen, served = lifecycle.resolve_work(
        db_session,
        workspace_id=board["workspace"].id,
        slug=BOARD_EXPERIENCE_SLUG,
        role="workspace_viewer",
    )
    assert chosen.channel == "live"
    assert served.id == release.id
    listed = lifecycle.list_work(
        db_session, workspace_id=board["workspace"].id, role="workspace_viewer"
    )
    assert [item[0].slug for item in listed] == [BOARD_EXPERIENCE_SLUG]


def test_reseeding_the_board_neither_re_releases_nor_re_deploys_it(db_session, board):
    """A release is immutable evidence, so cutting an identical one is noise.

    Rehearsals re-run this seed. Left unguarded, every one of them would append
    a release indistinguishable from the last and repoint the live deployment
    at it, turning the Releases list into a log of nothing having changed.
    """

    from app.models.experience import (
        ExperienceDeployment,
        ExperienceDraftRevision,
        ExperienceRelease,
    )

    experience = board["experience"]
    before = (
        db_session.query(ExperienceDeployment)
        .filter(ExperienceDeployment.experience_id == experience.id)
        .one()
    )
    revision = (
        db_session.query(ExperienceDraftRevision)
        .filter(ExperienceDraftRevision.experience_id == experience.id)
        .one()
        .revision
    )
    release_id = before.release_id

    ensure_board_binding(db_session, board["workspace"], board["system"])
    again = ensure_board_experience(db_session, board["workspace"])

    assert again.id == experience.id
    assert (
        db_session.query(ExperienceRelease)
        .filter(ExperienceRelease.experience_id == experience.id)
        .count()
        == 1
    )
    assert (
        db_session.query(ExperienceDraftRevision)
        .filter(ExperienceDraftRevision.experience_id == experience.id)
        .one()
        .revision
        == revision
    )
    db_session.refresh(before)
    assert before.release_id == release_id


def test_a_reset_takes_the_board_down_whole_so_a_re_seed_can_rebuild_it(
    db_session, board
):
    """The one part of the demo ``--reset`` deletes rather than retires.

    A released document cannot be edited, and a deployment cannot point at a
    release that was cut against a binding which no longer resolves. So a board
    left half in place is worse than no board: the next seed would either
    deploy the stale release or refuse the new one. The teardown is scoped to
    the seed's own slug and key — nothing else in the workspace is touched.
    """

    from app.models.experience import (
        Experience,
        ExperienceDeployment,
        ExperienceDraftHistory,
        ExperienceDraftRevision,
        ExperienceRelease,
    )
    from app.models.system_binding import SystemBinding

    workspace = board["workspace"]
    other = Experience(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Somebody else's app",
        slug="expenses",
        pattern="form_result",
        languages=["en"],
        theme={},
        access_policy={},
    )
    db_session.add(other)
    db_session.commit()

    tally = reset(db_session, workspace)

    assert tally["experiences"] == 1
    assert tally["bindings"] == 1
    for model_class in (
        ExperienceDeployment,
        ExperienceRelease,
        ExperienceDraftRevision,
        ExperienceDraftHistory,
    ):
        assert (
            db_session.query(model_class)
            .filter(model_class.experience_id == board["experience"].id)
            .count()
            == 0
        ), model_class.__name__
    assert (
        db_session.query(Experience)
        .filter(Experience.slug == BOARD_EXPERIENCE_SLUG)
        .one_or_none()
        is None
    )
    assert (
        db_session.query(SystemBinding)
        .filter(SystemBinding.binding_key == BOARD_BINDING_KEY)
        .one_or_none()
        is None
    )
    # Somebody else's application is not the seed's to remove.
    assert (
        db_session.query(Experience).filter(Experience.slug == "expenses").one_or_none()
        is not None
    )

    # And the System survives, so the rebuild reconciles a graph with history
    # behind it rather than creating a second one.
    assert (
        db_session.query(System)
        .filter(System.workspace_id == workspace.id, System.name == BOARD_SYSTEM_NAME)
        .one_or_none()
        is not None
    )

    ensure_board_binding(db_session, workspace, board["system"])
    rebuilt = ensure_board_experience(db_session, workspace)
    assert rebuilt.slug == BOARD_EXPERIENCE_SLUG
    assert rebuilt.id != board["experience"].id
