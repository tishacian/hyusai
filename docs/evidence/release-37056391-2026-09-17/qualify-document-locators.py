"""One retained upload, real worker and source locators; synthetic QA only."""
import argparse, fcntl, hashlib, json, sys, time, urllib.request, urllib.parse, uuid
from pathlib import Path
sys.path.insert(0, '/opt/agentium-protected-runner/repos/omnirag/scripts/qualification')
from observability_live import Client
p = argparse.ArgumentParser(); p.add_argument('--upload', action='store_true'); args=p.parse_args()
report=Path('/tmp/document-locators-37056391.json')
lock=report.with_suffix('.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
sha='37056391d6cc315c72495f973fb6fe0e2072ed68'
slug='qa-document-locators-37056391'
files=[Path('/tmp/agentium-r2-preview/history.xlsx'), Path('/opt/agentium-protected-runner/repos/omnirag/backend/app/tests/fixtures/po_invoice_recon/Invoice_INV-8834_Sample.pdf')]
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
state.setdefault('search',{})
for name,query in [('excel','NF-04 55 Interventions notes'),('pdf','INV-8834 total invoice 9860')]:
    if name not in state['search']:
        state['search'][name]=client.call('/documents/search',{'query':query,'top_k':10,'collection_name':slug}); save()
state.setdefault('previews',{})
for name in ['excel','pdf']:
    for rank,hit in enumerate(state['search'][name]['results']):
        meta=hit.get('metadata') or {}; filename=meta.get('document_filename') or meta.get('filename')
        if filename not in {f.name for f in files}: continue
        if name=='excel' and (filename!='history.xlsx' or 'NF-04' not in hit['content'] or '55' not in hit['content'] or meta.get('semantic_type')=='spreadsheet_schema'): continue
        if name=='pdf' and (not filename.endswith('.pdf') or 'INV-8834' not in hit['content']): continue
        params={'collection_name':slug,'filename':filename}
        if name=='excel':
            assert meta.get('sheet_name')=='Interventions & notes' and meta.get('cell_range'), meta
            params.update(sheet_name=meta['sheet_name'],cell_range=meta['cell_range'])
        doc_id=meta['document_id']
        preview=client.call('/documents/'+doc_id+'/rich-preview?'+urllib.parse.urlencode(params))
        state['previews'][name]={'rank':rank+1,'hit':hit,'preview':preview}; save(); break
    assert name in state['previews'], 'No matching retrieved source: '+name
excel=state['previews']['excel']['preview']
assert excel['kind']=='spreadsheet' and excel['sheet_name']=='Interventions & notes'
assert excel['selection']['row_start']<=830<=excel['selection']['row_end']
row=excel['rows'][830-excel['row_start']]
assert str(row[14-excel['column_start']])=='NF-04' and str(row[15-excel['column_start']])=='55', row
assert excel['selection_truncated'] is False
pdf=state['previews']['pdf']
assert pdf['preview']['kind']=='pdf'
assert pdf['hit']['metadata'].get('page',pdf['hit']['metadata'].get('page_number'))==1
state.setdefault('original_checksums',{})
for name,value in state['previews'].items():
    preview=value['preview']; path=preview['download_url']
    assert path.startswith('/api/v1/documents/')
    request=urllib.request.Request('https://agentium.papai.ai'+path,headers={'Authorization':'Bearer '+client.token,'X-Workspace-Slug':'agentium-showcase'})
    with urllib.request.urlopen(request,timeout=90) as response: actual=hashlib.sha256(response.read()).hexdigest()
    filename=value['hit']['metadata']['document_filename']
    assert actual==state['upload_intent'][filename]['sha256']
    state['original_checksums'][name]=actual; save()
state['status']='verified'; save()
print(json.dumps({'status':state['status'],'job_id':receipt['job_id'],'collection':slug,'excel_locator':excel['cell_range'],'pdf_page':1}))
