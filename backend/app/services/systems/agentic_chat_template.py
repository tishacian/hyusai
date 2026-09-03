"""Workspace-parameterised generator for the agentic chat System.

The agentic chat graph (``chat_agentic_thinking_v1``: plan / route / retrieve
lanes / generate / evaluate / self-correct / egress / HITL) was born as the
Andritz artifact ``andritz_chat_agentic_v3.json`` and provisioned by
migrations for that one workspace.  This module turns the same 23-node spine
into a template every workspace can own:

* the *shape* (nodes, edges, decision conditions, skills) is the artifact's,
  byte-for-byte, plus the model-tier wiring from the planner to the LLM nodes;
* the *profile* (collection binding, HITL wording, industrial grounding,
  provenance prefix) comes from the workspace.

``andritz_chat_agentic_v3.json`` stays the frozen fixture the historical
migrations replay; ``test_workspace_agentic_bootstrap.py`` pins the template
rendered for the Andritz profile against it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional

from app.services.chat_agentic_contract import agentic_flow_contract_digest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session as DBSession

    from app.models.workspace import Workspace

TEMPLATE_REVISION = "agentic_chat_template_v4"
TEMPLATE_ID = "agentic-chat-template-v4"
TEMPLATE_NAME = "Chat Agentic Thinking (workspace template)"
AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "flows" / "andritz_chat_agentic_v3.json"
)

ANDRITZ_NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
# Named Andritz machines / systems / brands that guarantee a query is in-corpus
# (gates a false ``reject_oos``).  Historically ``_KNOWN_ENTITY_RE`` in the skills.
ANDRITZ_KNOWN_ENTITIES: tuple[str, ...] = (
    "qualiscan",
    r"qms[\s-]?\d+",
    "uraca",
    "etachrom",
    "sinamics",
    "simotics",
    "jetlace",
    r"servo\s*x",
    "pollrich",
    r"continental\s*gvjs",
    "wilo",
    "ksb",
    "geotex",
    "excelle",
    "starter",
    "kd724",
)
ANDRITZ_EXAMPLE_ENTITIES = "AKK200, CU250S-2, D.60, Qualiscan QMS-12, URACA, Etachrom, SINAMICS"

# Nodes whose LLM call takes the planner's tier.
_TIER_CONSUMERS = ("task.generate", "task.self_correct")
_PLANNER_NODE = "plan.thinking"
_ASSET_NODE = "asset.collection"
_HITL_NODE = "hitl.expert_review"


@dataclass(frozen=True)
class AgenticChatProfile:
    """Everything workspace-specific the template and the skills need."""

    slug: str
    family: str = "generic"
    industrial: bool = False
    domain_label: str = ""
    collection_slug: Optional[str] = None
    oos_scope: str = ""
    expert_label: str = ""
    known_entities: tuple[str, ...] = ()
    example_entities: str = ""
    project_code_gates: bool = False

    @property
    def key(self) -> str:
        return "andritz" if self.family == "andritz" else self.slug

    @property
    def is_andritz(self) -> bool:
        return self.family == "andritz"

    @property
    def agent_label(self) -> str:
        """"agent de chat industriel Andritz" / "agent de chat ACME"."""
        kind = "industriel " if self.industrial else ""
        return f"agent de chat {kind}{self.domain_label or self.slug}".strip()

    @property
    def oos_message(self) -> str:
        if self.is_andritz:
            return "Hors du perimetre Andritz."
        return f"Hors du perimetre de {self.oos_scope}." if self.oos_scope else "Hors du perimetre du workspace."

    @property
    def clarify_question(self) -> str:
        if self.industrial:
            return "Pouvez-vous preciser le projet ou l'equipement concerne ?"
        return "Pouvez-vous preciser le sujet ou le document concerne ?"

    @property
    def anchor_examples(self) -> str:
        if self.example_entities:
            return self.example_entities
        return "une reference, un identifiant ou un nom de document"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["known_entities"] = list(self.known_entities)
        data["key"] = self.key
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> "AgenticChatProfile":
        data = dict(raw) if isinstance(raw, Mapping) else {}
        data.pop("key", None)
        known = data.get("known_entities")
        data["known_entities"] = tuple(str(x) for x in known) if isinstance(known, (list, tuple)) else ()
        allowed = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


def andritz_profile() -> AgenticChatProfile:
    """The profile the historical artifact encodes — the non-regression fixture."""
    return AgenticChatProfile(
        slug="andritz",
        family="andritz",
        industrial=True,
        domain_label="Andritz",
        collection_slug=ANDRITZ_NOTICES_COLLECTION,
        oos_scope=(
            "l'industrie Andritz (machines, pompes, cartes, variateurs, documentation technique)"
        ),
        expert_label="un expert Andritz",
        known_entities=ANDRITZ_KNOWN_ENTITIES,
        example_entities=ANDRITZ_EXAMPLE_ENTITIES,
        project_code_gates=True,
    )


def generic_profile(
    *,
    slug: str,
    family: str = "generic",
    domain_label: str = "",
    collection_slug: Optional[str] = None,
    industrial: Optional[bool] = None,
) -> AgenticChatProfile:
    from app.services.systems.bootstrap import INDUSTRIAL_FAMILIES

    is_industrial = bool(industrial) if industrial is not None else family in INDUSTRIAL_FAMILIES
    label = (domain_label or slug).strip()
    return AgenticChatProfile(
        slug=slug,
        family=family,
        industrial=is_industrial,
        domain_label=label,
        collection_slug=collection_slug,
        oos_scope=(
            f"la documentation technique de {label} (equipements, procedures, notices)"
            if is_industrial
            else f"la base de connaissances du workspace {label}"
        ),
        expert_label=f"un expert {label}" if is_industrial else "un expert du workspace",
        known_entities=(),
        example_entities="",
        project_code_gates=is_industrial,
    )


def workspace_agentic_chat_profile(
    workspace: "Workspace",
    *,
    db: Optional["DBSession"] = None,
) -> AgenticChatProfile:
    """Derive the profile from workspace settings (family, scopes, name)."""
    from app.services.systems.bootstrap import _workspace_chat_profile
    from app.services.workspace_features import workspace_family

    family = workspace_family(workspace)
    if family == "andritz":
        return andritz_profile()
    chat_profile = _workspace_chat_profile(workspace)
    slugs = [str(s) for s in (chat_profile.get("collection_slugs") or []) if str(s).strip()]
    collection = slugs[0] if len(slugs) == 1 else None
    return generic_profile(
        slug=str(getattr(workspace, "slug", "") or ""),
        family=family,
        domain_label=str(getattr(workspace, "name", "") or getattr(workspace, "slug", "") or ""),
        collection_slug=collection,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _load_artifact() -> dict[str, Any]:
    with ARTIFACT_PATH.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    if not isinstance(artifact, dict):  # pragma: no cover - repository invariant
        raise RuntimeError("agentic chat artifact is not a JSON object")
    return artifact


def _nodes_by_id(flow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node.get("id")): node for node in flow.get("nodes") or [] if isinstance(node, dict)}


def _wire_model_tier(flow: dict[str, Any]) -> None:
    """Planner -> LLM nodes: the tier is data, carried like every other plan field."""
    nodes = _nodes_by_id(flow)
    planner = nodes[_PLANNER_NODE]
    outputs = planner.setdefault("outputs", [])
    if not any(isinstance(o, dict) and o.get("name") == "model_tier" for o in outputs):
        outputs.append({"name": "model_tier", "schema": "string"})
    for node_id in _TIER_CONSUMERS:
        node = nodes[node_id]
        config = node.setdefault("config", {})
        inputs_map = config.setdefault("inputs_map", {})
        inputs_map["model_tier"] = {"node_id": _PLANNER_NODE, "path": ["model_tier"]}
        inputs = node.setdefault("inputs", [])
        if not any(isinstance(i, dict) and i.get("name") == "model_tier" for i in inputs):
            inputs.append({"name": "model_tier", "schema": "string"})


def _apply_profile(flow: dict[str, Any], profile: AgenticChatProfile) -> None:
    nodes = _nodes_by_id(flow)
    asset = nodes[_ASSET_NODE]
    asset_config = asset.setdefault("config", {})
    if profile.collection_slug:
        asset_config["collection_slug"] = profile.collection_slug
        asset_config["workspace_scoped"] = True
        if profile.family != "andritz":
            asset["label"] = f"Collection {profile.collection_slug}"
    else:
        asset_config["collection_slug"] = None
        asset_config["workspace_scoped"] = True
        asset["label"] = "Collections du workspace"

    hitl = nodes[_HITL_NODE]
    hitl_config = hitl.setdefault("config", {})
    hitl_config["prompt"] = (
        f"Confiance post-reponse < 0.4 (composite < 40) : {profile.expert_label} doit valider "
        "la reponse avant diffusion."
    )

    planner = nodes[_PLANNER_NODE]
    params = planner.setdefault("config", {}).setdefault("params", {})
    prompt = str(params.get("system_prompt") or "")
    if profile.family != "andritz":
        prompt = prompt.replace(
            "d'un agent de chat industriel Andritz",
            f"d'un agent de chat {'industriel ' if profile.industrial else ''}{profile.domain_label}",
        ).replace(
            "hors industrie Andritz",
            f"hors de {profile.oos_scope}",
        )
    params["system_prompt"] = prompt


def build_flow_definition(profile: AgenticChatProfile) -> dict[str, Any]:
    """Render the workspace's agentic chat graph (schema_version 3)."""
    artifact = _load_artifact()
    flow = copy.deepcopy(artifact.get("flow_definition") or {})
    flow["variant"] = AGENTIC_VARIANT
    flow["source"] = "agentic_chat_template"
    flow["template_id"] = TEMPLATE_ID
    flow["template_name"] = TEMPLATE_NAME
    flow["template_revision"] = TEMPLATE_REVISION
    flow["chat_profile_key"] = profile.key
    _wire_model_tier(flow)
    _apply_profile(flow, profile)
    return flow


def build_membrane_spec(profile: AgenticChatProfile) -> dict[str, Any]:
    artifact = _load_artifact()
    membrane = copy.deepcopy(artifact.get("membrane_spec") or {})
    inbound = membrane.setdefault("inbound", {})
    inbound["industrial_grounding"] = bool(profile.industrial)
    inbound["reject_cross_project_sources"] = bool(profile.industrial)
    inbound["collection_allowlist"] = [profile.collection_slug] if profile.collection_slug else []
    provenance = membrane.setdefault("provenance", {})
    provenance["object_store_prefix"] = f"membrane/{profile.slug}/chat-agentic/"
    return membrane


def build_adaptive_policy() -> dict[str, Any]:
    return copy.deepcopy(_load_artifact().get("adaptive_policy") or {})


def build_retrieval_contract(profile: AgenticChatProfile) -> dict[str, Any]:
    """System-level contract the retrieval skills enforce at runtime."""
    if profile.collection_slug:
        return {
            "collection": profile.collection_slug,
            "asset_binding": "authoritative",
            "empty_bound_collection": "abstain",
            "allow_workspace_fallback": False,
        }
    return {
        "asset_binding": "workspace",
        "allow_workspace_fallback": True,
    }


def contract_digest(profile: AgenticChatProfile) -> str:
    digest = agentic_flow_contract_digest(build_flow_definition(profile))
    if digest is None:  # pragma: no cover - the template always renders nodes/edges
        raise RuntimeError("agentic chat template rendered no contract")
    return digest


def flow_skill_slugs(flow: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        slug = (node.get("config") or {}).get("skill_slug")
        if slug and slug not in out:
            out.append(str(slug))
    return out


@dataclass(frozen=True)
class RenderedAgenticChat:
    profile: AgenticChatProfile
    flow_definition: dict[str, Any]
    membrane_spec: dict[str, Any]
    adaptive_policy: dict[str, Any]
    retrieval_contract: dict[str, Any]
    contract_sha256: str
    skill_slugs: list[str] = field(default_factory=list)


def render(profile: AgenticChatProfile) -> RenderedAgenticChat:
    flow = build_flow_definition(profile)
    digest = agentic_flow_contract_digest(flow)
    if digest is None:  # pragma: no cover
        raise RuntimeError("agentic chat template rendered no contract")
    return RenderedAgenticChat(
        profile=profile,
        flow_definition=flow,
        membrane_spec=build_membrane_spec(profile),
        adaptive_policy=build_adaptive_policy(),
        retrieval_contract=build_retrieval_contract(profile),
        contract_sha256=digest,
        skill_slugs=flow_skill_slugs(flow),
    )
