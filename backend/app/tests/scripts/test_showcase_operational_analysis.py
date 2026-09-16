import copy

import pytest
from scripts.showcase_operational_analysis import (
    calculate,
    check,
    EXPECTED,
    ROWS,
    flow_operational_analysis,
    experience_document,
)


def test_the_published_recipe_calculates_the_fixed_reference():
    result = calculate({})
    assert result["stats"] == EXPECTED
    assert result["stats"]["largest_overrun_order"] == "NF-04"
    assert result["stats"]["largest_overrun_minutes"] == 25
    assert (
        check({"stats": result["stats"], "answer": "Explain this delay"})["human_validated"]
        is False
    )
    assert (
        check({"stats": result["stats"], "answer": "Explain this delay"})["economic_impact"] is None
    )


def test_the_reference_check_catches_a_wrong_number_or_absent_answer():
    with pytest.raises(ValueError):
        check({"stats": {**EXPECTED, "overrun_minutes": 34}, "answer": "All good"})
    with pytest.raises(ValueError):
        check({"stats": {**EXPECTED, "largest_overrun_order": "NF-01"}, "answer": "All good"})
    with pytest.raises(ValueError):
        check({"stats": EXPECTED, "answer": ""})
    with pytest.raises(ValueError):
        calculate({"rows": []})
    with pytest.raises(ValueError):
        calculate({"rows": [{**ROWS[0], "actual_minutes": -1}]})


def test_flow_has_closed_input_and_no_customer_or_external_write_tool():
    flow = flow_operational_analysis()
    assert flow["nodes"][0]["config"]["input_schema"]["additionalProperties"] is False
    assert {n.get("config", {}).get("skill_slug") for n in flow["nodes"]} == {
        None,
        "python_recipe_v1",
        "llm_rag_answer_v1",
    }
    assert all(n["kind"] != "agent_loop" for n in flow["nodes"])
    assert experience_document()["pages"][0]["components"][1]["props"]["input"] == {}


def test_example_is_releasable_with_the_existing_lifecycle(db_session):
    from app.models.workspace import Workspace
    from app.models.system import System
    from app.models.skill import Skill
    from app.services.skills_registry.seed import seed_skills_and_capabilities
    from app.services.systems.flow_publication import initialize_new_system_publication_if_enabled
    from scripts.showcase_operational_analysis import ensure_experience
    from app.models.experience import ExperienceRelease, ExperienceDeployment

    workspace = Workspace(
        id="showcase-ops",
        slug="agentium-showcase",
        name="Showcase",
        settings={"features": {"experience_v1": True, "adoption_experience_v1": True}},
    )
    db_session.add(workspace)
    db_session.commit()
    seed_skills_and_capabilities(db_session)
    skills = (
        db_session.query(Skill)
        .filter(Skill.slug.in_(["python_recipe_v1", "llm_rag_answer_v1"]))
        .all()
    )
    system = System(
        id="showcase-ops-system",
        workspace_id=workspace.id,
        name="Operational Analysis",
        status="active",
        skill_ids=[s.id for s in skills],
        flow_definition=flow_operational_analysis(),
        settings={"showcase_seed": True},
    )
    db_session.add(system)
    db_session.flush()
    initialize_new_system_publication_if_enabled(
        db_session, system=system, workspace=workspace, actor="showcase-seed"
    )
    db_session.commit()
    experience = ensure_experience(db_session, workspace, system)
    assert experience.slug == "operational-analysis"
    deployment = db_session.query(ExperienceDeployment).filter_by(experience_id=experience.id).one()
    assert deployment.channel == "live"
    assert ensure_experience(db_session, workspace, system).id == experience.id
    assert db_session.query(ExperienceRelease).filter_by(experience_id=experience.id).count() == 1


def _flow_before_review():
    flow = flow_operational_analysis()
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] not in {"review", "allow_review"}]
    nodes = {node["id"]: node for node in flow["nodes"]}
    nodes["sink"]["config"] = {"output_schema": copy.deepcopy(nodes["check"]["config"]["output_schema"])}
    flow["edges"] = [edge for edge in flow["edges"] if not {"review", "allow_review"}.intersection((edge["from"], edge["to"]))]
    return flow


def test_scoped_install_is_idempotent_and_preserves_published_edits(db_session, monkeypatch):
    from scripts import showcase_operational_analysis as example
    from scripts.showcase_operational_analysis import install
    from app.models.workspace import Workspace
    from app.models.system import System
    from app.models.system_flow_draft import SystemFlowDraft
    from app.models.system_version import SystemVersion
    from app.models.system_binding import SystemBinding
    from app.models.experience import ExperienceRelease, ExperienceDeployment
    from app.services.skills_registry.seed import seed_skills_and_capabilities
    from app.services.systems.flow_publication import save_draft

    workspace = Workspace(id="install-ops", slug="agentium-showcase", name="Showcase",
        settings={"showcase_seed": True, "features": {"experience_v1": True, "adoption_experience_v1": True}})
    db_session.add(workspace)
    db_session.commit()
    seed_skills_and_capabilities(db_session)
    assert install(db_session)["applied"] is False
    assert db_session.query(System).count() == 0
    with monkeypatch.context() as legacy:
        legacy.setattr(example, "flow_operational_analysis", _flow_before_review)
        first = install(db_session, apply=True)
    system = db_session.get(System, first["system_id"])
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    authored_flow = copy.deepcopy(draft.flow_definition)
    authored_flow["nodes"][0]["label"] = "Authored draft awaiting review"
    save_draft(db_session, system_id=system.id, workspace=workspace,
        flow_definition=authored_flow, expected_revision=draft.revision, actor="reviewer")
    system.objective = "An authored objective, preserved by reinstall"
    release = db_session.query(ExperienceRelease).one()
    release_content = copy.deepcopy((release.pages, release.bindings_snapshot))
    draft_revision = draft.revision
    db_session.commit()
    assert install(db_session, apply=True) == first
    assert system.objective == "An authored objective, preserved by reinstall"
    assert system.flow_definition == _flow_before_review()
    assert db_session.get(SystemVersion, first["published_flow_version_id"]).flow_definition == _flow_before_review()
    assert draft.flow_definition == authored_flow
    assert draft.revision == draft_revision
    assert db_session.query(SystemBinding).one().published_flow_version_id == first["published_flow_version_id"]
    assert db_session.query(ExperienceDeployment).one().release_id == release.id
    assert (release.pages, release.bindings_snapshot) == release_content
    assert db_session.query(System).count() == 1
    assert db_session.query(SystemVersion).count() == 1
    assert db_session.query(ExperienceRelease).count() == 1


def test_full_showcase_reseed_preserves_operational_publication_and_draft(db_session, monkeypatch):
    from scripts import seed_showcase_workspace as seed
    from app.models.system_flow_draft import SystemFlowDraft
    from app.models.system_version import SystemVersion
    from app.services.systems.flow_publication import save_draft

    workspace = seed.ensure_workspace(db_session, "agentium-showcase-r4-test", "Showcase")
    seed.seed_skills_and_capabilities(db_session)
    policies = seed.ensure_policies(db_session, workspace)
    capabilities = seed.ensure_capabilities(db_session, workspace)
    with monkeypatch.context() as legacy:
        legacy.setattr(seed, "flow_operational_analysis", _flow_before_review)
        system = seed.ensure_systems(db_session, workspace, capabilities, policies)["operational_analysis"]
    published_id = system.published_flow_version_id
    versions_before = db_session.query(SystemVersion).filter_by(system_id=system.id).count()
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    authored_flow = copy.deepcopy(draft.flow_definition)
    authored_flow["nodes"][0]["label"] = "Authored operational draft"
    save_draft(db_session, system_id=system.id, workspace=workspace,
        flow_definition=authored_flow, expected_revision=draft.revision, actor="reviewer")
    revision_before = draft.revision
    system.objective = "Authored objective"
    db_session.commit()

    seed.ensure_systems(db_session, workspace, capabilities, policies)

    assert system.published_flow_version_id == published_id
    assert system.flow_definition == _flow_before_review()
    assert db_session.get(SystemVersion, published_id).flow_definition == _flow_before_review()
    assert draft.flow_definition == authored_flow
    assert draft.revision == revision_before
    assert system.objective == "Authored objective"
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == versions_before


@pytest.mark.parametrize("verdict", ["accepted", "rejected", "regression"])
async def test_published_example_requires_review_after_the_reference_check(db_session, monkeypatch, verdict):
    from app.models.decision import Decision
    from app.models.run import Run, SkillInvocation
    from app.models.workspace import Workspace
    from app.services.run_engine import engine
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    from app.services.skills_registry.seed import seed_skills_and_capabilities
    from app.services.systems.flow_ingress import create_published_ingress_run
    from scripts.showcase_operational_analysis import CALCULATE_CODE, install

    workspace = Workspace(id="review-ops", slug="agentium-showcase", name="Showcase",
        settings={"showcase_seed": True, "features": {"experience_v1": True, "adoption_experience_v1": True}})
    db_session.add(workspace)
    db_session.commit()
    seed_skills_and_capabilities(db_session)
    installed = install(db_session, apply=True)
    answer = "NF-04 has the largest overrun, +25 minutes. Investigate its recorded work steps."

    async def recipe(inputs, ctx):
        namespace = {}
        code = inputs["_recipe"]["code"]
        exec(compile(code, "<operational-test-recipe>", "exec"), namespace)
        result = namespace["main"](inputs)
        if verdict == "regression" and code == CALCULATE_CODE:
            result["stats"]["overrun_minutes"] = 34
        return result

    async def explain(inputs, ctx):
        return {"answer": answer}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: {
        "python_recipe_v1": recipe, "llm_rag_answer_v1": explain,
    }[slug])
    run = create_published_ingress_run(db_session, system_id=installed["system_id"],
        workspace=workspace, ingress_id="src", kind="manual", payload={})
    run_id = run.id
    db_session.commit()
    paused = await execute_run_dag(run_id)
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    if verdict == "regression":
        assert paused["status"] == "failed"
        assert db_session.query(Decision).filter_by(target_id=run_id, kind="hitl_approval").count() == 0
        assert not run.output_ref
        return

    assert paused["status"] == "hitl_pending"
    assert not run.output_ref
    decision = db_session.get(Decision, paused["awaiting_decision"])
    assert decision.rationale["node_id"] == "review"
    evidence = decision.rationale["upstream"]
    assert evidence["stats"] == EXPECTED
    assert evidence["answer"] == answer
    assert evidence["numerical_reference_passed"] is True
    assert evidence["human_validated"] is False
    assert evidence.get("economic_impact") is None
    assert decision.expiry_action == "reject"
    assert (await resume_run_dag(run_id, decision_id=decision.id))["status"] == "hitl_pending"
    decision.status = verdict
    decision.approved_by = "reviewer@example.test"
    db_session.commit()

    assert (await resume_run_dag(run_id, decision_id=decision.id))["status"] == "completed"
    db_session.expire_all()
    output = db_session.get(Run, run_id).output_ref
    assert output["stats"] == EXPECTED
    assert output["answer"] == answer
    assert output["human_validated"] is (verdict == "accepted")
    assert output["economic_impact"] is None
    assert output["review_decision_id"] == decision.id
    assert output["review_status"] == verdict
    assert output["reviewed_by"] == "reviewer@example.test"
    assert db_session.query(SkillInvocation).filter_by(run_id=run_id).count() == 3


def test_scoped_install_requires_structural_showcase_marker(db_session):
    from scripts.showcase_operational_analysis import install
    from app.models.workspace import Workspace
    from app.models.system import System
    from app.services.seed_catalog_safety import SeedWorkspaceBoundaryError

    db_session.add(Workspace(id="not-showcase", slug="agentium-showcase", name="Client",
        settings={"features": {"experience_v1": True, "adoption_experience_v1": True}}))
    db_session.commit()
    with pytest.raises(SeedWorkspaceBoundaryError):
        install(db_session, apply=True)
    assert db_session.query(System).count() == 0
