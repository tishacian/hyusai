"""Read-only recheck against the retained failing retrieval; no re-upload or Run."""
import hashlib,json,sys,urllib.parse,urllib.request
from pathlib import Path
sys.path.insert(0,'/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
source=Path('/tmp/document-locators-37056391.json')
before=json.loads(source.read_text())
sha='bb467f534d40b2bfa1faf624b32d726f8e405e4c'
client=Client('https://agentium.papai.ai/api/v1','/root/.attestation-username','/root/.attestation-password')
assert client.call('/build-info')['revision']==sha
hit=before['previews']['excel']['hit']; meta=hit['metadata']
job=client.call('/documents/jobs/'+before['job']['id'])
assert job==before['job'], 'Source job changed; review the retained evidence before qualification'
params={'collection_name':before['collection_slug'],'filename':meta['document_filename'],
        'sheet_name':meta['sheet_name'],'cell_range':meta['cell_range']}
preview=client.call('/documents/'+meta['document_id']+'/rich-preview?'+urllib.parse.urlencode(params))
report={'sha':sha,'source_report_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'retained_job_id':job['id'],'retained_celery_task_id':job['celery_task_id'],
        'retained_hit_id':hit['id'],'rank':before['previews']['excel']['rank'],
        'params':params,'before_preview':before['previews']['excel']['preview'],'after_preview':preview,
        'job_unchanged':True,'status':'observed'}
path=Path('/tmp/wide-citation-bb467f53.json')
path.write_text(json.dumps(report,indent=2))
assert preview['sheet_name']=='Interventions & notes' and preview['cell_range']=='A830:O831'
assert preview['selection']==before['previews']['excel']['preview']['selection']
assert preview['selection_truncated'] is False
for row,label,amount in [(830,'NF-04','55'),(831,'NF-05','0')]:
 cells=preview['rows'][row-preview['row_start']]
 assert cells[14-preview['column_start']]==label and cells[15-preview['column_start']]==amount
url=preview['download_url']; assert url.startswith('/api/v1/documents/')
req=urllib.request.Request('https://agentium.papai.ai'+url,headers={'Authorization':'Bearer '+client.token,'X-Workspace-Slug':'agentium-showcase'})
with urllib.request.urlopen(req,timeout=60) as r: digest=hashlib.sha256(r.read()).hexdigest()
assert digest==before['upload_intent']['history.xlsx']['sha256']
report.update(status='verified',original_sha256=digest)
path.write_text(json.dumps(report,indent=2))
print(json.dumps({'status':'verified','sha':sha,'range':params['cell_range'],'source_job_unchanged':True}))
