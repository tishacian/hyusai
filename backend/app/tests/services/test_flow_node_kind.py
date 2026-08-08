"""The structural role of a node must read the same way to every reader.

The compiler decides from this whether to freeze an ingress; the DAG walker
re-checks it before serving a Run against that frozen ingress. If the two
disagree, the dispatch boundary accepts a Run the engine then refuses with
``contract_ingress_source_invalid``, which is a worse failure than the clean
422 it replaces.
"""

import pytest

from app.services.chains.dag_validator import _node_kind
from app.services.flow_node_kind import flow_node_kind, is_flow_source_node
from app.services.run_engine.dag import DagGraph
from app.services.run_engine.triggers import dispatch_trigger_ingresses


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        # Canonical dialect: the role is named in ``kind``.
        ({"id": "n", "kind": "source"}, "source"),
        ({"id": "n", "kind": "task"}, "task"),
        ({"id": "n", "kind": "sink"}, "sink"),
        # Legacy dialect: no ``kind`` at all, the role is named in ``type``.
        ({"id": "n", "type": "source"}, "source"),
        # Only the bare ``source`` literal is tolerated. A dotted type is a
        # sub-discriminator, and a declarative asset must not become an entry
        # point by losing its ``kind``.
        ({"id": "n", "type": "source.collection"}, "task"),
        ({"id": "n", "type": "source.webhook"}, "task"),
        # A legacy ``type: sink`` deliberately stays a task: promoting it would
        # change compiled outputs, which is a separate decision.
        ({"id": "n", "type": "sink"}, "task"),
        # Nothing to go on.
        ({"id": "n"}, "task"),
        ({"id": "n", "kind": "", "type": ""}, "task"),
    ],
)
def test_flow_node_kind_resolves_both_dialects(node, expected) -> None:
    assert flow_node_kind(node) == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        # ``kind`` is canonical and decides on its own, so a graph carrying both
        # fields never resolves by mapping order.
        ({"id": "n", "kind": "task", "type": "source"}, "task"),
        ({"id": "n", "kind": "source", "type": "task"}, "source"),
        ({"id": "n", "kind": "sink", "type": "source"}, "sink"),
    ],
)
def test_kind_wins_over_a_contradicting_type(node, expected) -> None:
    assert flow_node_kind(node) == expected
    # Order of insertion must not matter either.
    reversed_node = dict(reversed(list(node.items())))
    assert flow_node_kind(reversed_node) == expected


def test_every_reader_agrees_on_a_legacy_source_node() -> None:
    node = {"id": "source.feeds", "type": "source"}
    flow = {
        "nodes": [node, {"id": "sink.brief", "kind": "sink"}],
        "edges": [{"from": "source.feeds", "to": "sink.brief"}],
    }

    assert is_flow_source_node(node)
    assert _node_kind(node) == "source"
    assert DagGraph.from_flow_definition(flow).nodes["source.feeds"].kind == "source"


def test_a_legacy_plain_source_is_not_promoted_to_a_trigger() -> None:
    """Recognising the role must not invent a delivery surface.

    ``dispatch_trigger_ingresses`` keys on the trigger ``type`` vocabulary, so a
    bare legacy source stays out of it while a declared trigger stays in.
    """

    legacy = {"nodes": [{"id": "source.feeds", "type": "source"}], "edges": []}
    declared = {
        "nodes": [{"id": "arrival", "kind": "source", "type": "source.sftp_arrival"}],
        "edges": [],
    }

    assert dispatch_trigger_ingresses(legacy) == {}
    assert dispatch_trigger_ingresses(declared) == {"sftp.file_arrived": ["arrival"]}
