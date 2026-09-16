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

def remote_completion(prompt, evidence, token_limit, *, json_output=False):
    program = "PROMPT = " + repr(prompt) + "\nTOKEN_LIMIT = " + str(token_limit) + "\nJSON_OUTPUT = " + repr(json_output) + "\n" + """
import asyncio,json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.model_plane.execution import resolve_model_execution,complete_model
with SessionLocal() as db:
    ws=db.query(Workspace).filter_by(slug='agentium-showcase').one()
    execution=resolve_model_execution(ws,provider='workspace')
    out=asyncio.run(complete_model(execution,PROMPT,{'_model_workspace':ws},generation_options={'max_completion_tokens':TOKEN_LIMIT,'reasoning_effort':'low',**({'response_format':{'type':'json_object'}} if JSON_OUTPUT else {})},stream=False))
    out["model_execution"] = execution.public()
    print(json.dumps(out,default=str))
"""
    started=time.monotonic()
    call=subprocess.run(['ssh','omnirag-demo','docker exec -i agentium-backend python'],
        input=program,text=True,capture_output=True,timeout=180,check=True)
    output=json.loads(call.stdout.splitlines()[-1])
    with (evidence/'provider-calls.jsonl').open('a') as f:
        f.write(json.dumps({'seconds':time.monotonic()-started,'output':output})+'\n')
    return output


def northforge_catalog(db_session, workspace, client):
    from app.models.skill import Skill
    from app.services.skills_registry.seed import SEED_SKILLS
    from scripts.showcase_intervention import retrieval_tool_specs
    planner = next(row for row in SEED_SKILLS if row["slug"] == "decide_next_v1")
    workspace.settings = {"catalog": {"enabled_skills": ["decide_next_v1"]},
                          "features": {"flow_workbench_v1": True, "flow_v3_dag_authoritative": True}}
    db_session.add(Skill(**planner, is_seeded="Y"))
    db_session.commit()
    slugs = ["decide_next_v1"]
    for spec in retrieval_tool_specs("agentium-showcase-notices", "agentium-showcase-intervention-history"):
        response = client.post('/skills', json=spec)
        assert response.status_code == 200, response.text
        slugs.append(response.json()["slug"])
    return slugs


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
        return remote_completion(payload["prompt"], evidence, 4000)
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


@pytest.mark.skipif(not os.environ.get("BRD_LIVE_GENERATION_DIR"), reason="Opt-in real generation worker")
def test_live_generation_worker(db_session, tmp_path, monkeypatch):
    from contextlib import nullcontext
    from app.db import base
    from app.models.workspace_job import WorkspaceJob
    from app.services import workspace_jobs
    from app.services.skills_registry import brd_generation as service
    from app.services.model_plane.execution import ModelExecution
    evidence = Path(os.environ["BRD_LIVE_GENERATION_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    monkeypatch.setattr(base, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(workspace_jobs, "dispatch_workspace_job", lambda *a, **k: "local-qualification")
    monkeypatch.setattr(service, "resolve_model_execution", lambda *a, **k:
        ModelExecution(provider="openai", model="remote-workspace-resolved", credential_source="workspace", model_source="workspace"))
    replay_path = os.environ.get("BRD_GENERATION_REPLAY")
    recorded_outputs = ([json.loads(line)["output"] for line in Path(replay_path).read_text().splitlines()]
                        if replay_path else [])
    async def complete(execution, prompt, context, **options):
        with (evidence/"generation-prompts.jsonl").open("a") as stream:
            stream.write(json.dumps({"prompt": prompt}) + "\n")
        if replay_path:
            assert recorded_outputs, "Recorded provider outputs exhausted; no implicit live retry"
            (evidence/'replay-source.txt').write_text(replay_path)
            return recorded_outputs.pop(0)
        return remote_completion(prompt, evidence, 10000, json_output=True)
    monkeypatch.setattr(service, "complete_model", complete)
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    family = os.environ.get("BRD_LIVE_FAMILY", "document_summary")
    assert family in {"document_summary", "intervention_preparation"}
    slugs = []
    fixture = "pih-spark089.docx"
    if family == "intervention_preparation":
        slugs = northforge_catalog(db_session, workspace, client)
        fixture = "northforge-intervention.docx"
    source = Path(__file__).resolve().parents[1] / "fixtures/brd" / fixture
    imported = client.post('/skills/import/business-requirements?retain=true',
        files={'file': (fixture, source.read_bytes())})
    assert imported.status_code == 200, imported.text
    (evidence/'import.json').write_text(json.dumps(imported.json(), indent=2))
    document = imported.json()['document']['id']
    job = client.post(f'/skills/imports/business-requirements/{document}/generations',
        json={'request_key': 'live-worker', 'family': family, 'name': family + ' live worker',
              'skill_slugs': slugs})
    assert job.status_code == 200, job.text
    result = service.run_generation_job(job.json()['id'])
    db_session.expire_all()
    row = db_session.get(WorkspaceJob, job.json()['id'])
    (evidence/'job.json').write_text(json.dumps({'status': row.status, 'result': row.result, 'error': row.error},indent=2,default=str))
    assert result['status'] == 'completed', row.result
    proposal = row.result['proposal']
    material = {key: proposal[key] for key in ('name', 'objective', 'flow_definition', 'skills', 'cases', 'mappings')}
    material['request_key'] = 'live-worker-runtime'
    (evidence/'candidate.json').write_text(json.dumps(material,indent=2))


def remote_retrieval(payload, evidence):
    collection = payload.get('context_collection')
    assert collection in {'agentium-showcase-notices', 'agentium-showcase-intervention-history'}
    request = {'query': payload['query'], 'context_collection': collection, 'top_k': 5,
               'latency_profile': 'balanced'}
    program = 'REQUEST = ' + repr(request) + '\n' + """
import asyncio,json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.skills_registry.executors import bind_executor
with SessionLocal() as db:
    ws=db.query(Workspace).filter_by(slug='agentium-showcase').one()
    tool=bind_executor({'kind':'registry_call','params':{'skill_slug':'semantic_search_v1',
        'frozen_input':{'context_collection':REQUEST['context_collection'],'top_k':5,'latency_profile':'balanced'}}})
    out=asyncio.run(tool(REQUEST,{'workspace_id':ws.id,'workspace_slug':ws.slug,'_model_workspace':ws}))
    print(json.dumps(out,default=str))
"""
    started = time.monotonic()
    call = subprocess.run(['ssh', 'omnirag-demo', 'docker exec -i agentium-backend python'],
                          input=program, text=True, capture_output=True, timeout=180, check=True)
    output = json.loads(call.stdout.splitlines()[-1])
    with (evidence/'retrieval-calls.jsonl').open('a') as stream:
        stream.write(json.dumps({'request': request, 'output': output,
                                 'seconds': time.monotonic()-started})+'\n')
    return output


@pytest.mark.skipif(not os.environ.get('BRD_NORTHFORGE_CANDIDATE'), reason='Opt-in live NorthForge tools')
@pytest.mark.asyncio
async def test_live_northforge_candidate(db_session, tmp_path, monkeypatch):
    from app.models.system_flow_draft import SystemFlowDraft
    from app.models.run import SkillInvocation
    from app.services.systems.flow_publication import create_draft_test_run
    from app.services.run_engine.dag import execute_run_dag
    from app.services.skills_registry import wrappers
    evidence = Path(os.environ['BRD_LIVE_EVIDENCE_DIR'])
    evidence.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, 'object_store_backend', 'local')
    monkeypatch.setattr(settings, 'object_store_base_path', str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    northforge_catalog(db_session, workspace, client)
    source = Path(__file__).parents[1]/'fixtures/brd/northforge-intervention.docx'
    imported = client.post('/skills/import/business-requirements?retain=true',
                           files={'file': (source.name, source.read_bytes())})
    assert imported.status_code == 200, imported.text
    path = '/skills/imports/business-requirements/'+imported.json()['document']['id']+'/proposals'
    material = json.loads(Path(os.environ['BRD_NORTHFORGE_CANDIDATE']).read_text())
    proposal = client.post(path, json=material)
    assert proposal.status_code == 200, proposal.text
    proposal = proposal.json()
    applied = client.post(path+'/'+proposal['id']+'/apply',
                          json={'expected_sha256': proposal['sha256'], 'reviewed': True})
    (evidence/'application.json').write_text(json.dumps(applied.json(), indent=2))
    assert applied.status_code == 200, applied.text
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=applied.json()['system_id']).one()
    async def complete(prompt, model, ctx):
        return remote_completion(prompt, evidence, 4000)['completion']
    monkeypatch.setattr(wrappers, '_route_llm_complete', complete)
    async def model_response(payload, ctx=None):
        return remote_completion(payload['prompt'], evidence, 4000)
    async def retrieve(payload, ctx=None):
        return remote_retrieval(payload, evidence)
    for slug, fn in [('workspace_llm_v1', model_response), ('semantic_search_v1', retrieve)]:
        entry = wrappers._REGISTRY[slug]
        monkeypatch.setitem(wrappers._REGISTRY, slug, (fn, entry[1], entry[2]))
    failures = []
    for case in material['cases']:
        run = create_draft_test_run(db_session, system_id=draft.system_id, workspace=workspace,
            user_id=user.id, input_ref=case['input_ref'], expected_draft_revision=draft.revision,
            expected_flow_sha256=draft.flow_sha256)
        db_session.commit()
        result = await execute_run_dag(run.id)
        db_session.expire_all()
        calls = db_session.query(SkillInvocation).filter_by(run_id=run.id).all()
        record = {'case': case, 'result': result, 'status': run.status, 'output': run.output_ref,
                  'checkpoints': run.checkpoints, 'review': 'not_performed',
                  'invocations': [{'id': row.id, 'skill': row.skill_slug, 'status': row.status,
                                   'input': row.input_ref, 'output': row.output_ref} for row in calls]}
        from app.models.decision import Decision
        decision = db_session.get(Decision, result['awaiting_decision']) if result.get('awaiting_decision') else None
        review_nodes = {node['id'] for node in draft.flow_definition['nodes'] if node.get('kind') == 'hitl'}
        record['decision_node'] = (decision.rationale or {}).get('node_id') if decision else None
        (evidence/(case['id']+'.json')).write_text(json.dumps(record, indent=2, default=str))
        if result['status'] != 'hitl_pending' or record['decision_node'] not in review_nodes:
            failures.append({'case': case['id'], 'result': result, 'decision_node': record['decision_node']})
    assert not failures, failures
