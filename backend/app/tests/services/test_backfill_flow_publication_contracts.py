"""Classification contract of the published-contract backfill script.

The window this script serves has no room for a green report that repaired
nothing, so the cases pinned here are the ones production actually exhibits:
a migration baseline reused without its ``flow_sha256``, a published contract
frozen by an older compiler that names no ingress at all, and a draft that has
genuinely moved ahead and must never be published on an operator's behalf.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

import pytest

from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services import flow_contracts
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication
from scripts import backfill_flow_publication_contracts as backfill


def _flow(label: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "io_mode": "overlay",
        "label": label,
        "nodes": [
            {
                "id": "manual",
                "kind": "source",
                "config": {
                    "input_schema": {
                        "type": "object",
                        "properties": {"case": {"type": "string"}},
                        "required": ["case"],
                        "additionalProperties": False,
                    }
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual", "to": "result", "kind": "data"}],
    }


def _workspace(db) -> Workspace:
    row = Workspace(
        id=str(uuid.uuid4()),
        name="Contract backfill",
        slug=f"contract-backfill-{uuid.uuid4().hex[:8]}",
    )
    db.add(row)
    db.commit()
    return row


def _published_system(db, workspace: Workspace, *, label: str = "baseline") -> System:
    """A System whose pointer is executable, as an explicit Publish leaves it."""

    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=f"System {label}",
        objective="test",
        status="active",
        settings={},
        skill_ids=[],
        flow_definition=_flow(label),
        created_by="seed",
    )
    db.add(system)
    db.commit()
    flow_publication.initialize_publication_state(
        db, system=system, workspace=workspace, actor="seed"
    )
    db.commit()
    db.refresh(system)
    return system


def _as_vacuous_published_contract(db, system: System) -> SystemVersion:
    """Freeze the contract an older compiler produced for a legacy graph.

    Structurally valid, self-consistent digest, and it names nothing: this is
    the shape the 8 August canary published, and every dispatch adapter refuses
    it with ``FLOW_INGRESS_KIND_UNAVAILABLE``. Freezing is the point of a
    published version, so no compiler fix reaches this row on its own.
    """

    version = db.get(SystemVersion, system.published_flow_version_id)
    contract = {
        "schema_version": flow_contracts.EXECUTION_CONTRACT_VERSION,
        "runtime_mode": version.execution_contract["runtime_mode"],
        "validation_mode": version.execution_contract["validation_mode"],
        "ingresses": [],
        "nodes": {},
        "outputs": [],
    }
    contract["contract_sha256"] = flow_contracts.canonical_sha256(contract)
    version.execution_contract = contract
    db.commit()
    return version


def _as_reused_077_baseline(db, system: System) -> SystemVersion:
    """Reshape the pointer into what migration 077 left on 16 production rows.

    077 reused an exact historical snapshot as the published version, so the row
    carries neither the contract Alembic cannot compile nor the ``flow_sha256``
    the column had only just gained. The draft keeps its digest.
    """

    version = db.get(SystemVersion, system.published_flow_version_id)
    version.execution_contract = None
    version.flow_sha256 = None
    db.commit()
    return version


def test_reused_baseline_without_a_digest_is_planned_for_publish(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    _as_reused_077_baseline(db_session, system)

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "publish"
    assert item["publication_kind"] == "initial"
    assert item["defects"] == ["execution_contract_missing", "flow_sha256_missing"]
    # The defect that used to hide these rows: a NULL digest read as "the draft
    # moved ahead", so the whole repairable set was reported as skipped.
    assert "reason" not in item
    assert "apply_risk" not in item


def test_draft_moved_ahead_is_skipped_even_without_a_stored_digest(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    _as_reused_077_baseline(db_session, system)
    flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=_flow("editor-edit"),
        expected_revision=1,
        actor="editor@example.invalid",
    )
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "skipped"
    assert item["reason"] == "draft differs from the published version; publish it by hand"
    assert item["draft_revision"] == 2


def test_executable_pointer_is_already_pinned(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)

    item = backfill._plan(db_session, system, workspace)

    assert item == {"system_id": system.id, "status": "active", "action": "already_pinned"}


def test_missing_pointer_is_skipped_for_the_migration(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    system.published_flow_version_id = None
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "skipped"
    assert item["reason"] == "no published pointer; run migration 081 first"


def test_publishing_the_planned_baseline_makes_it_executable(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    _as_reused_077_baseline(db_session, system)
    with pytest.raises(flow_publication.FlowPublicationError) as inert:
        flow_publication.published_run_evidence(
            db_session, system=system, workspace=workspace
        )
    assert inert.value.code == "PUBLISHED_EXECUTION_CONTRACT_MISSING"

    item = backfill._plan(db_session, system, workspace)
    version, _draft, no_op = flow_publication.publish_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=int(item["draft_revision"]),
        expected_published_version_id=item["published_flow_version_id"],
        message=backfill.MESSAGE,
        breaking_change_intent="acknowledged",
        actor="system:flow-contract-backfill",
    )
    db_session.commit()

    assert no_op is False
    assert (
        backfill._publication_defects(
            version, published_digest=canonical_flow_sha256(version.flow_definition)
        )
        == []
    )
    db_session.refresh(system)
    evidence, _flow_definition, digest, contract = flow_publication.published_run_evidence(
        db_session, system=system, workspace=workspace
    )
    assert evidence.id == version.id
    assert digest == version.flow_sha256
    assert contract["contract_sha256"]


def test_legacy_mirror_drift_is_reported_as_an_apply_risk(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    _as_reused_077_baseline(db_session, system)
    # A graph edited through the legacy path after the migration.
    system.flow_definition = _flow("legacy-edit")
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "publish"
    assert item["apply_risk"]["code"] == "PUBLISHED_FLOW_MIRROR_DRIFT"
    # The annotation is not a guess: apply really does refuse this System.
    with pytest.raises(flow_publication.FlowPublicationError) as refused:
        flow_publication.publish_draft(
            db_session,
            system_id=system.id,
            workspace=workspace,
            expected_draft_revision=int(item["draft_revision"]),
            expected_published_version_id=item["published_flow_version_id"],
            message=backfill.MESSAGE,
            breaking_change_intent="acknowledged",
            actor="system:flow-contract-backfill",
        )
    assert refused.value.code == "PUBLISHED_FLOW_MIRROR_DRIFT"


def test_digest_contradicting_its_payload_is_never_planned_for_publish(db_session) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    version.execution_contract = None
    version.flow_sha256 = "0" * 64
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "skipped"
    assert item["defects"] == ["execution_contract_missing", "flow_sha256_drift"]
    with pytest.raises(flow_publication.FlowPublicationError) as refused:
        flow_publication.publish_draft(
            db_session,
            system_id=system.id,
            workspace=workspace,
            expected_draft_revision=1,
            expected_published_version_id=system.published_flow_version_id,
            message=backfill.MESSAGE,
            breaking_change_intent="acknowledged",
            actor="system:flow-contract-backfill",
        )
    assert refused.value.code == "PUBLISHED_FLOW_VERSION_HASH_DRIFT"


def test_absent_digest_under_a_valid_contract_is_flagged_as_a_possible_no_op(
    db_session,
) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    version.flow_sha256 = None
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "publish"
    assert item["publication_kind"] == "republication"
    assert item["defects"] == ["flow_sha256_missing"]
    assert item["apply_risk"]["code"] == "PUBLISHED_FLOW_VERSION_HASH_MISSING"
    # Publish is a no-op when the frozen contract still matches, so the absent
    # digest survives and the System stays unexecutable.
    _version, _draft, no_op = flow_publication.publish_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=int(item["draft_revision"]),
        expected_published_version_id=item["published_flow_version_id"],
        message=backfill.MESSAGE,
        breaking_change_intent="acknowledged",
        actor="system:flow-contract-backfill",
    )
    assert no_op is True


def _run_main(monkeypatch, db_session, tmp_path, *args: str) -> tuple[int, dict[str, Any]]:
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_flow_publication_contracts", "--report", str(report), *args],
    )
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(backfill, "SessionLocal", lambda: db_session)
    code = backfill.main()
    return code, json.loads(report.read_text(encoding="utf-8"))


def test_dry_run_declares_its_limits_and_plans_the_repairable_set(
    db_session, monkeypatch, tmp_path
) -> None:
    workspace = _workspace(db_session)
    repairable = _published_system(db_session, workspace, label="repairable")
    _as_reused_077_baseline(db_session, repairable)
    edited = _published_system(db_session, workspace, label="edited")
    _as_reused_077_baseline(db_session, edited)
    flow_publication.save_draft(
        db_session,
        system_id=edited.id,
        workspace=workspace,
        flow_definition=_flow("editor-edit"),
        expected_revision=1,
        actor="editor@example.invalid",
    )
    _published_system(db_session, workspace, label="pinned")
    db_session.commit()

    code, report = _run_main(monkeypatch, db_session, tmp_path)

    assert code == 0
    assert report["mode"] == "dry_run"
    assert report["summary"] == {
        "systems": 3,
        "already_pinned": 1,
        "publish": 1,
        "publish_initial": 1,
        "publish_republication": 0,
        "published": 0,
        "skipped": 1,
        "failed": 0,
        "at_risk": 0,
    }
    # The dry run must not read as a promise it cannot keep.
    assert any("never calls publish_draft" in limit for limit in report["limits"])
    assert any("blocking DAG diagnostic" in limit for limit in report["limits"])


def test_dry_run_refuses_to_look_green_when_apply_will_be_refused(
    db_session, monkeypatch, tmp_path
) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace, label="drifted")
    _as_reused_077_baseline(db_session, system)
    system.flow_definition = _flow("legacy-edit")
    db_session.commit()

    code, report = _run_main(monkeypatch, db_session, tmp_path)

    assert code == 1
    assert report["summary"]["publish"] == 1
    assert report["summary"]["at_risk"] == 1


def test_apply_publishes_the_repairable_set_and_reports_zero_failures(
    db_session, monkeypatch, tmp_path
) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace, label="repairable")
    baseline = _as_reused_077_baseline(db_session, system).id

    code, report = _run_main(monkeypatch, db_session, tmp_path, "--apply")

    assert code == 0
    assert report["schema_version"] == 2
    assert report["summary"]["published"] == 1
    assert report["summary"]["failed"] == 0
    assert "limits" not in report
    item = report["workspaces"][0]["systems"][0]
    assert item["action"] == "published"
    assert item["no_op"] is False
    assert item["new_published_version_id"] != baseline


def test_a_vacuous_frozen_contract_is_republished_not_reported_as_pinned(
    db_session,
) -> None:
    """The defect that made "switch the image" insufficient.

    The pointer is executable by both runtime gates, so classifying on whether
    the column is populated calls it done. It names no ingress, so every
    adapter refuses it, and freezing means the fixed compiler never reaches it.
    """

    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    stale = _as_vacuous_published_contract(db_session, system)
    assert flow_publication.published_run_evidence(
        db_session, system=system, workspace=workspace
    )[3]["ingresses"] == []

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "publish"
    assert item["publication_kind"] == "republication"
    assert item["defects"] == ["execution_contract_stale"]
    assert item["expected_contract_sha256"] != stale.execution_contract["contract_sha256"]


def test_a_second_consecutive_apply_publishes_nothing(
    db_session, monkeypatch, tmp_path
) -> None:
    """Without this the estate gains a version row on every operator run."""

    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    _as_vacuous_published_contract(db_session, system)

    first_code, first = _run_main(monkeypatch, db_session, tmp_path, "--apply")
    versions_after_first = (
        db_session.query(SystemVersion).filter(SystemVersion.system_id == system.id).count()
    )
    second_code, second = _run_main(monkeypatch, db_session, tmp_path, "--apply")

    assert first_code == 0
    assert first["summary"]["published"] == 1
    assert first["summary"]["publish_republication"] == 1
    assert second_code == 0
    assert second["summary"] == {
        "systems": 1,
        "already_pinned": 1,
        "publish": 0,
        "publish_initial": 0,
        "publish_republication": 0,
        "published": 0,
        "skipped": 0,
        "failed": 0,
        "at_risk": 0,
    }
    assert (
        db_session.query(SystemVersion).filter(SystemVersion.system_id == system.id).count()
        == versions_after_first
    )


def test_the_dry_run_separates_a_first_publication_from_a_republication(
    db_session, monkeypatch, tmp_path
) -> None:
    """A run that now touches rows an earlier run skipped must say so."""

    workspace = _workspace(db_session)
    _as_reused_077_baseline(
        db_session, _published_system(db_session, workspace, label="never-published")
    )
    _as_vacuous_published_contract(
        db_session, _published_system(db_session, workspace, label="frozen-vacuous")
    )
    _published_system(db_session, workspace, label="current")

    code, report = _run_main(monkeypatch, db_session, tmp_path)

    assert code == 0
    assert report["summary"]["publish"] == 2
    assert report["summary"]["publish_initial"] == 1
    assert report["summary"]["publish_republication"] == 1
    assert report["summary"]["already_pinned"] == 1
    kinds = {
        item["system_id"]: item.get("publication_kind")
        for item in report["workspaces"][0]["systems"]
    }
    assert sorted(filter(None, kinds.values())) == ["initial", "republication"]


def test_a_contract_that_no_longer_compiles_is_never_reported_as_verified(
    db_session,
) -> None:
    """Staleness is unknown, not absent, when the compiler refuses the payload."""

    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace)
    # A Skill bound by a node that the catalog no longer serves: the frozen
    # contract stays valid, but nothing can be recompiled to compare it against.
    flow = _flow("uncompilable")
    flow["nodes"][0]["config"]["skill_slug"] = "skill-that-was-deleted"
    system.flow_definition = flow
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    version.flow_definition = flow
    version.flow_sha256 = canonical_flow_sha256(flow)
    db_session.commit()

    item = backfill._plan(db_session, system, workspace)

    assert item["action"] == "already_pinned"
    assert item["contract_freshness"] == "unverified"
    assert item["recompile_error"]["code"] == "SKILL_CONTRACT_MISSING"


def test_apply_reports_a_publish_that_repaired_nothing_as_a_failure(
    db_session, monkeypatch, tmp_path
) -> None:
    workspace = _workspace(db_session)
    system = _published_system(db_session, workspace, label="digestless")
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    version.flow_sha256 = None
    db_session.commit()

    code, report = _run_main(monkeypatch, db_session, tmp_path, "--apply")

    assert code == 1
    assert report["summary"]["published"] == 0
    assert report["summary"]["failed"] == 1
    item = report["workspaces"][0]["systems"][0]
    assert item["action"] == "not_repaired"
    assert item["no_op"] is True
    assert item["remaining_defects"] == ["flow_sha256_missing"]
