"""Replay the unedited PIH proposal produced by the configured provider."""
import json
import pytest
from pathlib import Path
from app.tests.api.test_workspace_skill_brd_import import _seed, _client
from app.core.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("review_status", ["accepted", "rejected"])
@pytest.mark.parametrize("invalid_hitl_mapping", [False, True])
async def test_generated_pih_proposal_executes_and_resumes(db_session, tmp_path, monkeypatch, review_status, invalid_hitl_mapping):
    monkeypatch.setattr(settings, 'object_store_backend', 'local')
    monkeypatch.setattr(settings, 'object_store_base_path', str(tmp_path))
    workspace,user=_seed(db_session)
    workspace.settings={'features':{'flow_workbench_v1':True,'flow_v3_dag_authoritative':True}}
    db_session.commit()
    client=_client(db_session,workspace,user)
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures' / 'brd'
    source=(fixtures / 'pih-spark089.docx').read_bytes()
    imported=client.post('/skills/import/business-requirements?retain=true',files={'file':('pih.docx',source)})
    assert imported.status_code==200,imported.text
    path='/skills/imports/business-requirements/'+imported.json()['document']['id']+'/proposals'
    filename = 'pih-generated-invalid-hitl.json' if invalid_hitl_mapping else 'pih-generated-proposal.json'
    material=json.loads((fixtures / filename).read_text())
    response=client.post(path,json=material)
    assert response.status_code==200,response.text
    proposal=response.json()
    applied=client.post(path+'/'+proposal['id']+'/apply',json={'expected_sha256':proposal['sha256'],'reviewed':True})
    assert applied.status_code==200,applied.text

    from app.models.system_flow_draft import SystemFlowDraft
    from app.services.systems.flow_publication import create_draft_test_run
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=applied.json()["system_id"]).one()
    assert len(draft.flow_definition["nodes"]) == 6
    assert len(proposal["proposal"]["coverage"]) == 7
    assert proposal["proposal"]["coverage"][0]["section"] == "business outcomes"
    from app.services.skills_registry import wrappers
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    from app.models.decision import Decision
    from app.models.run import SkillInvocation
    prompts = []
    async def model_response(payload, ctx=None):
        prompts.append(payload["prompt"])
        return {"completion": f"stage-{len(prompts)}", "model": "test-model"}
    entry = wrappers._REGISTRY["workspace_llm_v1"]
    monkeypatch.setitem(wrappers._REGISTRY, "workspace_llm_v1", (model_response, entry[1], entry[2]))
    for case in material["cases"]:
        run = create_draft_test_run(db_session, system_id=draft.system_id,
            workspace=workspace, user_id=user.id, input_ref=case["input_ref"],
            expected_draft_revision=draft.revision, expected_flow_sha256=draft.flow_sha256)
        assert run.execution_contract["brd_origin"]["proposal_id"] == proposal["id"]
        assert run.status == "pending"  # ingress validation, not model execution

        db_session.commit()
        before = len(prompts)
        summary = await execute_run_dag(run.id)
        assert summary["status"] == "hitl_pending", summary
        assert len(prompts) == before + 3
        decision = db_session.get(Decision, summary["awaiting_decision"])
        assert decision.status == "proposed"
        still_waiting = await resume_run_dag(run.id, decision_id=decision.id)
        assert still_waiting["status"] == "hitl_pending"
        assert len(prompts) == before + 3
        wrong_decision = await resume_run_dag(run.id, decision_id="not-this-decision")
        assert wrong_decision["error"] == "hitl_decision_mismatch"
        decision.status = review_status  # engine test; UI authorization tested separately
        db_session.commit()
        resumed = await resume_run_dag(run.id, decision_id=decision.id)
        if invalid_hitl_mapping:
            assert resumed["status"] == "failed", resumed
            db_session.expire_all()
            assert run.status == "failed"
            assert any(cp.get("kind") == "variable_resolution_error" for cp in run.checkpoints)
            assert len(prompts) == before + 3
            continue
        assert resumed["status"] == "completed", resumed
        db_session.expire_all()
        assert run.output_ref["draft"] == f"stage-{before + 3}"
        assert db_session.query(SkillInvocation).filter_by(run_id=run.id).count() == 3
        assert len(prompts) == before + 3  # resumption must not rerun the LLM
