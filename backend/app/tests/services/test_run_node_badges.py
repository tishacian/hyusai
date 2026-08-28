"""The figures a settled node puts on the canvas.

A run is the moment the data plane becomes visible: the transform read 8,412
rows and wrote 6,903, the fit scored 0.87, the serving node answered from
version 3. Every one of those numbers is already on the wire — datasets travel
as ``{dataset_id, rows, schema}`` envelopes and a model travels as a reference
carrying its primary metric — so the only question these tests answer is
whether the ``node_end`` checkpoint lifts them, and whether it stays silent on
the nodes that have nothing to say.

The alternative (a fetch per node after the run) is what makes a canvas feel
dead, so the badge riding the same frame as the status is the requirement, not
an optimization.
"""

from __future__ import annotations

from app.services.run_engine.dag import _node_data_badge


# ---------------------------------------------------------------------------
# Transform nodes: what came in, what went out
# ---------------------------------------------------------------------------


def test_a_transform_badge_names_both_sides_of_the_row_count():
    badge = _node_data_badge(
        {"dataset_id": "raw", "rows": 8412, "schema": []},
        {"output": {"dataset_id": "clean", "rows": 6903, "schema": []}},
    )

    assert badge == {"rows_in": 8412, "rows_out": 6903, "dataset_id": "clean"}


def test_an_upstream_envelope_is_found_one_level_down():
    """A wired port arrives as ``{"input": {...}}``, not flattened."""

    badge = _node_data_badge(
        {"input": {"dataset_id": "raw", "rows": 120}, "question": "?"},
        {"output": {"dataset_id": "out", "rows": 100}},
    )

    assert badge == {"rows_in": 120, "rows_out": 100, "dataset_id": "out"}


def test_graph_owned_configuration_is_never_mistaken_for_data():
    """``_transform`` carries pins, and a pin is not what the node read."""

    badge = _node_data_badge(
        {"_transform": {"sources": [{"dataset_id": "pinned", "rows": 999}]}},
        {"output": {"dataset_id": "out", "rows": 10}},
    )

    assert badge == {"rows_out": 10, "dataset_id": "out"}


def test_a_node_with_nothing_to_show_gets_no_badge():
    assert _node_data_badge({"question": "?"}, {"output": {"answer": "42"}}) is None
    assert _node_data_badge(None, {}) is None


def test_a_row_count_that_is_not_a_number_is_ignored():
    badge = _node_data_badge(
        {"dataset_id": "raw", "rows": "many"},
        {"output": {"dataset_id": "out", "rows": True}},
    )

    # The reference survives — it is a string either way — but neither count
    # does: "many" is not a figure and `True` is not a row count.
    assert badge == {"dataset_id": "out"}
    assert _node_data_badge({"rows": "many"}, {"output": {"rows": True}}) is None


def test_the_badge_carries_the_dataset_a_node_wrote_so_it_can_be_opened():
    """A score node's output is a dataset, and the point is to look at it."""

    badge = _node_data_badge(
        {"dataset_id": "features", "rows": 6903},
        {
            "output": {
                "dataset_id": "scored",
                "rows": 6903,
                "served": {"slug": "churn-radar", "version": 3},
            }
        },
    )

    assert badge["dataset_id"] == "scored"
    assert badge["model"] == {"slug": "churn-radar", "version": 3}
    # The upstream reference is NOT the badge's: a node is credited with what it
    # wrote, and pointing at its input would open the wrong table.
    assert badge["dataset_id"] != "features"


# ---------------------------------------------------------------------------
# Training nodes: the one number the fit produced
# ---------------------------------------------------------------------------


def test_a_training_badge_carries_the_primary_metric_and_the_rows_it_read():
    badge = _node_data_badge(
        {"dataset_id": "features", "rows": 8000},
        {
            "output": {
                "model_id": "m1",
                "slug": "churn-risk",
                "version": 3,
                "metric": {"key": "roc_auc", "value": 0.871},
                "rows": 8000,
            }
        },
    )

    assert badge["rows_in"] == 8000
    assert badge["metric"] == {"key": "roc_auc", "value": 0.871}
    assert badge["model_id"] == "m1"
    # A model reference is not a dataset envelope, so its `rows` is not an
    # output row count: the node wrote a model, not a table.
    assert "rows_out" not in badge


def test_a_metric_without_a_key_or_a_value_is_not_a_metric():
    assert (
        _node_data_badge(None, {"output": {"metric": {"value": 0.9}}}) is None
    )
    assert (
        _node_data_badge(None, {"output": {"metric": {"key": "roc_auc"}}}) is None
    )


# ---------------------------------------------------------------------------
# Serving nodes: which version answered
# ---------------------------------------------------------------------------


def test_a_batch_score_badge_names_the_model_that_scored_the_rows():
    badge = _node_data_badge(
        {"dataset_id": "base", "rows": 6903},
        {
            "output": {
                "dataset_id": "scored",
                "rows": 6903,
                "model": {"slug": "churn-risk", "version": 3},
                "scored_rows": 6903,
            }
        },
    )

    assert badge["rows_in"] == 6903 and badge["rows_out"] == 6903
    assert badge["model"] == {"slug": "churn-risk", "version": 3}


def test_a_single_record_prediction_badge_counts_its_answers():
    badge = _node_data_badge(
        {"tenure": 3},
        {
            "output": {
                "served": {"slug": "churn-risk", "version": 2},
                "predictions": [{"prediction": "1", "confidence": 0.82}],
            }
        },
    )

    assert badge["model"] == {"slug": "churn-risk", "version": 2}
    assert badge["predictions"] == 1


def test_a_model_reference_without_a_version_still_names_itself():
    badge = _node_data_badge(None, {"output": {"model": {"slug": "churn-risk"}}})

    assert badge == {"model": {"slug": "churn-risk"}}


# ---------------------------------------------------------------------------
# The checkpoint the canvas actually reads
# ---------------------------------------------------------------------------


def test_the_node_end_summary_carries_the_badge_under_data():
    """The frame the SSE consumer receives, not just the projection."""

    from app.services.run_engine.dag import (
        DagNode,
        WalkerState,
        _summarise_node_execution,
    )

    node = DagNode(
        id="clean",
        type="task",
        kind="task",
        label="Clean",
        config={"skill_slug": "sql_transform_v1"},
        skill_slug="sql_transform_v1",
        data={},
    )
    state = WalkerState()

    summary = _summarise_node_execution(
        None,
        None,
        node,
        {"output": {"dataset_id": "clean", "rows": 6903}},
        state,
        0,
        node_input={"dataset_id": "raw", "rows": 8412},
    )

    assert summary["data"] == {
        "rows_in": 8412,
        "rows_out": 6903,
        "dataset_id": "clean",
    }


def test_the_node_end_summary_lifts_the_invocation_and_provider():
    """The canvas needs the invocation id to open /runs, not another fetch."""

    from app.services.run_engine.dag import (
        DagNode,
        WalkerState,
        _summarise_node_execution,
    )

    class _Inv:
        id = "inv-brief"
        skill_slug = "azure_llm_v1"
        status = "completed"
        latency_ms = 88.0
        cost = None
        error = None
        trace = {
            "effective_model": "gpt-4o-mini",
            "provider": "openai",
            "credential_source": "env",
        }

    class _Query:
        def filter(self, *_a, **_k):
            return self

        def first(self):
            return _Inv()

    class _DB:
        def query(self, *_a, **_k):
            return _Query()

    node = DagNode(
        id="task.brief",
        type="llm",
        kind="task",
        label="Retention brief",
        config={"skill_slug": "azure_llm_v1"},
        skill_slug="azure_llm_v1",
        data={},
    )
    state = WalkerState()
    state.invocation_ids = ["inv-brief"]

    summary = _summarise_node_execution(
        _DB(),
        None,
        node,
        {"output": {"completion": "ok"}},
        state,
        0,
    )

    assert summary["invocation_id"] == "inv-brief"
    assert summary["skill_slug"] == "azure_llm_v1"
    assert summary["effective_model"] == "gpt-4o-mini"
    assert summary["provider"] == "openai"
    assert summary["credential_source"] == "env"


def test_an_agent_loop_summary_names_the_last_decide_and_chosen_skill():
    from app.services.run_engine.dag import (
        DagNode,
        WalkerState,
        _summarise_node_execution,
    )

    class _Inv:
        id = "inv-decide"
        skill_slug = "decide_next_v1"
        status = "completed"
        latency_ms = 40.0
        cost = None
        error = None
        trace = {
            "effective_model": "gpt-4o-mini",
            "provider": "openai",
            "credential_source": "env",
        }

    class _Query:
        def filter(self, *_a, **_k):
            return self

        def first(self):
            return _Inv()

    class _DB:
        def query(self, *_a, **_k):
            return _Query()

    node = DagNode(
        id="loop.itsd",
        type="agent_loop",
        kind="agent_loop",
        label="Reset password",
        config={"decide_skill": "decide_next_v1"},
        skill_slug="decide_next_v1",
        data={},
    )
    state = WalkerState()
    state.invocation_ids = ["inv-decide"]
    summary = _summarise_node_execution(
        _DB(),
        None,
        node,
        {
            "output": {
                "observations": [{"turn": 1, "skill": "azure_llm_v1", "ok": True}],
                "exit": "complete",
            }
        },
        state,
        0,
    )
    assert summary["invocation_id"] == "inv-decide"
    assert summary["decide_skill"] == "decide_next_v1"
    assert summary["chosen_skill"] == "azure_llm_v1"
    assert summary["provider"] == "openai"


def test_a_node_that_returned_nothing_usable_adds_no_data_key():
    from app.services.run_engine.dag import (
        DagNode,
        WalkerState,
        _summarise_node_execution,
    )

    node = DagNode(
        id="answer",
        type="task",
        kind="task",
        label="Answer",
        config={},
        skill_slug="llm_rag_answer_v1",
        data={},
    )

    summary = _summarise_node_execution(
        None, None, node, {"output": {"answer": "42"}}, WalkerState(), 0
    )

    assert "data" not in summary
