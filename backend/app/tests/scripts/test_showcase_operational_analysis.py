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
