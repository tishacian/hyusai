"""Compile and enforce secret-free executable Flow contracts.

Published versions and Runs persist the returned document. Runtime validation
therefore never needs to resolve a mutable Skill catalogue after acceptance.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill
from app.services.flow_node_kind import is_flow_source_node
from app.services.flow_skill_binding import (
    FlowSkillBinding,
    FlowSkillBindingError,
    resolve_flow_skill_binding,
)

MAX_SCHEMA_BYTES = 256 * 1024
MAX_SCHEMA_DEPTH = 32
EXECUTION_CONTRACT_VERSION = 1
_INGRESS_KINDS = frozenset({"manual", "chat", "http", "schedule", "event"})
_CONTROL_OUTPUT_ADAPTERS = {
    "retry": "retry.v1",
    "loop": "loop.v1",
}
_EXECUTION_CONTRACT_RUNTIME_MODES = frozenset({"dag_strict", "dag_overlay", "sequential_legacy"})
_EXECUTION_CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "runtime_mode",
        "validation_mode",
        "ingresses",
        "nodes",
        "outputs",
        "contract_sha256",
    }
)


@dataclass(frozen=True)
class FlowContractError(ValueError):
    code: str
    message: str
    path: str | None = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path:
            payload["path"] = self.path
        return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _schema_depth(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_SCHEMA_DEPTH:
        return depth
    if isinstance(value, Mapping):
        return max([depth, *(_schema_depth(item, depth=depth + 1) for item in value.values())])
    if isinstance(value, list):
        return max([depth, *(_schema_depth(item, depth=depth + 1) for item in value)])
    return depth


def _assert_local_refs(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            current = (*path, str(key))
            if key == "$ref" and (not isinstance(item, str) or not item.startswith("#")):
                raise FlowContractError(
                    code="schema_remote_ref_forbidden",
                    message="Executable schemas may use local $ref values only.",
                    path="/" + "/".join(current),
                )
            _assert_local_refs(item, path=current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_local_refs(item, path=(*path, str(index)))


def validate_schema_definition(schema: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise FlowContractError(
            code="schema_invalid",
            message=f"{field} must be a JSON Schema object.",
            path=field,
        )
    detached = copy.deepcopy(dict(schema))
    try:
        encoded = _canonical_json(detached).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FlowContractError(
            code="schema_invalid",
            message=f"{field} is not JSON serialisable.",
            path=field,
        ) from exc
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise FlowContractError(
            code="schema_too_large",
            message=f"{field} exceeds {MAX_SCHEMA_BYTES} bytes.",
            path=field,
        )
    if _schema_depth(detached) > MAX_SCHEMA_DEPTH:
        raise FlowContractError(
            code="schema_too_deep",
            message=f"{field} exceeds nesting depth {MAX_SCHEMA_DEPTH}.",
            path=field,
        )
    _assert_local_refs(detached, path=(field,))
    try:
        Draft202012Validator.check_schema(detached)
    except Exception as exc:  # jsonschema exposes several SchemaError subclasses.
        raise FlowContractError(
            code="schema_invalid",
            message=f"{field} is not a valid JSON Schema 2020-12 document.",
            path=field,
        ) from exc
    return detached


def validate_payload(
    payload: Any,
    schema: Mapping[str, Any],
    *,
    code: str,
    subject: str,
) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    error: ValidationError = errors[0]
    path = "/" + "/".join(str(item) for item in error.absolute_path)
    raise FlowContractError(
        code=code,
        message=f"{subject} does not satisfy its executable schema.",
        path=path or "/",
    )


def _execution_contract_error(*, message: str, path: str) -> FlowContractError:
    return FlowContractError(
        code="execution_contract_invalid",
        message=message,
        path=path,
    )


def _contract_identity(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _execution_contract_error(
            message=f"{path} must be a non-empty, already-trimmed string.",
            path=path,
        )
    return value


def _validate_frozen_schema(
    item: Mapping[str, Any],
    *,
    schema_key: str,
    hash_key: str,
    path: str,
) -> None:
    schema_path = f"{path}/{schema_key}"
    try:
        schema = validate_schema_definition(item.get(schema_key), field=schema_path)
    except FlowContractError as exc:
        raise _execution_contract_error(
            message=f"{schema_path} is not a valid frozen executable schema.",
            path=exc.path or schema_path,
        ) from exc
    schema_sha256 = item.get(hash_key)
    if not isinstance(schema_sha256, str) or schema_sha256 != canonical_sha256(schema):
        raise _execution_contract_error(
            message=f"{path}/{hash_key} does not match its frozen schema.",
            path=f"{path}/{hash_key}",
        )


def _validate_frozen_executor(node: Mapping[str, Any], *, path: str) -> None:
    """Check the shape of a frozen authored runtime, not its admissibility.

    Whether the named kind still exists and its parameters are still allowed is
    re-decided by ``skills_registry.bind_executor`` on every dispatch, so a
    binding the platform has since withdrawn fails closed there rather than
    becoming executable by virtue of having been frozen. Keeping the check
    structural also keeps this module free of the registry it validates for.
    """

    executor = node.get("executor")
    if not isinstance(executor, Mapping) or set(executor) != {"kind", "params"}:
        raise _execution_contract_error(
            message="A frozen executor must declare exactly a kind and its params.",
            path=f"{path}/executor",
        )
    _contract_identity(executor.get("kind"), path=f"{path}/executor/kind")
    if not isinstance(executor.get("params"), Mapping):
        raise _execution_contract_error(
            message="Frozen executor params must be a JSON object.",
            path=f"{path}/executor/params",
        )
    digest = node.get("skill_definition_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise _execution_contract_error(
            message="A frozen authored node must carry its Skill definition digest.",
            path=f"{path}/skill_definition_sha256",
        )


def skill_definition_sha256(
    *,
    input_schema: Any,
    output_schema: Any,
    executor: Any,
) -> str:
    """Digest the part of a Skill row that publication freezes.

    Identity comes from the payload rather than from ``Skill.version``, which
    authoring never bumps, for the reason 522632e0 established for published
    versions: a column nobody writes answers "unchanged" for exactly the rows
    the question exists to catch.
    """

    return canonical_sha256(
        {
            "input_schema": input_schema,
            "output_schema": output_schema,
            "executor": executor,
        }
    )


def validate_execution_contract(value: Any) -> dict[str, Any]:
    """Validate one immutable execution contract without mutable lookups.

    The outer digest alone proves only that a JSON document is self-consistent;
    it does not prove that the document still has executable semantics.  This
    validator therefore checks the complete v1 shape and every frozen schema
    digest before a published version can be used to create a Run.
    """

    if not isinstance(value, Mapping):
        raise _execution_contract_error(
            message="The execution contract must be a JSON object.",
            path="/",
        )
    try:
        contract = copy.deepcopy(dict(value))
    except Exception as exc:
        raise _execution_contract_error(
            message="The execution contract could not be detached safely.",
            path="/",
        ) from exc

    if set(contract) - {"brd_origin", "control_policy_snapshot"} != _EXECUTION_CONTRACT_KEYS:
        raise _execution_contract_error(
            message="The execution contract has missing or unknown top-level fields.",
            path="/",
        )
    pinned_sha256 = contract.pop("contract_sha256", None)
    try:
        computed_sha256 = canonical_sha256(contract)
    except (TypeError, ValueError) as exc:
        raise _execution_contract_error(
            message="The execution contract is not canonical JSON.",
            path="/",
        ) from exc
    if not isinstance(pinned_sha256, str) or pinned_sha256 != computed_sha256:
        raise _execution_contract_error(
            message="The execution contract digest does not match its payload.",
            path="/contract_sha256",
        )

    if "brd_origin" in contract:
        origin = contract["brd_origin"]
        fields = {"document_id", "document_sha256", "proposal_id", "proposal_sha256"}
        valid = isinstance(origin, dict) and set(origin) == fields
        if valid:
            try:
                valid = all(
                    str(UUID(origin[key])) == origin[key] for key in ("document_id", "proposal_id")
                )
                valid = valid and all(
                    isinstance(origin[key], str)
                    and len(origin[key]) == 64
                    and all(c in "0123456789abcdef" for c in origin[key])
                    for key in ("document_sha256", "proposal_sha256")
                )
            except (ValueError, TypeError, AttributeError):
                valid = False
        if not valid:
            raise _execution_contract_error(
                message="The BRD origin must contain canonical references and SHA-256 digests.",
                path="/brd_origin",
            )

    schema_version = contract.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != EXECUTION_CONTRACT_VERSION
    ):
        raise _execution_contract_error(
            message="The execution contract schema version is unsupported.",
            path="/schema_version",
        )
    runtime_mode = contract.get("runtime_mode")
    if not isinstance(runtime_mode, str) or runtime_mode not in _EXECUTION_CONTRACT_RUNTIME_MODES:
        raise _execution_contract_error(
            message="The execution contract runtime mode is invalid.",
            path="/runtime_mode",
        )
    expected_validation_mode = "enforce" if runtime_mode == "dag_strict" else "observe"
    if contract.get("validation_mode") != expected_validation_mode:
        raise _execution_contract_error(
            message="The execution contract validation mode contradicts its runtime mode.",
            path="/validation_mode",
        )

    ingresses = contract.get("ingresses")
    if not isinstance(ingresses, list):
        raise _execution_contract_error(
            message="The execution contract ingresses must be an array.",
            path="/ingresses",
        )
    ingress_ids: set[str] = set()
    for index, raw_ingress in enumerate(ingresses):
        path = f"/ingresses/{index}"
        if not isinstance(raw_ingress, Mapping):
            raise _execution_contract_error(
                message="Every execution contract ingress must be an object.",
                path=path,
            )
        ingress = dict(raw_ingress)
        if set(ingress) != {
            "ingress_id",
            "source_node_id",
            "kind",
            "input_schema",
            "input_schema_sha256",
        }:
            raise _execution_contract_error(
                message="The execution contract ingress has missing or unknown fields.",
                path=path,
            )
        ingress_id = _contract_identity(ingress.get("ingress_id"), path=f"{path}/ingress_id")
        source_node_id = _contract_identity(
            ingress.get("source_node_id"), path=f"{path}/source_node_id"
        )
        if ingress_id != source_node_id:
            raise _execution_contract_error(
                message="An ingress must be bound to its frozen source node.",
                path=f"{path}/source_node_id",
            )
        if ingress_id in ingress_ids:
            raise _execution_contract_error(
                message="Execution contract ingress ids must be unique.",
                path=f"{path}/ingress_id",
            )
        ingress_ids.add(ingress_id)
        ingress_kind = ingress.get("kind")
        if not isinstance(ingress_kind, str) or ingress_kind not in _INGRESS_KINDS:
            raise _execution_contract_error(
                message="The execution contract ingress kind is invalid.",
                path=f"{path}/kind",
            )
        _validate_frozen_schema(
            ingress,
            schema_key="input_schema",
            hash_key="input_schema_sha256",
            path=path,
        )
    if [item.get("ingress_id") for item in ingresses] != sorted(ingress_ids):
        raise _execution_contract_error(
            message="Execution contract ingresses must be canonically ordered.",
            path="/ingresses",
        )

    nodes = contract.get("nodes")
    if not isinstance(nodes, Mapping):
        raise _execution_contract_error(
            message="The execution contract nodes must be an object.",
            path="/nodes",
        )
    base_node_keys = {
        "skill_id",
        "skill_slug",
        "skill_version",
        "input_schema",
        "output_schema",
        "input_schema_sha256",
        "output_schema_sha256",
        "provider_json_schema",
    }
    adapter_node_keys = {
        "output_adapter",
        "invocation_output_schema",
        "invocation_output_schema_sha256",
    }
    authored_node_keys = {"executor", "skill_definition_sha256"}
    for raw_node_id, raw_node in nodes.items():
        node_id = _contract_identity(raw_node_id, path="/nodes")
        path = f"/nodes/{node_id}"
        if not isinstance(raw_node, Mapping):
            raise _execution_contract_error(
                message="Every execution contract node must be an object.",
                path=path,
            )
        node = dict(raw_node)
        node_keys = set(node)
        has_adapter = "output_adapter" in node
        # Seeded Skills dispatch through the hardcoded registry and freeze no
        # executor, so contracts compiled before authoring existed keep exactly
        # the key set they were digested with.
        has_executor = "executor" in node
        expected_keys = (
            base_node_keys
            | (adapter_node_keys if has_adapter else set())
            | (authored_node_keys if has_executor else set())
            | ({"skill_allowlist"} if "skill_allowlist" in node else set())
            | ({"tool_contract"} if "tool_contract" in node else set())
        )
        if node_keys != expected_keys:
            raise _execution_contract_error(
                message="The execution contract node has missing or unknown fields.",
                path=path,
            )
        if "skill_allowlist" in node:
            allowlist = node["skill_allowlist"]
            if (
                not isinstance(allowlist, list)
                or not 1 <= len(allowlist) <= 8
                or any(
                    not isinstance(item, str) or not item.strip() or item != item.strip()
                    for item in allowlist
                )
            ):
                raise _execution_contract_error(
                    message="An AgentLoop tool allowlist must contain one to eight Skill slugs.",
                    path=f"{path}/skill_allowlist",
                )
        if "tool_contract" in node:
            tools = node["tool_contract"]
            tool_nodes = tools.get("nodes") if isinstance(tools, Mapping) else None
            if (
                "skill_allowlist" not in node
                or not isinstance(tool_nodes, Mapping)
                or set(tool_nodes) != set(node.get("skill_allowlist", []))
                or any(
                    not isinstance(tool, Mapping)
                    or "tool_contract" in tool
                    or "skill_allowlist" in tool
                    or tool.get("skill_slug") != slug
                    for slug, tool in tool_nodes.items()
                )
                or tools.get("ingresses") != []
                or tools.get("outputs") != []
            ):
                raise _execution_contract_error(
                    message="Frozen tools must exactly match the AgentLoop allowlist.",
                    path=f"{path}/tool_contract",
                )
            validate_execution_contract(tools)
        if has_executor:
            _validate_frozen_executor(node, path=path)
        for field in ("skill_id", "skill_slug", "skill_version"):
            _contract_identity(node.get(field), path=f"{path}/{field}")
        if not isinstance(node.get("provider_json_schema"), bool):
            raise _execution_contract_error(
                message="provider_json_schema must be a JSON boolean.",
                path=f"{path}/provider_json_schema",
            )
        _validate_frozen_schema(
            node,
            schema_key="input_schema",
            hash_key="input_schema_sha256",
            path=path,
        )
        _validate_frozen_schema(
            node,
            schema_key="output_schema",
            hash_key="output_schema_sha256",
            path=path,
        )
        if has_adapter:
            if node.get("output_adapter") not in _CONTROL_OUTPUT_ADAPTERS.values():
                raise _execution_contract_error(
                    message="The execution contract output adapter is invalid.",
                    path=f"{path}/output_adapter",
                )
            _validate_frozen_schema(
                node,
                schema_key="invocation_output_schema",
                hash_key="invocation_output_schema_sha256",
                path=path,
            )

    outputs = contract.get("outputs")
    if not isinstance(outputs, list):
        raise _execution_contract_error(
            message="The execution contract outputs must be an array.",
            path="/outputs",
        )
    output_ids: set[str] = set()
    for index, raw_output in enumerate(outputs):
        path = f"/outputs/{index}"
        if not isinstance(raw_output, Mapping):
            raise _execution_contract_error(
                message="Every execution contract output must be an object.",
                path=path,
            )
        output = dict(raw_output)
        if set(output) != {"node_id", "schema", "schema_sha256"}:
            raise _execution_contract_error(
                message="The execution contract output has missing or unknown fields.",
                path=path,
            )
        node_id = _contract_identity(output.get("node_id"), path=f"{path}/node_id")
        if node_id in output_ids:
            raise _execution_contract_error(
                message="Execution contract output node ids must be unique.",
                path=f"{path}/node_id",
            )
        output_ids.add(node_id)
        _validate_frozen_schema(
            output,
            schema_key="schema",
            hash_key="schema_sha256",
            path=path,
        )
    if [item.get("node_id") for item in outputs] != sorted(output_ids):
        raise _execution_contract_error(
            message="Execution contract outputs must be canonically ordered.",
            path="/outputs",
        )
    if runtime_mode == "dag_strict" and len(outputs) != 1:
        raise _execution_contract_error(
            message="A strict execution contract must freeze exactly one output.",
            path="/outputs",
        )

    if "control_policy_snapshot" in contract:
        from app.services.control_policy_snapshot import validate_frozen_control_policy

        try:
            validate_frozen_control_policy(contract["control_policy_snapshot"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise _execution_contract_error(
                message="The frozen control policy is invalid.",
                path="/control_policy_snapshot",
            ) from exc
    contract["contract_sha256"] = pinned_sha256
    return contract


def _ports_schema(raw_ports: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    if isinstance(raw_ports, list):
        for raw in raw_ports:
            if not isinstance(raw, Mapping):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name:
                continue
            primitive = raw.get("schema")
            schema = (
                {"type": primitive}
                if primitive in {"string", "number", "integer", "boolean", "object", "array"}
                else {}
            )
            properties[name] = schema
            if raw.get("required") is True:
                required.append(name)
    result: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        result["required"] = sorted(required)
    return result


def _positive_int(value: Any) -> int | None:
    """Return a positive integer budget without accepting JSON booleans."""

    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _adapted_skill_output_schema(
    *,
    kind: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the stable public output emitted by a control-node adapter.

    A retry/loop invokes a Skill, but its node output is not the raw Skill
    output.  The immutable execution contract records both surfaces: this
    schema describes the adapted node output while ``invocation_output_schema``
    retains the exact catalogue schema used for each completed invocation.
    """

    if kind == "retry":
        attempts_schema: dict[str, Any] = {"type": "integer", "minimum": 1}
        max_attempts = _positive_int(config.get("max_attempts"))
        if max_attempts is not None:
            attempts_schema["maximum"] = max_attempts
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "_retry_attempts": attempts_schema,
                "_status": {"type": "string", "enum": ["completed", "failed"]},
                "_error": {"type": ["string", "null"]},
            },
            "required": ["_retry_attempts", "_status"],
            # Mapping results remain flattened for backward compatibility;
            # their exact pre-adaptation value is enforced independently.
            "additionalProperties": True,
        }

    if kind == "loop":
        iteration_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 0},
                "status": {
                    "type": "string",
                    "enum": ["completed", "failed", "skipped", "blocked", "noop"],
                },
                "output": {},
            },
            "required": ["index", "status", "output"],
            "additionalProperties": False,
        }
        iterations_schema: dict[str, Any] = {
            "type": "array",
            "items": iteration_schema,
        }
        count_schema: dict[str, Any] = {"type": "integer", "minimum": 0}
        max_iterations = _positive_int(config.get("max_iterations"))
        if max_iterations is not None:
            iterations_schema["maxItems"] = max_iterations
            count_schema["maximum"] = max_iterations
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "iterations": iterations_schema,
                "count": count_schema,
            },
            "required": ["iterations", "count"],
            "additionalProperties": False,
        }

    raise ValueError(f"Unsupported control-node output adapter: {kind}")


def _ingress_kind(node: Mapping[str, Any]) -> str | None:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    explicit = config.get("ingress_kind")
    # Only executable source nodes can be adapter entry points.  Typed
    # declarative assets such as ``type=source.collection, kind=asset`` are
    # graph context, not externally invokable ingresses.
    is_source = is_flow_source_node(node)
    if explicit is not None:
        if not isinstance(explicit, str) or explicit not in _INGRESS_KINDS:
            raise FlowContractError(
                code="ingress_kind_invalid",
                message="Ingress kind must be manual, chat, http, schedule or event.",
                path=f"nodes/{node.get('id')}/config/ingress_kind",
            )
        if not is_source:
            raise FlowContractError(
                code="ingress_node_kind_invalid",
                message="Only a source node can declare an ingress kind.",
                path=f"nodes/{node.get('id')}/kind",
            )
        return explicit
    if not is_source:
        return None
    node_type = str(node.get("type") or "")
    if node_type == "source.webhook":
        return "http"
    if node_type == "source.schedule":
        return "schedule"
    # ``type=input`` is the documented reasoning-plane entry port: the trigger
    # registry excludes it precisely because it is a chat surface rather than an
    # event (``run_engine.triggers.TRIGGER_TYPE_TO_EVENT``).  Keying this on the
    # role rather than on one node id matters because the seeded chat System
    # names the port ``chat.request``, not ``source.request``.
    if node_type == "input":
        return "chat"
    if node_type.startswith("source."):
        return "event"
    return "manual"


def _skill_lookup(
    db: DBSession,
    *,
    workspace_id: str | None,
    skill_ids: set[str],
    skill_slugs: set[str],
) -> tuple[dict[str, Skill], dict[str, Skill]]:
    if not skill_ids and not skill_slugs:
        return {}, {}
    rows = (
        db.query(Skill)
        .filter(
            or_(Skill.id.in_(skill_ids), Skill.slug.in_(skill_slugs)),
            or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None)),
        )
        .all()
    )
    return ({row.id: row for row in rows}, {row.slug: row for row in rows})


def compile_execution_contract(
    db: DBSession,
    *,
    flow: Mapping[str, Any],
    workspace_id: str | None,
    runtime_mode: str,
    allowed_skill_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Compile immutable ingress/node/output schemas for one accepted Flow."""
    from app.services.flow_data_sources import data_source_issues

    source_issues = data_source_issues(flow)
    if source_issues:
        node_id, code = source_issues[0]
        raise FlowContractError(
            code="data_source_invalid", message=code, path=f"nodes/{node_id}/config"
        )
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    raw_edges = flow.get("edges") if isinstance(flow.get("edges"), list) else []
    if flow.get("io_mode") == "strict":
        sink_ids = sorted(
            str(node.get("id") or "").strip()
            for node in nodes
            if isinstance(node, Mapping)
            and str(node.get("kind") or "task") == "sink"
            and str(node.get("id") or "").strip()
        )
        if not sink_ids:
            raise FlowContractError(
                code="flow_output_sink_required",
                message="A strict Flow must declare exactly one explicit sink node.",
                path="outputs",
            )
        if len(sink_ids) > 1:
            raise FlowContractError(
                code="flow_output_sink_ambiguous",
                message=(
                    "A strict Flow must declare exactly one explicit sink node; "
                    f"found {len(sink_ids)}."
                ),
                path="outputs",
            )
    inbound_node_ids = {
        str(edge.get("to") or edge.get("target") or "").strip()
        for edge in raw_edges
        if isinstance(edge, Mapping)
    }
    skill_ids: set[str] = set()
    skill_slugs: set[str] = set()
    resolved_nodes: list[tuple[Mapping[str, Any], FlowSkillBinding]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        node_ref = str(node.get("id") or index).strip()
        try:
            binding = resolve_flow_skill_binding(node)
        except FlowSkillBindingError as exc:
            raise FlowContractError(
                code=exc.code,
                message=f"{exc.message} Node {node_ref!r}.",
                path=f"nodes/{node_ref}",
            ) from exc
        resolved_nodes.append((node, binding))
        if binding.skill_id is not None:
            skill_ids.add(binding.skill_id)
        if binding.skill_slug is not None:
            skill_slugs.add(binding.skill_slug)
    by_id, by_slug = _skill_lookup(
        db,
        workspace_id=workspace_id,
        skill_ids=skill_ids,
        skill_slugs=skill_slugs,
    )

    ingress_contracts: list[dict[str, Any]] = []
    node_contracts: dict[str, Any] = {}
    output_contracts: list[dict[str, Any]] = []
    for node, binding in resolved_nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
        if "prompt_template_override" in config:
            if not (binding.skill_id or binding.skill_slug):
                raise FlowContractError(
                    code="node_override_unsupported",
                    message="Template overrides require an authored Skill.",
                    path=f"nodes/{node_id}/config/prompt_template_override",
                )
        kind = _ingress_kind(node)
        if kind:
            if node_id in inbound_node_ids:
                raise FlowContractError(
                    code="ingress_source_not_root",
                    message="An executable ingress source cannot have inbound edges.",
                    path=f"nodes/{node_id}",
                )
            raw_schema = config.get("input_schema")
            schema = validate_schema_definition(
                raw_schema
                if isinstance(raw_schema, Mapping)
                else _ports_schema(node.get("outputs")),
                field=f"ingresses.{node_id}.input_schema",
            )
            ingress_contracts.append(
                {
                    "ingress_id": node_id,
                    "source_node_id": node_id,
                    "kind": kind,
                    "input_schema": schema,
                    "input_schema_sha256": canonical_sha256(schema),
                }
            )

        raw_skill_id = binding.skill_id
        raw_skill_slug = binding.skill_slug
        skill_by_id = by_id.get(raw_skill_id) if raw_skill_id is not None else None
        skill_by_slug = by_slug.get(raw_skill_slug) if raw_skill_slug is not None else None
        if raw_skill_id is not None and raw_skill_slug is not None:
            if skill_by_id is None or skill_by_slug is None or skill_by_id.id != skill_by_slug.id:
                raise FlowContractError(
                    code="skill_contract_mismatch",
                    message=f"Skill id and slug disagree for node {node_id!r}.",
                    path=f"nodes/{node_id}",
                )
        skill = skill_by_id or skill_by_slug
        if raw_skill_id is not None or raw_skill_slug is not None:
            if skill is None:
                raise FlowContractError(
                    code="skill_contract_missing",
                    message=f"Skill contract for node {node_id!r} is unavailable.",
                    path=f"nodes/{node_id}",
                )
            if allowed_skill_ids is not None and skill.id not in allowed_skill_ids:
                raise FlowContractError(
                    code="skill_not_bound_to_system",
                    message=f"Skill contract for node {node_id!r} is not bound to the System.",
                    path=f"nodes/{node_id}",
                )
            input_schema = validate_schema_definition(
                skill.input_schema or {}, field=f"nodes.{node_id}.input_schema"
            )
            output_schema = validate_schema_definition(
                skill.output_schema or {}, field=f"nodes.{node_id}.output_schema"
            )
            node_kind = str(node.get("kind") or "task")
            output_adapter = _CONTROL_OUTPUT_ADAPTERS.get(node_kind)
            public_output_schema = output_schema
            if output_adapter is not None:
                public_output_schema = validate_schema_definition(
                    _adapted_skill_output_schema(
                        kind=node_kind,
                        config=config,
                    ),
                    field=f"nodes.{node_id}.adapted_output_schema",
                )
            declared_output_schema = config.get("output_schema")
            if isinstance(declared_output_schema, Mapping):
                if output_adapter is not None:
                    raise FlowContractError(
                        code="node_output_schema_not_overridable",
                        message=(
                            f"Node {node_id!r} publishes a control envelope; its output "
                            "schema is derived from the adapter, not authored."
                        ),
                        path=f"nodes/{node_id}/config/output_schema",
                    )
                public_output_schema = validate_schema_definition(
                    declared_output_schema,
                    field=f"nodes.{node_id}.output_schema",
                )
            execution = skill.execution if isinstance(skill.execution, Mapping) else {}
            capabilities = execution.get("capabilities")
            provider_json_schema = bool(
                execution.get("provider_json_schema") is True
                or isinstance(capabilities, Sequence)
                and not isinstance(capabilities, str | bytes)
                and "provider_json_schema" in capabilities
            )
            node_contracts[node_id] = {
                "skill_id": skill.id,
                "skill_slug": skill.slug,
                "skill_version": skill.version,
                "input_schema": input_schema,
                "output_schema": public_output_schema,
                "input_schema_sha256": canonical_sha256(input_schema),
                "output_schema_sha256": canonical_sha256(public_output_schema),
                "provider_json_schema": provider_json_schema,
            }
            if output_adapter is not None:
                node_contracts[node_id].update(
                    {
                        "output_adapter": output_adapter,
                        "invocation_output_schema": output_schema,
                        "invocation_output_schema_sha256": canonical_sha256(output_schema),
                    }
                )
            # An authored Skill's runtime lives on its own mutable row, so a
            # published node that resolved it live would change behaviour on an
            # edit to the catalog with no new version. Freeze the binding; the
            # edit reaches production only through the next Publish.
            if "prompt_template_override" in config and (
                not isinstance(skill.executor, Mapping) or skill.workspace_id != workspace_id
            ):
                raise FlowContractError(
                    code="node_override_unsupported",
                    message="Template overrides require a workspace-owned authored Skill.",
                    path=f"nodes/{node_id}/config/prompt_template_override",
                )
            if isinstance(skill.executor, Mapping):
                from app.services.flow_node_overrides import override_executor

                try:
                    frozen_executor = override_executor(dict(skill.executor), config)
                except ValueError as exc:
                    raise FlowContractError(
                        code="node_override_invalid",
                        message=str(exc),
                        path=f"nodes/{node_id}/config/prompt_template_override",
                    ) from exc
                node_contracts[node_id].update(
                    {
                        "executor": frozen_executor,
                        "skill_definition_sha256": skill_definition_sha256(
                            input_schema=input_schema,
                            output_schema=output_schema,
                            executor=frozen_executor,
                        ),
                    }
                )
            if str(node.get("kind") or "") == "agent_loop":
                raw_allowlist = config.get("skill_allowlist") or []
                allowlist = [
                    str(item).strip()
                    for item in raw_allowlist
                    if isinstance(item, str) and item.strip()
                ][:8]
                node_contracts[node_id]["skill_allowlist"] = allowlist
                if not allowlist:
                    raise FlowContractError(
                        code="agent_loop_allowlist_empty",
                        message=f"AgentLoop {node_id!r} published with an empty skill_allowlist.",
                        path=f"nodes/{node_id}/config/skill_allowlist",
                    )

                node_contracts[node_id]["tool_contract"] = compile_execution_contract(
                    db,
                    workspace_id=workspace_id,
                    runtime_mode=runtime_mode,
                    allowed_skill_ids=allowed_skill_ids,
                    flow={
                        "nodes": [
                            {"id": slug, "kind": "task", "config": {"skill_slug": slug}}
                            for slug in allowlist
                        ],
                        "edges": [],
                    },
                )

        if str(node.get("kind") or "") == "sink":
            raw_schema = config.get("output_schema")
            schema = validate_schema_definition(
                raw_schema
                if isinstance(raw_schema, Mapping)
                else _ports_schema(node.get("inputs")),
                field=f"outputs.{node_id}.schema",
            )
            output_contracts.append(
                {
                    "node_id": node_id,
                    "schema": schema,
                    "schema_sha256": canonical_sha256(schema),
                }
            )

    contract: dict[str, Any] = {
        "schema_version": EXECUTION_CONTRACT_VERSION,
        "runtime_mode": runtime_mode,
        "validation_mode": "enforce" if runtime_mode == "dag_strict" else "observe",
        "ingresses": sorted(ingress_contracts, key=lambda item: item["ingress_id"]),
        "nodes": {key: node_contracts[key] for key in sorted(node_contracts)},
        "outputs": sorted(output_contracts, key=lambda item: item["node_id"]),
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def contract_ingress(
    contract: Mapping[str, Any],
    ingress_id: str,
) -> Mapping[str, Any]:
    ingresses = contract.get("ingresses")
    if isinstance(ingresses, list):
        for ingress in ingresses:
            if isinstance(ingress, Mapping) and ingress.get("ingress_id") == ingress_id:
                return ingress
    raise FlowContractError(
        code="ingress_unknown",
        message="The requested ingress is not part of the published execution contract.",
        path=f"ingresses/{ingress_id}",
    )
