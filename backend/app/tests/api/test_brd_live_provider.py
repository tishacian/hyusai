"""Opt-in PIH runtime recorder: engine assertions are not quality acceptance.

Set BRD_LIVE_CANDIDATE and a fresh BRD_LIVE_EVIDENCE_DIR. This uses the
configured Showcase provider remotely; local Runs never touch production DB.
Inspect every retained assertion verdict and output, even when pytest passes.
"""
import json
import os
import subprocess
import time
import pytest
from pathlib import Path
from app.tests.api.test_workspace_skill_brd_import import _seed, _client
from app.core.config import settings


@pytest.mark.skipif(not os.environ.get("BRD_LIVE_EVIDENCE_DIR"), reason="Opt-in real provider qualification")
@pytest.mark.asyncio
async def test_live_pih_candidate(db_session, tmp_path, monkeypatch):
    evidence = Path(os.environ["BRD_LIVE_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
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
    material=json.loads(Path(os.environ['BRD_LIVE_CANDIDATE']).read_text())
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
        # Only the provider boundary uses the deployed workspace configuration.
        # Test objects and Runs stay in the isolated local database.
        program = "PROMPT = " + repr(payload["prompt"]) + "\n" + """
import asyncio,json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.model_plane.execution import resolve_model_execution,complete_model
with SessionLocal() as db:
    ws=db.query(Workspace).filter_by(slug='agentium-showcase').one()
    execution=resolve_model_execution(ws,provider='workspace')
    out=asyncio.run(complete_model(execution,PROMPT,{'_model_workspace':ws},generation_options={'max_completion_tokens':4000,'reasoning_effort':'low'},stream=False))
    print(json.dumps(out,default=str))
"""
        started=time.monotonic()
        call=subprocess.run(['ssh','omnirag-demo','docker exec -i agentium-backend python'],
            input=program,text=True,capture_output=True,timeout=180,check=True)
        output=json.loads(call.stdout.splitlines()[-1])
        with (evidence/'provider-calls.jsonl').open('a') as f:
            f.write(json.dumps({'seconds':time.monotonic()-started,'output':output})+'\n')
        return output
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
        decision.status = "accepted"  # engine test; UI authorization tested separately
        db_session.commit()
        resumed = await resume_run_dag(run.id, decision_id=decision.id)
        assert resumed["status"] == "completed", resumed
        db_session.expire_all()
        from app.services.evaluation.campaigns import assertion_results
        result = {"case_id": case["id"], "run_id": run.id, "output": run.output_ref,
                  "assertions": assertion_results(run.output_ref, case["assertions"]),
                  "review": "harness_acceptance_not_human"}
        (evidence/(case["id"]+'.json')).write_text(json.dumps(result,indent=2))
        assert db_session.query(SkillInvocation).filter_by(run_id=run.id).count() == 3
        assert len(prompts) == before + 3
