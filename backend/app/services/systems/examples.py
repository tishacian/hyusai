"""Built-in System examples a creator may import on purpose (plan lot 4, US09).

An example is an ordinary export envelope (``agentium.system.export``), so
importing it goes through ``POST /systems/import`` like any other envelope and
creates a draft System the creator owns. Nothing here is imported on its own:
the catalogue is only read when someone chooses "Start from an example".

Every example is domain-neutral, references skills by slug only and ships no
documents: the creator brings their own sources.
"""

from __future__ import annotations

import copy
from typing import Any

from app.services.chains.export_service import ENVELOPE_KIND, SCHEMA_VERSION

PUBLISHER = "Agentium"


def _question_answer_flow(*, instruction: str) -> dict[str, Any]:
    return {
        "source": "flow",
        "extended": False,
        "schema_version": 3,
        "variant": "automation_v1",
        "nodes": [
            {
                "id": "trigger",
                "type": "source",
                "kind": "source",
                "label": "Question",
                "position": {"x": 80, "y": 120},
                "outputs": [{"name": "transcript", "schema": "string", "required": True}],
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "type": "object",
                        "required": ["transcript"],
                        "properties": {
                            "transcript": {
                                "type": "string",
                                "description": "The question to answer from the workspace documents.",
                            }
                        },
                    },
                },
            },
            {
                "id": "answer",
                "type": "skill",
                "kind": "task",
                "label": "Sourced answer",
                "position": {"x": 360, "y": 120},
                "inputs": [{"name": "query", "schema": "string"}],
                "outputs": [
                    {"name": "answer", "schema": "string"},
                    {"name": "citations", "schema": "array"},
                ],
                "config": {
                    "skill_slug": "llm_rag_answer_v1",
                    "skill_category": "RAG",
                    "inputs_map": {"query": "run.transcript"},
                    "params": {"instruction": instruction},
                    "outputs_map": {},
                },
                "data": {
                    "description": (
                        "Answers from the workspace documents with citations, "
                        "and says so when the documents do not hold the answer."
                    ),
                },
            },
            {
                "id": "output",
                "type": "sink",
                "kind": "sink",
                "label": "Answer",
                "position": {"x": 640, "y": 120},
                "inputs": [{"name": "result", "schema": "object"}],
            },
        ],
        "edges": [
            {"from": "trigger", "to": "answer", "kind": "data", "from_port": "transcript"},
            {"from": "answer", "to": "output", "kind": "data", "to_port": "result"},
        ],
    }


_EXAMPLES: list[dict[str, Any]] = [
    {
        "id": "internal_procedures_assistant",
        "version": "1",
        "name": "Internal procedures assistant",
        "objective": (
            "Answer employees' questions about internal procedures from the documents "
            "imported into this workspace, cite the passage used, and abstain when the "
            "documents do not contain the answer."
        ),
        "requires": ["completion_model", "collection"],
        "flow": _question_answer_flow(
            instruction=(
                "Answer only from the retrieved passages and cite each one you use. "
                "If they do not contain the answer, say that the documents do not cover it."
            ),
        ),
    },
]


def list_examples() -> list[dict[str, Any]]:
    """The catalogue with provenance and the exact envelope that would be imported."""
    rows = []
    for example in _EXAMPLES:
        rows.append(
            {
                "id": example["id"],
                "version": example["version"],
                "name": example["name"],
                "objective": example["objective"],
                "requires": list(example["requires"]),
                "provenance": {
                    "publisher": PUBLISHER,
                    "source": "builtin",
                    "example_id": example["id"],
                    "version": example["version"],
                },
                "envelope": envelope(example),
            }
        )
    return rows


def envelope(example: dict[str, Any]) -> dict[str, Any]:
    flow = copy.deepcopy(example["flow"])
    slugs = sorted(
        {
            str(node["config"]["skill_slug"])
            for node in flow["nodes"]
            if isinstance(node.get("config"), dict) and node["config"].get("skill_slug")
        }
    )
    return {
        "kind": ENVELOPE_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_by": PUBLISHER,
        "source": {"example_id": example["id"], "example_version": example["version"]},
        "system": {
            "name": example["name"],
            "objective": example["objective"],
            "flow_definition": flow,
            "skill_slugs": slugs,
            "execution_mode": "real_time_decision",
            "execution_profile": {},
            "coordination_pattern": "single_agent",
            "default_prompt_type": None,
            "default_model": None,
            "retrieval_mode_default": None,
        },
    }
