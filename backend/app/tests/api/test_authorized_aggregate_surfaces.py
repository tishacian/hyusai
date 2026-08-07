"""Indirect aggregates must never reintroduce denied runtime objects."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.v1.endpoints import impact, skills
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam import decision_plane


def _seed(db, attest_authorization_v2):
    workspace = Workspace(
        id="workspace-authorized-aggregates",
        slug="authorized-aggregates",
        name="Authorized aggregates",
    )
    user = User(id="aggregate-owner", username="aggregate-owner")
    other = User(id="aggregate-other", username="aggregate-other")
    skill = Skill(
        id="skill-authorized-aggregate",
        slug="authorized_aggregate_v1",
        name="Authorized aggregate",
    )
    capability = Capability(
        id="capability-authorized-aggregate",
        workspace_id=workspace.id,
        slug="authorized_aggregate",
        name="Authorized aggregate",
        skill_ids=[skill.id],
    )
    system = System(
        id="system-authorized-aggregate",
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Authorized aggregate",
        status="active",
    )
    now = datetime.utcnow()
    own_run = Run(
        id="run-authorized-aggregate-own",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        cost_internal=1.0,
        value_estimated=4.0,
        value_source="auto",
    )
    hidden_run = Run(
        id="run-authorized-aggregate-hidden",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="manual",
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        cost_internal=999.0,
        value_estimated=4_999.0,
        value_source="auto",
    )
    invocations = [
        SkillInvocation(
            id="invocation-authorized-aggregate-own",
            run_id=own_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=10.0,
            cost=0.25,
            cost_measured=True,
        ),
        SkillInvocation(
            id="invocation-authorized-aggregate-unmeasured",
            run_id=own_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=20.0,
            cost=777.0,
            cost_measured=False,
        ),
        SkillInvocation(
            id="invocation-authorized-aggregate-hidden",
            run_id=hidden_run.id,
            skill_id=skill.id,
            skill_slug=skill.slug,
            status="completed",
            latency_ms=9_999.0,
            cost=1_000.0,
            cost_measured=True,
        ),
    ]
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_contributor",
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    "capability.read": "enforce",
                    "system.read": "enforce",
                    "run.read": "enforce",
                    "skill_invocation.read": "enforce",
                },
            }
        },
    )
    db.add_all(
        [
            workspace,
            user,
            other,
            member,
            skill,
            capability,
            system,
            own_run,
            hidden_run,
            *invocations,
            config,
        ]
    )
    db.flush()
    attest_authorization_v2(
        config,
        [
            "capability.read",
            "system.read",
            "run.read",
            "skill_invocation.read",
        ],
    )
    db.commit()
    return workspace, user, capability, system, skill


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(impact.router, prefix="/impact")
    app.include_router(skills.router, prefix="/skills")
    for module in (impact, skills):
        app.dependency_overrides[module.get_current_workspace] = lambda: workspace
        app.dependency_overrides[module.get_current_user] = lambda: user
        app.dependency_overrides[module.get_db] = lambda: db
    return TestClient(app)


def test_impact_aggregates_only_runs_allowed_to_the_subject(
    db_session,
    attest_authorization_v2,
):
    workspace, user, capability, system, _skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    client = _client(db_session, workspace, user)

    portfolio = client.get("/impact/portfolio", params={"period": "rolling_30d"})
    by_capability = client.get(
        "/impact/by-capability",
        params={"period": "rolling_30d"},
    )
    by_system = client.get("/impact/by-system", params={"period": "rolling_30d"})

    assert portfolio.status_code == by_capability.status_code == by_system.status_code == 200
    assert portfolio.json()["runs_count"] == 1
    assert portfolio.json()["total_cost"] == 1.0
    assert by_capability.json()["items"] == [
        {
            **by_capability.json()["items"][0],
            "capability_id": capability.id,
            "runs_count": 1,
            "total_cost": 1.0,
        }
    ]
    assert by_system.json()["items"][0]["system_id"] == system.id
    assert by_system.json()["items"][0]["runs_count"] == 1
    assert by_system.json()["items"][0]["total_cost"] == 1.0
    assert "999" not in portfolio.text


def test_skill_catalog_runtime_metrics_compose_run_and_invocation_read(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _capability, _system, skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    response = _client(db_session, workspace, user).get("/skills")

    assert response.status_code == 200
    row = next(item for item in response.json()["skills"] if item["slug"] == skill.slug)
    assert row["metrics"] == {
        "calls": 2,
        "avg_latency_ms": 15.0,
        "total_cost": 0.25,
        "cost_state": "available",
        "cost_sample_count": 1,
        "success_rate": 1.0,
    }
    assert "9999" not in response.text
    assert "1000" not in response.text
    assert "777" not in response.text


def _bulk_seed(db, workspace, user, system, capability, skill, *, runs: int) -> None:
    """Add ``runs`` completed runs (2 invocations each) readable by ``user``."""
    now = datetime.utcnow()
    for index in range(runs):
        run = Run(
            id=f"run-bulk-{index}",
            workspace_id=workspace.id,
            initiated_by_user_id=user.id,
            system_id=system.id,
            capability_id=capability.id,
            status="completed",
            trigger="manual",
            started_at=now - timedelta(minutes=2),
            completed_at=now - timedelta(minutes=1),
        )
        db.add(run)
        for j in range(2):
            db.add(
                SkillInvocation(
                    id=f"invocation-bulk-{index}-{j}",
                    run_id=run.id,
                    skill_id=skill.id,
                    skill_slug=skill.slug,
                    status="completed",
                    latency_ms=10.0,
                    cost=0.1,
                    cost_measured=True,
                )
            )
    db.commit()


def _capture_selects(db, fn) -> list[str]:
    """Run ``fn`` and return every SELECT emitted on the session's engine."""
    engine = db.get_bind()
    statements: list[str] = []

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)
    return statements


def _count_selects(db, fn) -> int:
    return len(_capture_selects(db, fn))


def test_skill_metrics_query_count_is_constant_regardless_of_batch_size(
    db_session,
    attest_authorization_v2,
):
    """Regression test for the /skills N+1: per-row membership + IAM-config
    lookups used to make SELECT count grow linearly with the number of runs
    and invocations. The aggregate must preload them once per request."""
    workspace, user, capability, system, skill = _seed(
        db_session,
        attest_authorization_v2,
    )

    def _aggregate() -> None:
        response = _client(db_session, workspace, user).get("/skills")
        assert response.status_code == 200

    small = _count_selects(db_session, _aggregate)

    _bulk_seed(
        db_session,
        workspace,
        user,
        system,
        capability,
        skill,
        runs=40,
    )

    large = _count_selects(db_session, _aggregate)

    # The batch grew by 40 runs and 80 invocations; the SELECT count must not
    # grow with it.  Allow a small constant slack for catalog joins, but no
    # linear term (previously this would have added ~2*(40+80) lookups).
    assert large - small < 30, (
        f"SELECT count grew from {small} to {large} when adding 40 runs/80 "
        "invocations — the /skills aggregate reintroduced a per-row N+1"
    )


# Every JSON payload column on ``SkillInvocation``.  The aggregate reads six
# scalars per invocation and none of these, but selecting the whole entity
# still transferred and JSON-decoded all of them.
INVOCATION_PAYLOAD_COLUMNS = (
    "input_ref",
    "output_ref",
    "metrics",
    "trace",
    "execution_snapshot",
)


def test_skill_metrics_never_loads_invocation_payload_columns(
    db_session,
    attest_authorization_v2,
):
    """A constant SELECT count is not a constant amount of work.

    The aggregate used to fetch every JSON payload column of every invocation
    just to read ``skill_slug``/``status``/``latency_ms``/``cost``, which on a
    mature workspace meant decoding hundreds of megabytes of JSON that the
    response never uses — invisible to a statement counter.  Pin the projection
    so the payload cannot creep back in, and make sure pruning it was not
    traded for a per-row deferred column load.
    """
    workspace, user, capability, system, skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    _bulk_seed(
        db_session,
        workspace,
        user,
        system,
        capability,
        skill,
        runs=40,
    )

    def _aggregate() -> None:
        response = _client(db_session, workspace, user).get("/skills")
        assert response.status_code == 200

    statements = _capture_selects(db_session, _aggregate)
    touching_invocations = [
        statement for statement in statements if "skill_invocations" in statement
    ]
    assert touching_invocations, "the aggregate no longer queries skill_invocations"

    for statement in touching_invocations:
        for column in INVOCATION_PAYLOAD_COLUMNS:
            assert f"skill_invocations.{column}" not in statement, (
                f"the /skills aggregate loads skill_invocations.{column}; it "
                "only needs the metric scalars, and fetching the payload "
                "columns costs hundreds of MB of JSON decoding per request"
            )

    # A deferred column would be re-fetched one statement per row, trading the
    # payload cost for the N+1 the sibling test guards against.
    assert len(touching_invocations) == 1, (
        f"expected a single skill_invocations SELECT, got "
        f"{len(touching_invocations)} — a deferred column is being lazy-loaded"
    )


class _CountingManifests(dict):
    """Count how often the manifest registry is walked for canonicalisation."""

    def __init__(self, source):
        super().__init__(source)
        self.walks = 0

    def items(self):
        self.walks += 1
        return super().items()


def test_skill_metrics_digests_the_iam_policy_once_per_request(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    """``candidate_config_sha256`` is per-resolution but not per-resource.

    It canonicalises and hashes the whole manifest registry, which the
    aggregate then redid for every Run and SkillInvocation in the batch —
    seconds of pure CPU spent re-deriving one identical digest, and invisible
    to a statement counter because it issues no SQL.  The digest depends only
    on the workspace policy, so this work must not grow with the batch.
    """
    workspace, user, capability, system, skill = _seed(
        db_session,
        attest_authorization_v2,
    )
    _bulk_seed(
        db_session,
        workspace,
        user,
        system,
        capability,
        skill,
        runs=40,
    )

    counting = _CountingManifests(decision_plane.MANIFESTS)
    monkeypatch.setattr(decision_plane, "MANIFESTS", counting)
    # The memo is process-global, so an earlier test can leave it warm and drop
    # the count to zero — satisfying the bound below without ever exercising the
    # path it guards.  Start cold so the count means what it claims.
    decision_plane._candidate_config_sha256.cache_clear()
    response = _client(db_session, workspace, user).get("/skills")

    assert response.status_code == 200
    row = next(item for item in response.json()["skills"] if item["slug"] == skill.slug)
    # 42 runs and 82 invocations were authorized, so the digest was needed 124
    # times.  Deriving it more than once per distinct policy is wasted work.
    assert row["metrics"]["calls"] == 82
    assert counting.walks <= 2, (
        f"the manifest registry was canonicalised {counting.walks} times while "
        "resolving 124 resources — the /skills aggregate re-derives the IAM "
        "policy digest per row"
    )
