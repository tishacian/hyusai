"""One retained upload, real worker and source locators; synthetic QA only."""
import argparse, fcntl, hashlib, json, sys, time, urllib.request, urllib.parse, uuid
from pathlib import Path
sys.path.insert(0, '/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
p = argparse.ArgumentParser(); p.add_argument('--upload', action='store_true'); args=p.parse_args()
report=Path('/tmp/ocr-locators-bb467f53.json')
lock=report.with_suffix('.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
sha='bb467f534d40b2bfa1faf624b32d726f8e405e4c'
slug='qa-document-ocr-bb467f53'
files=[Path('/tmp/agentium-r2-ocr/Invoice_INV-8834_Synthetic_Scan.pdf')]
state=json.loads(report.read_text()) if report.exists() else {'sha':sha,'collection_slug':slug,'kind':'synthetic technical qualification, not client knowledge'}
assert state['sha']==sha and state['collection_slug']==slug

def save():
    tmp=report.with_suffix('.tmp'); tmp.write_text(json.dumps(state,indent=2)); tmp.replace(report)

client=Client('https://agentium.papai.ai/api/v1','/root/.attestation-username','/root/.attestation-password')
assert client.call('/build-info')['revision']==sha
if 'receipt' not in state:
    assert args.upload, 'Explicit --upload required for the first request'
    assert 'upload_intent' not in state, 'An upload may already exist: inspect collection/jobs, never upload again blindly'
    state['upload_intent']={f.name:{'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in files}; save()
    boundary='AgentiumQA'+uuid.uuid4().hex
    parts=[f'--{boundary}\r\nContent-Disposition: form-data; name="collection_name"\r\n\r\n{slug}\r\n'.encode()]
    for f in files:
        parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{f.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),f.read_bytes(),b'\r\n']
    parts.append(f'--{boundary}--\r\n'.encode())
    req=urllib.request.Request(client.base+'/documents/upload-batch',data=b''.join(parts),headers={'Authorization':'Bearer '+client.token,'X-Workspace-Slug':'agentium-showcase','Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(req,timeout=90) as r: state['receipt']=json.load(r)
    save()
receipt=state['receipt']; assert receipt['collection_name']==slug and receipt['job_id']
deadline=time.monotonic()+240
while True:
    state['job']=client.call('/documents/jobs/'+receipt['job_id']); save()
    if state['job']['status'] not in {'queued','running'}: break
    if time.monotonic()>deadline:
        print(json.dumps({'status':'still_active','job_id':receipt['job_id']})); raise SystemExit(2)
    time.sleep(3)
assert state['job']['status']=='completed', state['job'].get('error')
assert not state['job']['celery_task_id'].startswith('eager:')
state['inventory']=client.call('/documents/collections/'+receipt['collection_id']+'/inventory'); save()

state['facts']=client.call('/documents/document-facts?'+urllib.parse.urlencode({'collection_name':slug,'semantic_type':'document_ocr_text'})); save()
state['search']=client.call('/documents/search',{'query':'INV-8834 invoice total due QAR','top_k':5,'collection_name':slug}); save()
hits=[h for h in state['search']['results'] if h['metadata'].get('document_filename')==files[0].name and 'INV-8834' in h['content']]
assert hits, 'No source-backed invoice text retrieved from image-only PDF'
hit=hits[0]; meta=hit['metadata']
assert meta.get('page')==1 and '9,860.00' in hit['content']
facts=state['facts']['items']
assert any(f.get('page')==1 and 'INV-8834' in f['content'] and (f.get('evidence_locator') or {}).get('provider') for f in facts), 'No persisted OCR-provider evidence'
params={'collection_name':slug,'filename':files[0].name}
state['preview']=client.call('/documents/'+meta['document_id']+'/rich-preview?'+urllib.parse.urlencode(params)); save()
assert state['preview']['kind']=='pdf'
url=state['preview']['download_url']; assert url.startswith('/api/v1/documents/')
req=urllib.request.Request('https://agentium.papai.ai'+url,headers={'Authorization':'Bearer '+client.token,'X-Workspace-Slug':'agentium-showcase'})
with urllib.request.urlopen(req,timeout=60) as r: digest=hashlib.sha256(r.read()).hexdigest()
assert digest==state['upload_intent'][files[0].name]['sha256']
state.update(status='verified',original_sha256=digest); save()
print(json.dumps({'status':'verified','job_id':receipt['job_id'],'collection':slug,'page':1,'ocr_facts':len(facts)}))
