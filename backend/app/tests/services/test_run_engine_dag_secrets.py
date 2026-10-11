"""Flow ``secret`` nodes: grants by reference, validator checks and no-leak guarantees."""

from __future__ import annotations

import base64
import json
import uuid

import pytest

from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chains.dag_validator import validate_flow, validate_flow_secrets
from app.services.run_engine import engine as engine_module
from app.services.run_engine import secret_grants
from app.services.run_engine.agent_loop import build_decide_prompt
from app.services.run_engine.dag import WalkerState, _without_secret_values, execute_run_dag
from app.services.secrets import SecretRegistryError, SecretValue, create
from app.services.secrets.backends.base import reset_backends

PLAIN = "sk-flow-secret-7f3a9c"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("SECRET_REGISTRY_FERNET_KEY", base64.urlsafe_b64encode(b"f" * 32).decode())
    reset_backends()
    yield
    reset_backends()


@pytest.fixture()
def ws(db_session):
    workspace = Workspace(
        id=f"ws-{uuid.uuid4().hex[:8]}", slug=f"s-{uuid.uuid4().hex[:8]}", name="W"
    )
    db_session.add(workspace)
    db_session.commit()
    create(
        db_session,
        scope="workspace",
        name="api-key",
        value=PLAIN,
        actor="test",
        workspace_id=workspace.id,
    )
    db_session.add(
        Skill(
            id=str(uuid.uuid4()),
            slug="secret_echo",
            name="secret_echo",
            pricing={"unit_price": 0.0},
            execution={"mode": "sync", "timeout_ms": 1000},
        )
    )
    db_session.commit()
    return workspace


def _flow(binding_slot="api_key", extra_nodes=(), extra_edges=()):
    return {
        "nodes": [
            {"id": "entry", "kind": "source"},
            {
                "id": "key",
                "kind": "secret",
                "config": {
                    "secret_ref": "secret://workspace/api-key",
                    "bindings": {"call": binding_slot},
                },
            },
            {"id": "call", "kind": "task", "config": {"skill_slug": "secret_echo"}},
            {"id": "out", "kind": "sink"},
            *extra_nodes,
        ],
        "edges": [
            {"from": "entry", "to": "call"},
            {"from": "key", "to": "call"},
            {"from": "call", "to": "out"},
            *extra_edges,
        ],
    }


def _start(db, workspace, flow, monkeypatch, skill):
    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda slug: skill
        if slug == "secret_echo"
        else (_ for _ in ()).throw(NotImplementedError()),
    )
    skill_row = db.query(Skill).filter(Skill.slug == "secret_echo").one()
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="s",
        objective="t",
        flow_definition=flow,
        skill_ids=[skill_row.id],
    )
    db.add(system)
    db.commit()
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        input_ref={"question": "hi"},
        status="pending",
    )
    run.flow_snapshot = flow
    db.add(run)
    db.commit()
    return run


def _persisted_text(db, run_id) -> str:
    db.expire_all()
    run = db.query(Run).filter(Run.id == run_id).one()
    invocations = db.query(SkillInvocation).filter(SkillInvocation.run_id == run_id).all()
    return json.dumps(
        {
            "checkpoints": run.checkpoints,
            "output": run.output_ref,
            "error": run.error,
            "invocations": [
                [i.input_ref, i.output_ref, i.error, i.trace, i.metrics] for i in invocations
            ],
        },
        default=str,
    )


@pytest.mark.asyncio
async def test_task_reads_granted_slot_and_nothing_leaks(db_session, ws, monkeypatch):
    seen: dict = {}

    async def skill(payload, ctx):
        grants = ctx["secrets"]
        seen["slots"] = grants.slots()
        seen["match"] = grants.get("api_key").reveal() == PLAIN
        with pytest.raises(SecretRegistryError) as exc:
            grants.get("other")
        seen["denied"] = exc.value.code
        seen["payload_has_secret"] = "secrets" in payload
        return {
            "echo": grants.get("api_key").reveal(),
            "header": f"Bearer {grants.get('api_key').reveal()}",
        }

    run = _start(db_session, ws, _flow(), monkeypatch, skill)
    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    assert seen == {
        "slots": ["api_key"],
        "match": True,
        "denied": "SECRET_NOT_GRANTED",
        "payload_has_secret": False,
    }
    text = _persisted_text(db_session, run.id)
    assert PLAIN not in text
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    assert invocation.output_ref == {"echo": "***", "header": "Bearer ***"}
    node_end = next(
        cp
        for cp in db_session.get(Run, run.id).checkpoints
        if cp.get("kind") == "node_end" and cp.get("node_id") == "key"
    )
    assert "secret://" not in json.dumps(node_end.get("output_preview") or {})


@pytest.mark.asyncio
async def test_secret_marker_is_the_only_pool_entry(db_session, ws, monkeypatch):
    captured: dict = {}

    async def skill(payload, ctx):
        captured["payload"] = dict(payload)
        return {"ok": True}

    run = _start(db_session, ws, _flow(), monkeypatch, skill)
    await execute_run_dag(run.id)
    assert "granted" not in captured["payload"]
    assert PLAIN not in json.dumps(captured["payload"])


@pytest.mark.asyncio
async def test_skill_error_message_is_redacted(db_session, ws, monkeypatch):
    async def skill(payload, ctx):
        raise RuntimeError(f"upstream rejected key {ctx['secrets'].get('api_key').reveal()}")

    run = _start(db_session, ws, _flow(), monkeypatch, skill)
    await execute_run_dag(run.id)
    text = _persisted_text(db_session, run.id)
    assert PLAIN not in text
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    assert invocation.status == "failed" and "***" in invocation.error


@pytest.mark.asyncio
async def test_unbound_task_gets_no_slot(db_session, ws, monkeypatch):
    seen: dict = {}

    async def skill(payload, ctx):
        seen["slots"] = ctx["secrets"].slots()
        return {}

    flow = _flow()
    flow["nodes"][1]["config"]["bindings"] = {"elsewhere": "api_key"}
    run = _start(db_session, ws, flow, monkeypatch, skill)
    await execute_run_dag(run.id)
    assert seen["slots"] == []


def test_ctx_cannot_forge_grants():
    assert secret_grants.secret_bindings_for({"nodes": [], "edges": []}, "call") == {}


def test_slot_conflict_fails_closed():
    flow = _flow(
        extra_nodes=[
            {
                "id": "key2",
                "kind": "secret",
                "config": {
                    "secret_ref": "secret://workspace/other",
                    "bindings": {"call": "api_key"},
                },
            }
        ],
        extra_edges=[{"from": "key2", "to": "call"}],
    )
    with pytest.raises(SecretRegistryError) as exc:
        secret_grants.secret_bindings_for(flow, "call")
    assert exc.value.code == "SECRET_SLOT_CONFLICT"


def test_walker_payload_and_sanitizers_mask_secrets():
    secret_grants.remember("run-x", SecretValue(PLAIN))
    try:
        state = WalkerState()
        state.node_outputs = {"a": {"v": f"x{PLAIN}y"}}
        state.ctx = {"leak": SecretValue(PLAIN), "note": PLAIN}
        state.pool.set_namespace("a", {"v": PLAIN})
        payload = json.dumps(state.to_payload())
        assert PLAIN not in payload

        clean = _without_secret_values(
            {"obj": SecretValue("zzzz-other"), "s": PLAIN, "api_key": "x"}
        )
        assert clean == {"obj": "***", "s": "***"}

        prompt = build_decide_prompt(
            goal={"q": PLAIN},
            observations=[{"tool": "x", "out": f"token={PLAIN}"}],
            visible_skills=[],
            budget={},
        )
        assert PLAIN not in prompt
    finally:
        secret_grants.forget("run-x")


def test_grants_object_is_not_serialisable():
    grants = secret_grants.SecretGrants(None, {"api_key": "secret://workspace/x"}, None)
    assert "secret://" not in repr(grants)
    with pytest.raises(TypeError):
        json.dumps({"g": grants})


def test_validator_structural_codes():
    flow = _flow()
    assert not [
        i for i in validate_flow(flow) if i.code.startswith("secret_") or i.level == "error"
    ]

    unbound = _flow()
    unbound["edges"] = [e for e in unbound["edges"] if e["from"] != "key"]
    codes = {i.code: i.level for i in validate_flow(unbound)}
    assert codes.get("secret_unbound") == "warn"
    assert "node_orphan" not in codes

    bad = _flow()
    bad["nodes"][1]["config"]["secret_ref"] = "not-a-ref"
    assert any(i.code == "secret_ref_invalid" and i.level == "error" for i in validate_flow(bad))


def test_validator_registry_codes(db_session, ws):
    system = System(id=str(uuid.uuid4()), workspace_id=ws.id, name="s", objective="t")
    db_session.add(system)
    skill_row = db_session.query(Skill).filter(Skill.slug == "secret_echo").one()
    skill_row.execution = {"mode": "sync", "secret_slots": ["token"]}
    db_session.commit()

    def codes(flow):
        return {
            i.code
            for i in validate_flow_secrets(
                db_session, flow, workspace_id=ws.id, system_id=system.id
            )
        }

    assert codes(_flow(binding_slot="token")) == set()
    assert codes(_flow(binding_slot="api_key")) == {"secret_slot_unknown"}

    unknown = _flow(binding_slot="token")
    unknown["nodes"][1]["config"]["secret_ref"] = "secret://workspace/missing"
    assert codes(unknown) == {"secret_unknown"}

    foreign = _flow(binding_slot="token")
    foreign["nodes"][1]["config"]["secret_ref"] = "secret://system/other-system/api-key"
    assert codes(foreign) == {"secret_scope_violation"}
