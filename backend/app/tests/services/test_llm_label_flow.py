"""The labeling node owns its configuration and keeps the workspace context."""
from types import ModuleType, SimpleNamespace
import sys

import pytest

from app.services.run_engine.dag import (
    DagNode, _GRAPH_OWNED_BLOCKS, _apply_graph_owned_config, _passthrough_without_recipe,
)
from app.services.run_engine.execution_contract import resolve_flow_execution
from app.services.skills_registry import wrappers
from app.services.skills_registry.seed import SEED_CAPABILITIES, SEED_SKILLS
from app.services.systems.flow_manifest import _editable_fields_from_schema


SLUG = "llm_label_dataset_v1"


def test_label_catalog_is_bound_claimed_and_all_settings_are_editable():
    skill = next(row for row in SEED_SKILLS if row["slug"] == SLUG)
    # Zero token pricing leaves provider cost unmeasured; a fixed-price unit
    # would incorrectly report this workspace-model execution as measured free.
    assert skill["pricing"] == {"unit": "per_1k_tokens", "unit_price": 0.0, "currency": "USD"}
    assert wrappers._REGISTRY[SLUG][0] is wrappers._llm_label_dataset_v1
    assert wrappers._REGISTRY[SLUG][2] == "bound"
    assert any(SLUG in row["skill_slugs"] for row in SEED_CAPABILITIES)
    fields = _editable_fields_from_schema(SimpleNamespace(input_schema=skill["input_schema"]))
    key, slugs, params = next(row for row in _GRAPH_OWNED_BLOCKS if row[0] == "_label")
    assert set(params) == {field["key"] for field in fields}
    props = skill["input_schema"]["properties"]
    assert "default" not in props["input_cost_per_million"]
    assert "default" not in props["output_cost_per_million"]
    assert not {"provider", "model"}.intersection(props)


def test_label_flow_routes_to_dag_and_replaces_untrusted_configuration():
    params = {"labels": ["yes", "no"], "max_cost_usd": 1, "instruction": "Choose a class"}
    config = {"skill_slug": SLUG, "params": params}
    flow = {"schema_version": 3, "nodes": [{"id": "label", "kind": "task", "config": config}], "edges": []}
    assert resolve_flow_execution(flow).uses_dag
    node = DagNode("label", "skill", "task", None, config, SLUG, {})
    incoming = {
        "_label": {"max_cost_usd": 1000, "labels": ["injected"]},
        "max_cost_usd": 1000, "labels": ["injected"], "dataset_id": "source",
    }
    key, slugs, keys = next(row for row in _GRAPH_OWNED_BLOCKS if row[0] == "_label")
    _apply_graph_owned_config(node, incoming, key=key, slugs=slugs, param_keys=keys)
    assert incoming["_label"]["labels"] == ["yes", "no"]
    assert incoming["_label"]["max_cost_usd"] == 1
    assert incoming["_label"]["node_id"] == "label"
    assert "labels" not in incoming and "max_cost_usd" not in incoming
    assert _passthrough_without_recipe(incoming) == {"dataset_id": "source"}
    other = DagNode("other", "skill", "task", None, {}, "opaque_v1", {})
    _apply_graph_owned_config(other, incoming, key=key, slugs=slugs, param_keys=keys)
    assert "_label" not in incoming


@pytest.mark.asyncio
@pytest.mark.parametrize("pin", [None, {"dataset_id": "pinned"}, {"dataset_slug": "pinned-lineage"}])
async def test_wrapper_prefers_pin_and_preserves_governed_context(monkeypatch, pin):
    calls = []
    result = {"dataset_id": "generated", "job_id": "job", "labeling": {"rows": 2}}
    module = ModuleType("app.services.llm_dataset_labeling")
    async def label_dataset(payload, ctx):
        calls.append((payload, ctx))
        return result
    module.label_dataset = label_dataset
    monkeypatch.setitem(sys.modules, module.__name__, module)
    block = {"sources": [pin] if pin else [], "labels": ["yes", "no"]}
    ctx = {"workspace_id": "trusted", "user_id": "user", "run_id": "run"}
    got = await wrappers._llm_label_dataset_v1({
        "_label": block, "wired": {"dataset_id": "wired"}, "workspace_id": "forged",
    }, ctx)
    assert got is result
    assert calls[0][0] == {"config": block, "dataset_ref": pin or {"dataset_id": "wired"}}
    assert calls[0][1] is ctx


@pytest.mark.asyncio
async def test_wrapper_allows_resume_without_replacing_the_recorded_source(monkeypatch):
    module = ModuleType("app.services.llm_dataset_labeling")
    async def label_dataset(payload, ctx):
        assert payload == {"config": {"resume_job_id": "saved"}, "dataset_ref": None}
        return {"job_id": "saved"}
    module.label_dataset = label_dataset
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert await wrappers._llm_label_dataset_v1(
        {"_label": {"resume_job_id": "saved"}}, {"workspace_id": "trusted"}
    ) == {"job_id": "saved"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,ctx,code", [
    ({"workspace_id": "forged", "_label": {}}, {}, "label_workspace_required"),
    ({"_label": []}, {"workspace_id": "trusted"}, "label_config_missing"),
    ({"labels": ["yes", "no"]}, {"workspace_id": "trusted"}, "label_config_missing"),
])
async def test_wrapper_rejects_caller_workspace_or_missing_graph_config(payload, ctx, code):
    with pytest.raises(ValueError, match=code):
        await wrappers._llm_label_dataset_v1(payload, ctx)
