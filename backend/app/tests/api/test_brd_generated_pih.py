"""Replay the unedited PIH proposal produced by the configured provider."""
import json
from pathlib import Path
from app.tests.api.test_workspace_skill_brd_import import _seed, _client
from app.core.config import settings


def test_generated_pih_proposal_creates_executable_draft(db_session, tmp_path, monkeypatch):
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
    material=json.loads((fixtures / 'pih-generated-proposal.json').read_text())
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
    for case in material["cases"]:
        run = create_draft_test_run(db_session, system_id=draft.system_id,
            workspace=workspace, user_id=user.id, input_ref=case["input_ref"],
            expected_draft_revision=draft.revision, expected_flow_sha256=draft.flow_sha256)
        assert run.execution_contract["brd_origin"]["proposal_id"] == proposal["id"]
        assert run.status == "pending"  # ingress validation, not model execution
